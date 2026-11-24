"""No answer prompt may name an emergency number - issue #258, Task A.

The answer prompts used to give the model "911 for US, 112 for EU" and
"988 for US, Crisis Text Line 741741" as examples. A model given examples
repeats them, so a user in Pakistan, Australia or Brazil asking for urgent
help could be told to call 911 - the failure #146 fixed for Emergency
Contacts, coming back through Generate Answer.

The prompts now tell the model never to state an emergency number and to
point the user to local emergency services and the Emergency Contacts page,
which resolves the right numbers per country from
services/emergency_numbers.json. These tests keep it that way:

  * no rendered prompt, for any category, on either the one-shot or the
    conversational path, contains a number from the emergency dataset or a
    well-known hotline;
  * no rendered prompt contains any digit run of three or more digits, so a
    number we have never heard of cannot slip in either;
  * every prompt that talks about urgent or crisis help still sends the user
    to the Emergency Contacts page and forbids stating a number, so the fix
    cannot be undone by quietly deleting the referral.

No network, no keys and no model calls.
"""
import json
import re

import pytest

# Pure string checks over the prompt builder.
pytestmark = pytest.mark.unit

import services.emergency as em
from utils import prompts as P

# Hotlines that are not in the dataset as emergency numbers but have appeared
# in these prompts before, or are the obvious next thing someone would add.
EXTRA_NUMBERS = {"911", "112", "999", "000", "988", "741741", "116123"}


def _dataset_numbers():
    with open(em.DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    numbers = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and re.fullmatch(r"[\d\s-]+", node.strip()):
            numbers.add(re.sub(r"[\s-]", "", node))

    walk(data)
    return numbers


FORBIDDEN = _dataset_numbers() | EXTRA_NUMBERS

# Digits a prompt legitimately carries: list markers ("1. ", "(2)"), word
# limits ("60 words"), ranges ("2-3 short sentences") and "100%". Everything
# else that looks like a number is treated as a phone number.
_LIST_MARKER = re.compile(r"(?m)^\s*\d+\.\s|\(\d+\)")
_ALLOWED_DIGITS = re.compile(r"\d+\s*%|\d+\s+words\b|\b\d+-\d+\s+short\b")
_NUMBER = re.compile(r"(?<![\w])\d(?:[\d\s-]*\d)?(?![\w])")

# The categories whose prompts discuss urgent, medical, safety or crisis help.
# Each used to name 911/112 or 988 and must now carry the referral instead.
URGENT_CATEGORIES = [
    "EMERGENCY_ASSISTANCE",
    "EMERGENCY_CLOTHING_ASSISTANCE",
    "HOME_REPAIR_SUPPORT",
    "HEALTHCARE_WELLNESS_SUPPORT",
    "MEDICAL_NAVIGATION",
    "MENTAL_WELLBEING_SUPPORT",
    "HEALTH_EDUCATION_GUIDANCE",
    "ELDERLY_SUPPORT",
    "MEDICAL_HELP",
]

# Locations from the five-location check in #258, plus none at all. The
# location must never change whether a number appears.
LOCATIONS = ["", "United States", "India", "Karachi, Pakistan", "Australia", "Brazil"]


def _phone_like(text):
    """Return every number in text that is not a list marker, limit or range."""
    text = _LIST_MARKER.sub(" ", text)
    text = _ALLOWED_DIGITS.sub(" ", text)
    return [re.sub(r"[\s-]", "", m.group()) for m in _NUMBER.finditer(text)]


def _rendered_prompts():
    for category in P.category_prompts:
        for location in LOCATIONS:
            yield (
                f"get_prompt/{category}/{location or 'none'}",
                P.get_prompt(category, "Need help", "Please help me", location),
            )
            yield (
                f"get_conversational_prompt/{category}/{location or 'none'}",
                P.get_conversational_prompt(category, "Need help", location),
            )


RENDERED = list(_rendered_prompts())


def test_detector_catches_the_numbers_the_prompts_used_to_carry():
    """Prove the check bites: the old wording must be flagged."""
    old = (
        "include 911 for US, 112 for EU, or location-specific. "
        "National Suicide Prevention Lifeline 988 for US, Crisis Text Line 741741"
    )
    found = set(_phone_like(old))
    assert {"911", "112", "988", "741741"} <= found
    assert {"911", "112", "988", "741741"} <= FORBIDDEN


def test_detector_ignores_list_markers_limits_and_percentages():
    text = "1. Answer in 2-3 short sentences.\n2. Keep it under 60 words.\n(3) Be 100% accurate."
    assert _phone_like(text) == []


def test_dataset_numbers_are_loaded():
    # Guards the guard: if the dataset walk ever returns nothing, the main
    # test below would pass for the wrong reason.
    assert len(FORBIDDEN) > 50
    assert {"911", "112", "999", "000", "100"} <= FORBIDDEN


def test_no_prompt_names_an_emergency_number():
    # One test over every category, location and path, reporting every
    # offender at once rather than 444 near-identical cases.
    offenders = {}
    for name, prompt in RENDERED:
        hits = sorted(set(_phone_like(prompt)) & FORBIDDEN)
        if hits:
            offenders[name] = hits
    assert offenders == {}, f"prompts name emergency numbers: {offenders}"


def test_no_prompt_contains_any_phone_like_number():
    offenders = {}
    for name, prompt in RENDERED:
        long_runs = sorted({n for n in _phone_like(prompt) if len(n) >= 3})
        if long_runs:
            offenders[name] = long_runs
    assert offenders == {}, f"prompts contain phone-like numbers: {offenders}"


def test_every_category_is_rendered_on_both_paths():
    # Guards the two loops above against an empty or partial RENDERED list.
    assert len(RENDERED) == len(P.category_prompts) * len(LOCATIONS) * 2


def test_no_category_template_names_an_emergency_number():
    # The raw templates too, so a number added behind a placeholder that the
    # renderer happens not to reach is still caught.
    for category, template in P.category_prompts.items():
        hits = sorted(set(_phone_like(template)) & FORBIDDEN)
        assert hits == [], f"{category} template names {hits}"


@pytest.mark.parametrize("category", URGENT_CATEGORIES)
def test_urgent_prompts_point_to_emergency_contacts(category):
    template = P.category_prompts[category]
    assert "Emergency Contacts page" in template, category
    assert re.search(r"[Nn]ever state an? .*number yourself", template), category


def test_urgent_categories_exist():
    # A renamed category would make the referral test above vacuous.
    assert set(URGENT_CATEGORIES) <= set(P.category_prompts)
