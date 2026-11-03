"""
Tests for grounded organization retrieval - issue #197, stack 3.

``utils/grounded_orgs.py`` answers "which organizations help with this?" from a
dataset of records a person has verified, with a source behind every claim,
instead of asking a model to recall them (``utils/search_orgs.py``). These tests
pin the behaviour that makes that trustworthy:

* unverified or unsourced data is never served,
* the taxonomy graph finds organizations a flat lookup would miss,
* a request with no match returns nothing rather than something invented,
* rows keep the exact contract the data team's aggregator and the tab read
  (see ``tests/test_org_search_contract.py`` and issue #170),
* ``audit`` can tell supported organizations from unsupported ones.

Most records here are TEST-ONLY fixtures (fake names, ``example.invalid`` URLs).
The last section runs against the shipped PROXY dataset in
``services/organizations.json``. No network, model or AWS is used.
"""
import copy
import json
from pathlib import Path
from unittest import mock

import pytest

from utils import grounded_orgs as GO
from utils import search_orgs as SO

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "grounded_orgs_test_records.json"

# A small taxonomy shaped like utils/predict_category_list.py, including the
# special "0.0.0.0.0" general key that must not be treated as a child of anything.
TAXONOMY = {
    "0.0.0.0.0": "GENERAL_CATEGORY",
    "1": "FOOD_AND_ESSENTIALS", "1.1": "FOOD_ASSISTANCE",
    "1.2": "GROCERY_SHOPPING_AND_DELIVERY",
    "3": "HOUSING_ASSISTANCE", "3.3": "REPAIR_MAINTENANCE_SUPPORT", "3.3.1": "PLUMBING",
    "4": "EDUCATION_CAREER_SUPPORT", "4.3": "TUTORING", "4.3.1": "MATH",
}

# What the aggregator selects (after renaming) and what the tab renders.
AGGREGATOR_COLUMNS = ("organization_name", "location", "contact", "email",
                      "web_url", "mission", "source")
TAB_COLUMNS = ("organization_name", "location", "causes", "size", "rating")


@pytest.fixture
def taxonomy():
    return GO.Taxonomy(TAXONOMY)


@pytest.fixture
def records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["organizations"]


def _find(taxonomy, records, **kwargs):
    args = {"subject": "", "description": "", "location": "San Jose, CA"}
    args.update(kwargs)
    return GO.find_organizations_grounded(records=records, taxonomy=taxonomy, **args)


def _ids(result):
    return [r["source_id"] for r in result["grounding"]["results"]]


# -------------------------------------------------------------------
# The dataset rules: what is allowed to be served at all
# -------------------------------------------------------------------

def test_fixture_records_are_all_servable(records):
    """The fixture itself must satisfy the rules, or the other tests prove nothing."""
    assert all(GO.problems(r) == [] for r in records)


def test_a_record_nobody_verified_is_never_served(taxonomy, records):
    """No named verifier means no result, however well the record matches."""
    unverified = copy.deepcopy(records[0])
    unverified["verified_by"] = ""
    assert "missing verified_by" in GO.problems(unverified)
    result = _find(taxonomy, [unverified], category="FOOD_ASSISTANCE")
    assert result["organizations"] == []


def test_a_claim_without_a_source_drops_the_whole_record(taxonomy, records):
    """A phone number nobody can trace is a claim; the record is not served."""
    unsourced = copy.deepcopy(records[0])
    del unsourced["sources"]["contact"]
    assert "contact has no https source" in GO.problems(unsourced)
    assert _find(taxonomy, [unsourced], category="FOOD_ASSISTANCE")["organizations"] == []


def test_a_source_must_be_https(records):
    insecure = copy.deepcopy(records[0])
    insecure["sources"]["web_url"] = "http://example.invalid/x"
    assert "web_url has no https source" in GO.problems(insecure)


def test_blank_rating_and_size_make_no_claim_and_need_no_source(records):
    """Unknown is allowed. Inventing a rating or size to fill the column is not."""
    bare = copy.deepcopy(records[0])
    bare["rating"], bare["size"] = 0.0, ""
    del bare["sources"]["rating"], bare["sources"]["size"]
    assert GO.problems(bare) == []


