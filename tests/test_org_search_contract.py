"""
Tests for More Organizations / the Organizations tab - issue #170.

This endpoint has a second consumer that is easy to forget, because it lives in
another repository: the data team's `saayam-org-aggregator`, which serves
`v1/ml/orgAggregatorList` for the Request Details Organizations tab. It calls
us with boto3 and then does, verbatim:

    payload = json.loads(response['Payload'].read())
    if payload.get('statusCode') != 200: raise ...
    orgs = pd.DataFrame(payload['body']['organizations'])
    ... .rename(columns={'organization_name': 'name'})[
            ['name','location','contact','email','web_url','mission','source', ...]]

So `body` must stay an object, `body["organizations"]` must be a list, and
every field it selects must be present on every row. PR #165 serialised `body`
and would have broken the Organizations tab from a different repo; nothing in
our suite would have caught it. These tests are that guard.

No network or keys required.
"""
import json
from unittest import mock

import lambda_function as LF
from utils import search_orgs as SO


# Columns the ml-api aggregator selects out of our rows after renaming
# organization_name -> name. A missing one is a KeyError in their merge.
AGGREGATOR_COLUMNS = (
    "organization_name", "location", "contact", "email", "web_url",
    "mission", "source",
)

# Columns the Organizations tab renders. `rating` and `size` are currently
# dropped by the aggregator's merge - see F2 on issue #170 - but we must keep
# producing them or the tab can never be completed.
TAB_COLUMNS = ("organization_name", "location", "causes", "size", "rating")


def _model_org(**overrides):
    org = {
        "organization_name": "Second Harvest Food Bank",
        "org_type": "nonprofit",
        "size": "large",
        "rating": 4.8,
        "location": "San Jose, CA",
        "contact": "+1-408-555-0100",
        "email": "info@example.org",
        "source": "https://www.charitynavigator.org/example",
        "web_url": "https://example.org",
        "mission": "Feed people.",
        "description": "Distributes food.",
        "relevance": "Serves the requested area.",
        "causes": "Food Security",
    }
    org.update(overrides)
    return org


def _found(organizations):
    return mock.patch.object(
        LF, "find_organizations",
        return_value=SO.normalize_result({"organizations": organizations}),
    )


def _event(payload, envelope="direct"):
    if envelope == "direct":
        return dict(payload)          # boto3 lambda.invoke, and the aggregator
    return {"body": json.dumps(payload)}   # API Gateway


PAYLOAD = {
    "subject": "food",
    "description": "I cannot afford groceries this month",
    "location": "San Jose, CA",
}


# -------------------------------------------------------------------
# The shape the aggregator reads
# -------------------------------------------------------------------

def test_body_stays_an_object_with_an_organizations_list():
    with _found([_model_org()]):
        res = LF.search_orgs_handler(_event(PAYLOAD), None)

    assert res["statusCode"] == 200
    assert isinstance(res["body"], dict), (
        "body must not be serialised: the aggregator does body['organizations']"
    )
    assert isinstance(res["body"]["organizations"], list)


def test_every_column_the_aggregator_selects_is_present_on_every_row():
    with _found([_model_org(), _model_org(organization_name="Loaves & Fishes")]):
        res = LF.search_orgs_handler(_event(PAYLOAD), None)

    for row in res["body"]["organizations"]:
        for column in AGGREGATOR_COLUMNS:
            assert column in row, f"{column} missing: KeyError in the ml-api merge"


def test_every_column_the_organizations_tab_renders_is_present():
    with _found([_model_org()]):
        res = LF.search_orgs_handler(_event(PAYLOAD), None)

    row = res["body"]["organizations"][0]
    for column in TAB_COLUMNS:
        assert column in row, f"{column} missing: the tab cannot fill its column"


