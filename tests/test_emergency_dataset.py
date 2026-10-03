"""Integrity checks on services/emergency_numbers.json.

The resolver can only be as safe as the data under it. These tests fail the
build on the two ways the dataset itself can hurt someone: a number that no
handset can dial, and a number that belongs to a different country than the
record it sits in.

No network and no keys required.
"""
import hashlib
import json
import re

import pytest

# Integrity assertions over the shipped emergency numbers directory.
pytestmark = pytest.mark.dataset

import services.emergency as em

# The shipped file, read directly. Going through _load_emergency_numbers()
# would try S3 first, so on a machine with AWS credentials these tests would
# silently check whatever the bucket holds instead of this repository.
with open(em.DATA_FILE, "rb") as _f:
    RAW = _f.read()
DATA = json.loads(RAW)

# s3://saayam-virginia-public/emergency_contact.json is the ground truth and
# this file is its fallback copy. This is the object's ETag, which for a
# single-part SSE-S3 upload is the MD5 of its bytes.
S3_GROUND_TRUTH_MD5 = "712452bd2f3db75e71c7300959b61f69"

# Numbers that are North American mental health crisis numbers (988 is legitimate
# in US and Canada, but must not leak into any other jurisdiction).
US_AND_CA_ONLY_NUMBERS = {"988"}


def iter_service_maps():
    """Yield (path, country_code, services) for every service map in the file."""
    for country_code, country in DATA.items():
        if country.get("default"):
            yield f"{country_code}.default", country_code, country["default"]
        for state_name, state in country.get("states", {}).items():
            if state.get("default"):
                yield (
                    f"{country_code}.{state_name}.default",
                    country_code,
                    state["default"],
                )
            for bucket in ("cities", "zips"):
                for key, services in state.get(bucket, {}).items():
                    yield (
                        f"{country_code}.{state_name}.{bucket}.{key}",
                        country_code,
                        services,
                    )


ALL_SERVICE_MAPS = list(iter_service_maps())


def test_bundled_file_is_the_s3_ground_truth():
    """The fallback must say exactly what S3 says.

    The bundled file answers whenever S3 cannot be read. If the two drift, a
    network blip changes the numbers a person is shown. When the S3 object is
    updated, copy it here byte for byte and update S3_GROUND_TRUTH_MD5 to the
    new ETag in the same change.
    """
    assert hashlib.md5(RAW).hexdigest() == S3_GROUND_TRUTH_MD5


def test_the_shipped_file_passes_the_loader_shape_check():
    """The loader rejects a misshapen dataset; the shipped one must not be."""
    assert em._validate_dataset(DATA) is DATA


def test_the_file_is_not_empty():
    assert len(DATA) >= 70, f"only {len(DATA)} countries loaded"
    assert ALL_SERVICE_MAPS


def test_country_keys_are_iso_alpha2():
    bad = [c for c in DATA if not re.fullmatch(r"[A-Z]{2}", c)]
    assert not bad, f"not ISO-3166 alpha-2 country codes: {bad}"


def test_every_number_is_dialable():
    """No blanks, no prose, no truncated values.

    This is the test that catches the class of bug behind Australia being
    stored as "0" (a lost leading zero on Triple Zero) and Pakistan's ambulance
    being stored as the sentence "115 and 1122".
    """
    bad = [
        f"{path}.{service} = {number!r}"
        for path, _country, services in ALL_SERVICE_MAPS
        for service, number in services.items()
        if not em.is_dialable(number)
    ]
    assert not bad, "numbers that cannot be dialed:\n  " + "\n  ".join(bad)


def test_no_us_only_number_appears_outside_the_us():
    """The core safety invariant of issue #146, asserted against the data."""
    leaks = [
        f"{path}.{service} = {number}"
        for path, country, services in ALL_SERVICE_MAPS
        for service, number in services.items()
        if country not in ("US", "CA") and str(number).strip() in US_AND_CA_ONLY_NUMBERS
    ]
    assert not leaks, "US-only numbers outside the US record:\n  " + "\n  ".join(leaks)


# Uninhabited or non-permanent territories where emergency services do not exist.
UNINHABITED_TERRITORIES = {"AQ", "BV", "HM", "NF", "PN", "SJ", "TF", "UM"}


def test_every_country_can_answer_a_general_emergency():
    """Every country must have something for the fallback to reach for.

    If this fails, users in that country get "unavailable" for any service the
    directory does not list - which is safe, but is the gap this issue is about.
    """
    without = [
        code for code, country in DATA.items()
        if code not in UNINHABITED_TERRITORIES
        and not em.EmergencyServiceResolver._general_emergency_number(country)
    ]
    assert not without, f"no general emergency line resolvable for: {without}"


def test_service_names_are_from_the_known_vocabulary():
    """An unmodelled service name is silently invisible to the client.

    Adding one is fine - add it to KNOWN_SERVICES in the same change so it is
    returned and covered by the fallback.
    """
    unknown = sorted({
        service
        for _path, _country, services in ALL_SERVICE_MAPS
        for service in services
        if service not in em.KNOWN_SERVICES
    })
    assert not unknown, f"services absent from KNOWN_SERVICES: {unknown}"


@pytest.mark.parametrize(
    "country,service,expected",
    [
        # The routes issue #146 names explicitly for India.
        ("IN", "general_emergency", "112"),
        ("IN", "police", "112"),
        ("IN", "fire", "101"),
        ("IN", "ambulance", "108"),
        ("IN", "disaster_management", "108"),
        ("IN", "women_helpline", "1091"),
        # Australia's Triple Zero, previously stored as a single "0".
        ("AU", "police", "000"),
        ("AU", "general_emergency", "000"),
        # Pakistan's Rescue 1122, previously the un-dialable "115 and 1122".
        # The data team confirmed 1122 in the S3 ground truth (October 2026).
        ("PK", "ambulance", "1122"),
    ],
)
def test_specific_corrected_values(country, service, expected):
    assert DATA[country]["default"][service] == expected