def test_load_records_keeps_only_servable_records(tmp_path, records):
    bad = copy.deepcopy(records[1])
    bad["verified_on"] = "last tuesday"
    path = tmp_path / "orgs.json"
    path.write_text(json.dumps({"organizations": [records[0], bad]}), encoding="utf-8")
    assert [r["source_id"] for r in GO.load_records(path)] == ["fx-001"]


def test_a_missing_default_dataset_returns_nothing_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(GO, "DATA_PATH", tmp_path / "absent.json")
    assert GO.load_records() == []


@pytest.mark.dataset
def test_the_shipped_dataset_follows_its_own_rules():
    """Every record committed to services/organizations.json must pass, so a bad
    commit fails the build instead of reaching a user."""
    if not GO.DATA_PATH.exists():
        pytest.skip("no shipped dataset yet")
    text = GO.DATA_PATH.read_text(encoding="utf-8")
    assert "example.invalid" not in text, "test fixture data leaked into the dataset"
    raw = json.loads(text)
    for record in raw.get("organizations", []):
        assert GO.problems(record) == [], record.get("source_id")


# -------------------------------------------------------------------
# The taxonomy as a graph
# -------------------------------------------------------------------

def test_edges_come_from_the_dotted_ids(taxonomy):
    assert taxonomy.parent("3.3.1") == "3.3"
    assert taxonomy.children("3") == ["3.3"]
    assert taxonomy.parent("3") is None


def test_the_general_category_key_is_a_root_not_a_child(taxonomy):
    """"0.0.0.0.0" contains dots but its would-be parent does not exist."""
    assert taxonomy.parent("0.0.0.0.0") is None
    assert taxonomy.ancestors("0.0.0.0.0") == []


def test_ancestors_run_nearest_first_and_descendants_cover_the_subtree(taxonomy):
    assert taxonomy.ancestors("3.3.1") == ["3.3", "3"]
    assert set(taxonomy.descendants("3")) == {"3.3", "3.3.1"}


def test_resolve_accepts_an_id_or_a_category_name(taxonomy):
    assert taxonomy.resolve("4.3.1") == "4.3.1"
    assert taxonomy.resolve("math") == "4.3.1"
    assert taxonomy.resolve("Food Assistance") == "1.1"
    assert taxonomy.resolve("not a category") is None


def test_infer_picks_the_most_specific_category_from_free_text(taxonomy):
    assert taxonomy.infer("my sink has a plumbing problem") == ["3.3.1"]
    # Both the parent and the child match; only the specific one is kept.
    assert taxonomy.infer("plumbing repair maintenance") == ["3.3.1"]


def test_infer_is_conservative(taxonomy):
    """A wrong category is worse than none."""
    assert taxonomy.infer("I would like some advice") == []


def test_the_default_taxonomy_is_the_classifiers_dictionary():
    from utils.predict_category_list import help_categories
    assert GO.Taxonomy().names == dict(help_categories)


# -------------------------------------------------------------------
# Retrieval
# -------------------------------------------------------------------

def test_exact_beats_broader_and_the_graph_finds_what_a_flat_lookup_misses(taxonomy, records):
    """Plumbing: the plumbing org is exact, the housing org (3) is broader.
    A flat exact-match lookup would return only the first."""
    result = _find(taxonomy, records, category="PLUMBING")
    assert _ids(result) == ["fx-004", "fx-002"]
    by_id = {r["source_id"]: r for r in result["grounding"]["results"]}
    assert by_id["fx-004"]["matched_via"] == "exact"
    assert by_id["fx-002"]["matched_via"] == "broader"
    assert by_id["fx-004"]["score"] > by_id["fx-002"]["score"]


def test_a_narrower_organization_is_found_for_a_broad_request(taxonomy, records):
    result = _find(taxonomy, records, category="4", location="United States")
    assert _ids(result) == ["fx-003"]
    assert result["grounding"]["results"][0]["matched_via"] == "narrower"


