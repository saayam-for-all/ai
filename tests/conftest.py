"""Shared fixtures for the GenAI regression suite.

Every test in this suite is hermetic: no test in the default run may open a
socket, read Postgres, or call a model provider. The fixtures here exist so
that individual test files stop re-declaring their own fakes, and so that the
"no I/O" rule is enforced in one place rather than trusted file by file.

Anything that genuinely needs the network must be marked ``needs_network``,
which ``pytest.ini`` excludes from the default run and from CI.
"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import lambda_function as LF  # noqa: E402


# ---------------------------------------------------------------------------
# Guardrail: the default run must not touch the network
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_network(request):
    """Fail any unmarked test that tries to open a URL.

    The emergency resolver calls ipinfo.io and Nominatim, and the search and
    answer services call model providers. A test that silently reaches one of
    those is not a regression test - it is a monitor for somebody else's
    uptime, and it fails for reasons that have nothing to do with our code.
    """
    if request.node.get_closest_marker("needs_network"):
        yield
        return
    def _blocked(*args, **kwargs):
        raise AssertionError(
            "This test made a live network call. Mock it, or mark the test "
            "with @pytest.mark.needs_network if the call is the point."
        )
    with mock.patch("urllib.request.urlopen", side_effect=_blocked):
        yield


# ---------------------------------------------------------------------------
# The module under test
# ---------------------------------------------------------------------------

@pytest.fixture
def handlers():
    """The lambda_function module, imported once."""
    return LF


@pytest.fixture
def emergency_directory():
    """The shipped emergency numbers directory, parsed."""
    path = REPO_ROOT / "services" / "emergency_numbers.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Event builders - these mirror what API Gateway actually delivers
# ---------------------------------------------------------------------------

@pytest.fixture
def proxy_event():
    """Build a PROXY-integration event (Emergency Contacts).

    Proxy is the only integration that forwards query parameters and the
    caller IP, which is why Emergency Contacts uses it.
    """
    def _build(query=None, body=None, source_ip="8.8.8.8"):
        event = {
            "queryStringParameters": dict(query or {}),
            "requestContext": {"identity": {"sourceIp": source_ip}},
        }
        if body is not None:
            event["body"] = body if isinstance(body, str) else json.dumps(body)
        return event
    return _build


@pytest.fixture
def json_event():
    """Build a non-proxy event whose body is a JSON string.

    Every service except Emergency Contacts is on non-proxy integration, so
    the client reads ``response.body.<field>`` as a structure.
    """
    def _build(payload=None, raw=None):
        if raw is not None:
            return {"body": raw}
        return {"body": json.dumps(payload or {})}
    return _build


# ---------------------------------------------------------------------------
# Fakes at the process edge
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_answer():
    """Patch the answer model. Yields a helper taking text or an exception."""
    def _patch(returns="A generated answer.", raises=None):
        if raises is not None:
            return mock.patch.object(LF, "generate_ai_answer", side_effect=raises)
        return mock.patch.object(LF, "generate_ai_answer", return_value=returns)
    return _patch


@pytest.fixture
def fake_request_row():
    """Patch the Postgres lookup.

    ``error_kind`` is what separates "this request does not exist" (a 404 the
    client can act on) from "the store is down" (a 503 it should retry), so
    the helper takes it explicitly rather than letting tests hand-roll a dict.
    """
    def _patch(subject="A subject", description="A description",
               location="Austin, TX", category_id="1", error_kind=None):
        if error_kind is not None:
            row = {"error": "stubbed failure", "error_kind": error_kind}
        else:
            row = {
                "req_subj": subject,
                "req_desc": description,
                "req_loc": location,
                "req_cat_id": category_id,
            }
        return mock.patch.object(LF, "_lookup_request", return_value=row)
    return _patch


@pytest.fixture
def no_database():
    """Assert the request store is never touched.

    Used to prove that a caller supplying subject and description is answered
    without Postgres - the core claim of issue #169.
    """
    return mock.patch.object(
        LF, "_lookup_request",
        side_effect=AssertionError("the database was read when it should not have been"),
    )


@pytest.fixture
def fake_organizations():
    """Patch organization search with a result, or with a provider failure."""
    def _patch(organizations=None, raises=None):
        if raises is not None:
            return mock.patch.object(LF, "find_organizations", side_effect=raises)
        return mock.patch.object(
            LF, "find_organizations",
            return_value={"organizations": list(organizations or [])},
        )
    return _patch


# ---------------------------------------------------------------------------
# Response readers
# ---------------------------------------------------------------------------

@pytest.fixture
def body_of():
    """Read a response body from either integration style.

    Proxy responses carry a JSON string; non-proxy responses carry the object
    itself. Tests should assert on content without caring which.
    """
    def _read(response):
        body = response.get("body")
        return json.loads(body) if isinstance(body, str) else body
    return _read
