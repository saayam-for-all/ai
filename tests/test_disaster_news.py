"""Part 4: extraction, conservative matching and Lambda integration."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from services import disaster_check as dc, disaster_news as news, usgs_earthquakes as usgs

pytestmark = pytest.mark.unit
NOW = datetime(2023, 2, 6, 12, tzinfo=timezone.utc)
SNIPPET = "A magnitude 7.8 earthquake struck near Gaziantep, Turkey on 2023-02-06T01:17:34Z."
POINT = {"latitude": 37.0662, "longitude": 37.3833}
FIXTURE = Path(__file__).parent / "fixtures/usgs/kahramanmaras_2023-02-06.geojson"


@pytest.fixture
def edges():
    with mock.patch.object(news.disaster_geocoding, "geocode_place", return_value=POINT) as geo:
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(FIXTURE.read_bytes())) as http:
            yield geo, http


def check(snippet=SNIPPET, **extra):
    return news.check_news({"news_snippet": snippet, **extra}, now=NOW)


def test_precise_report_matches_one_record_from_recorded_usgs_response(edges):
    result = check(published_at="2023-02-06T04:00:00Z")
    assert result["status"] == "matched"
    assert result["disaster_detected"] is True
    assert result["confidence"] == "high"
    event, = result["events"]
    assert event["event_id"] == "usgs-us6000jllz"
    assert event["verified_by"][0]["source"] == "USGS"
    assert event["llm_cross_check"] is None
    assert event["boundary_source"] == "modelled"
    assert result["extracted"]["magnitude"] == 7.8
    assert result["extracted"]["reported_location"] == "Gaziantep, Turkey"
    assert json.loads(json.dumps(result)) == result
    edges[0].assert_called_once_with("Gaziantep, Turkey")


def test_query_uses_epicentral_distance_and_report_time_without_impact_expansion(edges):
    check()
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(edges[1].call_args.args[0].full_url).query)
    assert query["maxradiuskm"] == ["50.0"]
    assert query["starttime"] == ["2023-02-06T01:02:34"]


@pytest.mark.parametrize("suffix", ["", " today", " yesterday", " this morning", " on 2023-02-06"])
def test_missing_or_ambiguous_time_is_unresolved_without_network(edges, suffix):
    result = check("A magnitude 7.8 earthquake struck near Gaziantep, Turkey" + suffix + ".")
    assert result["reason"] == "missing_or_ambiguous_occurrence_time"
    assert result["disaster_detected"] is None
    assert result["confidence"] == "unverified"
    assert not edges[0].called and not edges[1].called


def test_publication_time_is_not_invented_as_the_event_time(edges):
    result = check("A magnitude 7.8 earthquake struck near Gaziantep, Turkey.",
                   published_at="2023-02-06T04:00:00Z")
    assert result["extracted"]["occurred_at"] is None
    assert result["extracted"]["published_at"] == "2023-02-06T04:00:00Z"
    assert result["status"] == "unresolved"


@pytest.mark.parametrize("snippet", [
    "An earthquake struck this morning.",
    "The local football team won.",
    "Flooding submerged Chennai.",
    "A wildfire is burning near Los Angeles.",
    "A tsunami struck Japan.",
    "A hurricane struck Florida.",
    "A tornado struck Oklahoma.",
    "A volcanic eruption occurred in Iceland.",
    "An earthquake and flood hit Japan.",
    "No " + SNIPPET,
    "Officials denied that " + SNIPPET,
    "If " + SNIPPET,
    SNIPPET + " This was a drill.",
    SNIPPET.replace("Gaziantep, Turkey", "Gaziantep and Tokyo"),
    SNIPPET.replace("Gaziantep, Turkey", "Gaziantep or Tokyo"),
    SNIPPET.replace("Gaziantep, Turkey", "Tokyo on Monday"),
])
def test_unsupported_or_unsafe_prose_never_confirms_a_nearby_event(edges, snippet):
    result = check(snippet)
    assert result["status"] == "unresolved"
    assert result["events"] == [] and result["disaster_detected"] is None
    assert not edges[0].called and not edges[1].called


def test_unknown_or_ambiguous_place_is_unresolved(edges):
    edges[0].return_value = None
    result = check()
    assert result["reason"] == "unknown_or_ambiguous_location"
    assert not edges[1].called


@pytest.mark.parametrize("snippet,reason", [
    (SNIPPET.replace("01:17:34Z", "13:00:00Z"), "inconsistent_occurrence_time"),
    (SNIPPET.replace("2023-02-06", "2023-01-01"), "outside_supported_time_window"),
    (SNIPPET.replace("2023-02-06", "2023-02-30"), "missing_or_ambiguous_occurrence_time"),
    (SNIPPET.replace("7.8", "4.9"), "outside_supported_magnitude_range"),
    (SNIPPET.replace("7.8", "11"), "outside_supported_magnitude_range"),
])
def test_unusable_report_details_do_not_call_providers(edges, snippet, reason):
    assert check(snippet)["reason"] == reason
    assert not edges[0].called and not edges[1].called


@pytest.mark.parametrize("value", [None, "", 0, False, [], {}, "x" * 2001])
def test_invalid_snippet_is_a_validation_error(edges, value):
    with pytest.raises(dc.InvalidQuery):
        check(value)
    assert not edges[0].called and not edges[1].called


@pytest.mark.parametrize("value", [None, False, 123, "", "2023-02-06", "2023-02-06T01:00:00", "2023-02-30T00:00:00Z", "2023-02-07T00:00:00Z"])
def test_invalid_publication_time_is_a_validation_error(edges, value):
    with pytest.raises(dc.InvalidQuery):
        check(published_at=value)
    assert not edges[0].called and not edges[1].called


def test_occurrence_after_publication_is_inconsistent(edges):
    assert check(published_at="2023-02-06T01:00:00Z")["reason"] == "inconsistent_occurrence_time"
    assert not edges[0].called


def test_timezone_offset_is_normalized(edges):
    result = check(SNIPPET.replace("01:17:34Z", "06:47:34+05:30"))
    assert result["status"] == "matched"
    assert result["extracted"]["occurred_at"] == "2023-02-06T01:17:34Z"


def test_no_match_is_not_an_all_clear(edges):
    edges[1].side_effect = lambda *a, **k: io.BytesIO(b'{"features": []}')
    result = check()
    assert result["reason"] == "no_authoritative_match"
    assert result["sources_checked"][0]["status"] == "ok"
    assert result["disaster_detected"] is None
    assert "not an all-clear" in result["advisory"]


@pytest.mark.parametrize("changes", [
    {"latitude": 39},
    {"started_at": NOW - timedelta(hours=1)},
    {"magnitude": 6.5},
    {"event_type": "flood"},
    {"expires_at": NOW},
    {"started_at": NOW + timedelta(seconds=1)},
])
def test_nearby_unrelated_or_expired_events_cannot_confirm_the_report(edges, changes):
    event = usgs._to_event(json.loads(FIXTURE.read_text())["features"][0])
    with mock.patch.object(usgs, "fetch_events", return_value=[{**event, **changes}]):
        assert check()["reason"] == "no_authoritative_match"


def test_multiple_matching_records_are_unresolved(edges):
    event = usgs._to_event(json.loads(FIXTURE.read_text())["features"][0])
    with mock.patch.object(usgs, "fetch_events", return_value=[event, {**event, "event_id": "other"}]):
        assert check()["reason"] == "multiple_authoritative_matches"