def test_a_category_can_be_inferred_from_the_request_text(taxonomy, records):
    result = _find(taxonomy, records, description="a plumbing leak under my sink")
    assert result["grounding"]["query_categories"] == ["3.3.1"]
    assert _ids(result)[0] == "fx-004"


def test_keywords_catch_requests_no_category_name_matches(taxonomy, records):
    result = _find(taxonomy, records, description="I cannot afford groceries",
                   location="Austin, TX")
    assert _ids(result) == ["fx-005"]
    assert result["grounding"]["results"][0]["matched_via"] == "keyword"


def test_nothing_matching_returns_nothing_not_something_plausible(taxonomy, records):
    result = _find(taxonomy, records, description="legal advice about a visa")
    assert result["organizations"] == []
    assert result["grounding"]["results"] == []


def test_location_filters_by_city_state_and_national(taxonomy, records):
    assert _ids(_find(taxonomy, records, category="FOOD_ASSISTANCE",
                      location="San Jose, CA")) == ["fx-001"]
    assert _find(taxonomy, records, category="FOOD_ASSISTANCE",
                 location="Austin, TX")["organizations"] == []
    # A state-level area serves a city inside it; a national one serves anywhere.
    assert "fx-002" in _ids(_find(taxonomy, records, category="HOUSING_ASSISTANCE",
                                  location="Oakland, CA"))
    assert _ids(_find(taxonomy, records, category="TUTORING",
                      location="Boise, ID")) == ["fx-003"]


def test_ca_does_not_match_chicago(taxonomy, records):
    """Whole-word matching: a state code must not match inside another word."""
    assert _find(taxonomy, records, category="HOUSING_ASSISTANCE",
                 location="Chicago, IL")["organizations"] == []


def test_an_unspecified_location_does_not_filter(taxonomy, records):
    """The handler sends "United States" when the caller gave none."""
    assert set(_ids(_find(taxonomy, records, category="1", location="United States"))) \
        == {"fx-001", "fx-005"}


def test_the_limit_is_respected(taxonomy, records):
    assert len(_find(taxonomy, records, category="1", location="", limit=1)["organizations"]) == 1


def test_the_same_request_always_gives_the_same_answer(taxonomy, records):
    first = _find(taxonomy, records, category="PLUMBING")
    assert first == _find(taxonomy, records, category="PLUMBING")


# -------------------------------------------------------------------
# The contract the aggregator and the tab depend on
# -------------------------------------------------------------------

@pytest.mark.contract
def test_every_row_carries_every_contract_field(taxonomy, records):
    result = _find(taxonomy, records, category="PLUMBING")
    assert result["organizations"]
    for row in result["organizations"]:
        assert set(SO.ORGANIZATION_FIELDS) <= set(row)


@pytest.mark.contract
def test_aggregator_and_tab_columns_are_present_and_filled(taxonomy, records):
    for row in _find(taxonomy, records, category="FOOD_ASSISTANCE")["organizations"]:
        for column in AGGREGATOR_COLUMNS + TAB_COLUMNS:
            assert column in row
        assert row["rating"] == 4.0 and row["size"] == "small" and row["causes"]


@pytest.mark.contract
def test_the_envelope_the_aggregator_reads_keeps_body_an_object(taxonomy, records):
    """payload['body']['organizations'] must work: body is a dict, not a string."""
    body = _find(taxonomy, records, category="FOOD_ASSISTANCE")
    payload = {"statusCode": 200, "body": body}
    assert isinstance(payload["body"], dict)
    assert isinstance(payload["body"]["organizations"], list)


@pytest.mark.contract
def test_source_is_the_organizations_own_source_url(taxonomy, records):
    row = _find(taxonomy, records, category="FOOD_ASSISTANCE")["organizations"][0]
    assert row["source"] == "https://example.invalid/fx-001"


