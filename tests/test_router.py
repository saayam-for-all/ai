"""Router-level regression tests - issue #171.

Every service in this repository is packaged into one deployment, and
``lambda_handler`` is the fallback entry point that decides which handler a
request reaches. Nothing tested that decision before: the per-service suites
each call their own handler directly, so a routing mistake - a service name
that stopped resolving, an alias that was dropped, a malformed body turning
into a 500 - would have passed every test while breaking the deployed API.

These are the tests that cover the seam between the services rather than the
services themselves.
"""
import json
from unittest import mock

import pytest

import lambda_function as LF

pytestmark = pytest.mark.integration


SERVICES = [
    ("predict_category", "predict_category_handler"),
    ("generate_subject", "generate_subject_handler"),
    ("generate_answer", "generate_answer_handler"),
    ("emergency_contacts", "emergency_contacts_handler"),
    ("search_orgs", "search_orgs_handler"),
    # The aggregator may address organization search under any of these.
    ("search_org", "search_orgs_handler"),
    ("find_nonprofits", "search_orgs_handler"),
]

SENTINEL = {"statusCode": 200, "body": {"routed": True}}


@pytest.mark.parametrize("service,handler_name", SERVICES)
def test_service_in_body_reaches_its_handler(service, handler_name):
    with mock.patch.object(LF, handler_name, return_value=SENTINEL) as handler:
        result = LF.lambda_handler({"body": json.dumps({"service": service})}, None)
    assert handler.called, f"{service!r} did not reach {handler_name}"
    assert result is SENTINEL


@pytest.mark.parametrize("service,handler_name", SERVICES)
def test_service_in_query_string_reaches_its_handler(service, handler_name):
    event = {"queryStringParameters": {"service": service}}
    with mock.patch.object(LF, handler_name, return_value=SENTINEL) as handler:
        result = LF.lambda_handler(event, None)
    assert handler.called, f"{service!r} in the query string did not reach {handler_name}"
    assert result is SENTINEL


@pytest.mark.parametrize("service", ["GENERATE_ANSWER", "  Generate_Answer  ", "generate_answer"])
def test_service_name_is_case_and_whitespace_insensitive(service):
    with mock.patch.object(LF, "generate_answer_handler", return_value=SENTINEL) as handler:
        LF.lambda_handler({"body": json.dumps({"service": service})}, None)
    assert handler.called


def test_query_string_wins_over_body():
    """An explicit query parameter is the more specific instruction."""
    event = {
        "queryStringParameters": {"service": "generate_subject"},
        "body": json.dumps({"service": "generate_answer"}),
    }
    with mock.patch.object(LF, "generate_subject_handler", return_value=SENTINEL) as chosen:
        with mock.patch.object(LF, "generate_answer_handler", return_value=SENTINEL) as other:
            LF.lambda_handler(event, None)
    assert chosen.called and not other.called


def test_absent_service_defaults_to_predict_category():
    """Back-compat: the original single-service deployment had no `service`."""
    with mock.patch.object(LF, "predict_category_handler", return_value=SENTINEL) as handler:
        LF.lambda_handler({"body": json.dumps({"subject": "x"})}, None)
    assert handler.called


def test_unknown_service_returns_the_documented_shape():
    result = LF.lambda_handler({"body": json.dumps({"service": "does_not_exist"})}, None)
    assert result["statusCode"] == 400
    body = result["body"]
    assert "does_not_exist" in body["error"]
    # The message has to name the alternatives, or a caller cannot self-correct.
    for service in ("predict_category", "generate_subject", "generate_answer",
                    "emergency_contacts", "search_orgs"):
        assert service in body["error"]


@pytest.mark.parametrize("raw", ["{not json", "", "   ", "[1, 2, 3]", '"a bare string"'])
def test_a_body_that_is_not_an_object_never_500s(raw):
    """A malformed body is a client error, not a server error.

    The router parses the body only to discover the service name. Letting a
    JSONDecodeError escape turned every malformed request into a 500, which
    reads as "we are broken" rather than "your payload is wrong" and is
    unactionable in an alert.
    """
    with mock.patch.object(LF, "predict_category_handler", return_value=SENTINEL):
        result = LF.lambda_handler({"body": raw}, None)
    assert result["statusCode"] != 500, f"malformed body {raw!r} produced a 500"


def test_malformed_body_is_reported_as_400():
    result = LF.lambda_handler({"body": "{not json"}, None)
    assert result["statusCode"] == 400
    assert "JSON" in result["body"]["error"]


def test_malformed_body_still_routes_when_the_query_string_named_the_service():
    """The body is not the router's problem once the service is known.

    The router only reads the body to discover the service. When the query
    string already named one, dispatch proceeds and the routed handler reports
    the bad payload in its own error contract, which is more specific than
    anything the router could say about it.
    """
    event = {"queryStringParameters": {"service": "generate_answer"}, "body": "{not json"}
    with mock.patch.object(LF, "generate_answer_handler", return_value=SENTINEL) as handler:
        result = LF.lambda_handler(event, None)
    assert handler.called, "the router swallowed a request it should have dispatched"
    assert result is SENTINEL


def test_an_empty_event_does_not_crash():
    with mock.patch.object(LF, "predict_category_handler", return_value=SENTINEL):
        result = LF.lambda_handler({}, None)
    assert result["statusCode"] != 500


def test_non_proxy_services_keep_an_object_body():
    """The mirror image: these clients read response.body.<field>.

    Serialising the body here would turn every one of those reads into
    undefined.
    """
    result = LF.lambda_handler({"body": json.dumps({"service": "nope"})}, None)
    assert isinstance(result["body"], dict)


def test_a_handler_raising_does_not_leak_internals():
    """An unexpected error must not put a stack trace or a key in the body."""
    event = {"body": json.dumps({"service": "search_orgs", "description": "d"})}
    with mock.patch.object(
        LF, "search_orgs_handler",
        side_effect=RuntimeError("gemini key sk-secret123 rejected at api.gemini.com"),
    ):
        result = LF.lambda_handler(event, None)
    rendered = json.dumps(result["body"])
    assert "sk-secret123" not in rendered


def test_every_advertised_service_has_a_handler():
    """The router's error message lists the services it supports.

    If that list and the dispatch table drift apart, a caller is told to use a
    service name that does not route.
    """
    import lambda_function as LF

    advertised = LF.lambda_handler({"body": json.dumps({"service": "unknown"})}, None)
    listed = advertised["body"]["error"].split("Supported:")[1]
    for service in [s.strip() for s in listed.split(",")]:
        sentinel = {"statusCode": 200, "body": {}}
        handler_name = {
            "predict_category": "predict_category_handler",
            "generate_subject": "generate_subject_handler",
            "generate_answer": "generate_answer_handler",
            "emergency_contacts": "emergency_contacts_handler",
            "search_orgs": "search_orgs_handler",
        }[service]
        with mock.patch.object(LF, handler_name, return_value=sentinel) as handler:
            LF.lambda_handler({"body": json.dumps({"service": service})}, None)
        assert handler.called, f"{service} is advertised but does not route"