def test_a_row_missing_fields_from_the_model_is_still_complete():
    """The model does not always return every key. The aggregator builds a
    DataFrame from these rows, so a ragged row becomes NaN columns in a
    different repository."""
    with _found([{"organization_name": "Sparse Org"}]):
        res = LF.search_orgs_handler(_event(PAYLOAD), None)

    row = res["body"]["organizations"][0]
    for field in SO.ORGANIZATION_FIELDS:
        assert field in row, f"{field} must always be present"


def test_direct_invoke_and_api_gateway_envelopes_agree():
    for envelope in ("direct", "gateway"):
        with _found([_model_org()]):
            res = LF.search_orgs_handler(_event(PAYLOAD, envelope), None)
        assert res["statusCode"] == 200, envelope
        assert res["body"]["organizations"][0]["organization_name"]


# -------------------------------------------------------------------
# Rating and size normalisation - the tab sorts by rating
# -------------------------------------------------------------------

def test_charity_navigator_style_score_is_converted_to_the_five_point_scale():
    assert SO._normalize_rating(95) == 4.8
    assert SO._normalize_rating(100) == 5.0


def test_rating_is_always_a_float_in_range():
    for bad in (None, "", "not a number", -3, 4000, [], {}):
        rating = SO._normalize_rating(bad)
        assert isinstance(rating, float)
        assert 0.0 <= rating <= 5.0, f"{bad!r} produced {rating}"


def test_rating_keeps_one_decimal_place():
    assert SO._normalize_rating("4.26") == 4.3
    assert SO._normalize_rating(4.8) == 4.8


def test_size_is_one_of_the_three_values_or_empty():
    assert SO._normalize_size("Large") == "large"
    assert SO._normalize_size("medium-sized nonprofit") == "medium"
    assert SO._normalize_size("enormous") == ""
    assert SO._normalize_size(None) == ""


def test_org_type_is_normalised_to_nonprofit_or_for_profit():
    for text in ("nonprofit", "Non-Profit", "non profit", "NONPROFIT"):
        assert SO._normalize_org_type(text) == "nonprofit"
    for text in ("for-profit", "For Profit", "for_profit"):
        assert SO._normalize_org_type(text) == "for-profit"
    assert SO._normalize_org_type("cooperative") == ""


def test_a_bad_rating_from_the_model_does_not_reach_the_sortable_column():
    with _found([_model_org(rating="95/100"), _model_org(rating=88)]):
        res = LF.search_orgs_handler(_event(PAYLOAD), None)

    for row in res["body"]["organizations"]:
        assert isinstance(row["rating"], float)
        assert 0.0 <= row["rating"] <= 5.0


def test_missing_location_falls_back_to_the_requested_location():
    org = SO.normalize_organization({"organization_name": "X"}, location="San Jose, CA")
    assert org["location"] == "San Jose, CA"


def test_causes_is_seeded_from_the_category_when_the_model_omits_it():
    org = SO.normalize_organization({"organization_name": "X"}, category="Food Security")
    assert org["causes"] == "Food Security"


# -------------------------------------------------------------------
# Provider fallback
# -------------------------------------------------------------------

ROWS = {"organizations": [_model_org()]}


def _two_providers(groq="ok", gemini="ok"):
    """Patch the provider list and the per-provider invoke.

    Each provider is a named sentinel, and _invoke_provider dispatches on it,
    so the fallback loop itself is what gets exercised rather than a mock that
    swallows the whole chain.
    """
    llms = {"groq": object(), "gemini": object()}
    outcomes = {llms["groq"]: groq, llms["gemini"]: gemini}

    def invoke(llm, *_args):
        outcome = outcomes[llm]
        if isinstance(outcome, Exception):
            raise outcome
        return ROWS if outcome == "ok" else {"organizations": []}

    providers = [
        (name, (lambda llm=llms[name]: llm) if outcome != "absent" else (lambda: None))
        for name, outcome in (("groq", groq), ("gemini", gemini))
    ]
    return (
        mock.patch.object(SO, "_providers", return_value=providers),
        mock.patch.object(SO, "_invoke_provider", side_effect=invoke),
        mock.patch.object(SO, "build_prompt", return_value=object()),
    )