def test_a_blank_location_or_cause_is_never_filled_in_from_the_request(taxonomy, records):
    """The model-output normalizer fills a blank location and causes from the
    request. Here that would present a claim no source supports."""
    blank = copy.deepcopy(records[0])
    blank["location"], blank["causes"] = "", []
    del blank["sources"]["location"]
    row = _find(taxonomy, [blank], category="FOOD_ASSISTANCE",
                location="San Jose, CA")["organizations"][0]
    assert row["location"] == "" and row["causes"] == ""


def test_the_relevance_line_is_deterministic_text_not_model_output(taxonomy, records):
    result = _find(taxonomy, records, category="PLUMBING")
    assert result["organizations"][0]["relevance"] == \
        "Listed as serving PLUMBING, the category of this request."
    assert "broader area that includes PLUMBING" in result["organizations"][1]["relevance"]


def test_the_grounding_block_names_the_source_of_every_field(taxonomy, records):
    hit = _find(taxonomy, records, category="FOOD_ASSISTANCE")["grounding"]["results"][0]
    assert hit["source_id"] == "fx-001"
    assert hit["field_sources"]["contact"].startswith("https://")


# -------------------------------------------------------------------
# Auditing organizations from another source
# -------------------------------------------------------------------

# The shape the model path produces (see tests/test_org_search_contract.py).
MODEL_STYLE_ORG = {
    "organization_name": "Second Harvest Food Bank", "org_type": "nonprofit",
    "size": "large", "rating": 4.8, "location": "San Jose, CA",
    "contact": "+1-408-555-0100", "web_url": "https://example.org",
}


def test_a_model_written_organization_with_no_record_is_unsupported(records):
    report = GO.audit([MODEL_STYLE_ORG], records=records)
    assert report["organizations"][0]["status"] == "unsupported"
    assert report["summary"] == {"total": 1, "supported": 0, "contradicted": 0, "unsupported": 1}


def test_an_organization_matching_its_record_is_supported(records):
    assert GO.audit([records[0]], records=records)["summary"]["supported"] == 1


def test_a_differing_field_is_reported_as_contradicted(records):
    wrong = dict(records[0], rating=4.9, contact="+1-999-999-9999")
    entry = GO.audit([wrong], records=records)["organizations"][0]
    assert entry["status"] == "contradicted"
    assert set(entry["mismatched_fields"]) == {"rating", "contact"}


def test_formatting_differences_are_not_contradictions(records):
    same = dict(records[0], web_url="HTTP://WWW.example.invalid/fx-001/",
                contact="+1 (000) 000-0000")
    assert GO.audit([same], records=records)["organizations"][0]["status"] == "supported"


# -------------------------------------------------------------------
# End to end through the Lambda handler
# -------------------------------------------------------------------

@pytest.mark.integration
def test_the_handler_can_serve_grounded_results(taxonomy, records):
    """Swap the model search for the grounded one behind the real handler and
    check the envelope the aggregator reads."""
    import lambda_function as LF

    def grounded(subject, description, location, category=None):
        return GO.find_organizations_grounded(
            subject, description, location, category, records=records, taxonomy=taxonomy)

    event = {"subject": "plumbing", "description": "a plumbing leak",
             "location": "San Jose, CA", "category": "PLUMBING"}
    with mock.patch.object(LF, "find_organizations", side_effect=grounded):
        response = LF.search_orgs_handler(event, None)
    assert response["statusCode"] == 200
    organizations = response["body"]["organizations"]
    assert [o["organization_name"] for o in organizations][0].startswith("Fixture Plumbing Aid")


# -------------------------------------------------------------------
# The proxy dataset in services/organizations.json
# -------------------------------------------------------------------
# Sameer (21 Oct 2026) said proxy data is fine for this experiment. These tests
# run against the shipped made-up records and skip themselves once the file holds
# only real, person-verified records.

PROXY_TAXONOMY = {
    "1": "FOOD_AND_ESSENTIALS", "1.1": "FOOD_ASSISTANCE",
    "2": "CLOTHING_ASSISTANCE", "2.1": "DONATE_CLOTHES",
    "3": "HOUSING_ASSISTANCE", "3.5": "LOOKING_FOR_RENTAL",
    "4": "EDUCATION_CAREER_SUPPORT", "4.3": "TUTORING",
}


@pytest.fixture
def proxy_records():
    """The shipped proxy records, or skip when the dataset holds none."""
    found = [r for r in GO.load_records() if r.get("verified_by") == "proxy-data"]
    if not found:
        pytest.skip("no proxy records in the shipped dataset")
    return found


def _names(category, location, records):
    """Organization names the grounded search returns for a category and place."""
    result = GO.find_organizations_grounded(
        "", "", location, category, records=records, taxonomy=GO.Taxonomy(PROXY_TAXONOMY))
    return [o["organization_name"] for o in result["organizations"]]


@pytest.mark.dataset
def test_proxy_records_are_labelled_so_nobody_mistakes_them_for_real(proxy_records):
    """Made-up records must say so in their name and may only cite reserved
    example domains, so they can never pass for a verified organization."""
    for record in proxy_records:
        assert "(proxy data)" in record["organization_name"], record["source_id"]
        assert record["web_url"].startswith("https://example.org/"), record["source_id"]


@pytest.mark.dataset
def test_a_shelter_request_gets_only_its_own_citys_record(proxy_records):
    """Housing in Chicago returns the Chicago shelter, not Houston's or Seattle's."""
    names = _names("HOUSING_ASSISTANCE", "Chicago, IL", proxy_records)
    assert names[0] == "Sample Chicago Shelter Network (proxy data)"
    assert not any("Houston" in n or "Seattle" in n for n in names)


@pytest.mark.dataset
def test_a_narrower_housing_request_reaches_the_broader_record(proxy_records):
    """Looking for a rental (3.5) finds the shelter filed under Housing (3):
    the category graph at work, which a flat lookup would miss."""
    names = _names("LOOKING_FOR_RENTAL", "Houston, TX", proxy_records)
    assert "Sample Houston Shelter Network (proxy data)" in names


@pytest.mark.dataset
def test_a_category_nobody_covers_returns_nothing(proxy_records):
    """Tutoring has no proxy record, so the answer is empty, not invented."""
    assert _names("TUTORING", "Chicago, IL", proxy_records) == []


@pytest.mark.dataset
def test_an_uncovered_city_gets_only_the_national_record(proxy_records):
    """Denver has no local record; only the nationwide helpline may answer."""
    assert _names("HOUSING_ASSISTANCE", "Denver, CO", proxy_records) == [
        "Sample National Housing Helpline (proxy data)"]


@pytest.mark.dataset
def test_one_citys_record_never_leaks_into_another_city(proxy_records):
    """Housing in Houston returns Houston's shelter and never Chicago's: a record
    must not widen its own service area."""
    names = _names("HOUSING_ASSISTANCE", "Houston, TX", proxy_records)
    assert names[0] == "Sample Houston Shelter Network (proxy data)"
    assert not any("Chicago" in n or "Seattle" in n for n in names)


@pytest.mark.dataset
def test_the_demo_prints_matches_with_sources_and_says_when_nothing_matches(
        proxy_records, capsys):
    """The demo shows the main behaviours in plain text: a local match, a match
    through the category graph, a national fallback, and two empty answers."""
    GO.demo(records=proxy_records, taxonomy=GO.Taxonomy(PROXY_TAXONOMY))
    out = capsys.readouterr().out
    assert "Sample Chicago Shelter Network (proxy data)" in out
    assert "matched via: broader" in out
    assert "name sourced from: https://example.org/proxy/" in out
    assert out.count("nothing returned") == 2


def test_the_demo_flag_runs_the_demo_and_other_arguments_search(monkeypatch, capsys):
    """``--demo`` runs the demo; any other arguments run one search and print JSON."""
    calls = []
    monkeypatch.setattr(GO, "demo", lambda: calls.append("demo"))
    GO.main(["--demo"])
    assert calls == ["demo"]
    monkeypatch.setattr(GO, "find_organizations_grounded",
                        lambda *a, **k: {"organizations": [], "grounding": {}})
    GO.main(["shelter", "a place to stay", "Chicago, IL"])
    assert json.loads(capsys.readouterr().out)["organizations"] == []