def test_the_real_provider_list_is_groq_then_gemini():
    """The loop above is patched, so pin the production list separately."""
    assert [name for name, _ in SO._providers()] == ["groq", "gemini"]


def test_gemini_serves_the_request_when_groq_fails():
    """A Groq outage used to take the whole Organizations tab down."""
    providers, invoke, prompt = _two_providers(
        groq=RuntimeError("model_decommissioned"), gemini="ok"
    )
    with providers, invoke as invoked, prompt:
        result = SO.find_organizations("food", "no groceries", "San Jose, CA")

    assert invoked.call_count == 2, "Groq must be tried before Gemini"
    assert result["organizations"][0]["organization_name"] == "Second Harvest Food Bank"


def test_groq_is_used_alone_when_it_succeeds():
    providers, invoke, prompt = _two_providers(groq="ok", gemini="ok")
    with providers, invoke as invoked, prompt:
        result = SO.find_organizations("food", "no groceries", "San Jose, CA")

    assert invoked.call_count == 1, "Gemini must not be called when Groq works"
    assert len(result["organizations"]) == 1


def test_a_provider_returning_no_organizations_falls_through_to_the_next():
    providers, invoke, prompt = _two_providers(groq="empty", gemini="ok")
    with providers, invoke, prompt:
        result = SO.find_organizations("food", "no groceries", "San Jose, CA")

    assert len(result["organizations"]) == 1


def test_an_unconfigured_provider_is_skipped_not_fatal():
    providers, invoke, prompt = _two_providers(groq="absent", gemini="ok")
    with providers, invoke as invoked, prompt:
        result = SO.find_organizations("food", "no groceries", "San Jose, CA")

    assert invoked.call_count == 1
    assert len(result["organizations"]) == 1


def test_every_provider_failing_raises_rather_than_returning_an_empty_success():
    with mock.patch.object(SO, "_providers",
                           return_value=[("groq", lambda: None),
                                         ("gemini", lambda: None)]):
        try:
            SO.find_organizations("food", "no groceries", "San Jose, CA")
        except SO.OrganizationSearchError:
            pass
        else:
            raise AssertionError("a total provider failure must not look like success")


def test_total_provider_failure_is_a_502_with_a_code_and_a_list(capsys):
    with mock.patch.object(
        LF, "find_organizations",
        side_effect=SO.OrganizationSearchError("groq: down; gemini: not configured"),
    ):
        res = LF.search_orgs_handler(_event(PAYLOAD), None)

    assert res["statusCode"] == 502
    assert res["body"]["code"] == "ORG_SEARCH_UNAVAILABLE"
    # organizations is always a list, so a caller that reads it before checking
    # the status gets [] rather than a KeyError.
    assert res["body"]["organizations"] == []
    assert "groq: down" in capsys.readouterr().out


# -------------------------------------------------------------------
# Request validation
# -------------------------------------------------------------------

def test_description_is_required():
    res = LF.search_orgs_handler(_event({"subject": "food", "location": "X"}), None)
    assert res["statusCode"] == 400


def test_missing_location_defaults_and_missing_subject_is_tolerated():
    with _found([_model_org()]) as found:
        res = LF.search_orgs_handler(_event({"description": "help"}), None)

    assert res["statusCode"] == 200
    assert found.call_args.kwargs["location"] == "United States"
    assert found.call_args.kwargs["subject"] == ""


def test_category_is_passed_through_to_the_search():
    with _found([_model_org()]) as found:
        LF.search_orgs_handler(_event(dict(PAYLOAD, category="Food Security")), None)

    assert found.call_args.kwargs["category"] == "Food Security"


def test_unified_router_reaches_search_orgs():
    with _found([_model_org()]):
        res = LF.lambda_handler(
            {"body": json.dumps(dict(PAYLOAD, service="search_orgs"))}, None
        )

    assert res["statusCode"] == 200
    assert res["body"]["organizations"]
