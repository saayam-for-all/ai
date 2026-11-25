"""The daily model health and entitlement probe (issue #195, Part C).

The request path stops at the first model that answers, so a dead fallback is
invisible until the day it is needed. The probe's whole job is to look at the
models nobody is calling. These tests pin that it looks at all of them, that
it names the right error class (Part A's classifier), and that it writes the
metrics Part D's alarm watches. Hermetic: every provider call is a fake.
"""

from __future__ import annotations

import json
import logging
import threading

import groq
import httpx
import pytest
from google.genai import errors as genai_errors

import lambda_function as LF
import utils.client as client
import utils.model_health_probe as probe


pytestmark = pytest.mark.unit

_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
SECRET = "SENTINEL-PROVIDER-DETAIL-195"

CHAIN = probe.configured_model_chain()
PRIMARY = CHAIN[0]
LAST_RESORT = CHAIN[-1]


def _groq(cls, status):
    body = {"error": {"message": SECRET}}
    return cls(
        f"Error code: {status} {SECRET}",
        response=httpx.Response(status, request=_REQUEST, json=body),
        body=body,
    )


def _gemini(code, status):
    return genai_errors.ClientError(
        code, {"error": {"code": code, "message": SECRET, "status": status}}
    )


def _invoke(outcomes):
    """Fake provider: answers by model id, raising when given an exception."""
    calls = []

    def invoke(target):
        calls.append(target.model)
        outcome = outcomes.get(target.model, "OK")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    invoke.calls = calls
    return invoke


class _Clock:
    """Each call advances 250 ms, so every probe measures 250 ms."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        value = self.now
        self.now += 0.25
        return value


# ---------------------------------------------------------------------------
# What gets probed
# ---------------------------------------------------------------------------

def test_every_model_in_the_chain_is_probed_including_unused_fallbacks():
    invoke = _invoke({})
    results = probe.run_probe(invoke=invoke)

    assert invoke.calls == [target.model for target in CHAIN]
    assert [r.model for r in results] == [target.model for target in CHAIN]
    assert results[0].role == "primary"
    assert all(r.role == "fallback" for r in results[1:])


def test_the_probe_reads_the_same_chain_requests_use():
    from utils import model_fallback

    assert probe.configured_model_chain() is model_fallback._DEFAULT_MODEL_CHAIN


def test_a_healthy_primary_does_not_stop_the_probe():
    # run_model_chain would stop here. The probe must not.
    invoke = _invoke({})
    probe.run_probe(invoke=invoke)
    assert LAST_RESORT.model in invoke.calls


def test_a_dead_fallback_behind_a_healthy_primary_is_reported():
    """The gemini-2.0-flash case: the last resort was shut down on 1 June
    2026 and nothing noticed, because nothing called it."""
    results = probe.run_probe(
        invoke=_invoke({LAST_RESORT.model: _gemini(404, "NOT_FOUND")})
    )
    summary = probe.summarize(results)

    assert summary["healthy"] is False
    assert summary["failed"] == 1
    dead = next(r for r in summary["results"] if r["model"] == LAST_RESORT.model)
    assert dead["reachable"] is False
    assert dead["error_class"] == "model_not_found"
    assert dead["role"] == "fallback"


# ---------------------------------------------------------------------------
# Telling failures apart (Part A's names)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "error,expected",
    [
        pytest.param(_groq(groq.NotFoundError, 404), "model_not_found", id="groq-404"),
        pytest.param(_gemini(404, "NOT_FOUND"), "model_not_found", id="gemini-404"),
        pytest.param(_groq(groq.AuthenticationError, 401), "auth_or_entitlement",
                     id="groq-401"),
        pytest.param(_groq(groq.PermissionDeniedError, 403), "auth_or_entitlement",
                     id="groq-403"),
        pytest.param(_groq(groq.RateLimitError, 429), "rate_limited", id="groq-429"),
        pytest.param(_gemini(429, "RESOURCE_EXHAUSTED"), "rate_limited",
                     id="gemini-429"),
        pytest.param(groq.APITimeoutError(request=_REQUEST), "timeout_or_unavailable",
                     id="groq-timeout"),
        pytest.param(_groq(groq.InternalServerError, 503), "timeout_or_unavailable",
                     id="groq-503"),
    ],
)
def test_each_failure_is_recorded_with_its_error_class(error, expected):
    (result,) = probe.run_probe(
        targets=[PRIMARY], invoke=_invoke({PRIMARY.model: error})
    )
    assert result.reachable is False
    assert result.error_class == expected


@pytest.mark.parametrize("status", [401, 403])
def test_a_lapsed_subscription_is_not_reported_as_a_retired_model(status):
    cls = groq.AuthenticationError if status == 401 else groq.PermissionDeniedError
    (result,) = probe.run_probe(
        targets=[PRIMARY], invoke=_invoke({PRIMARY.model: _groq(cls, status)})
    )
    assert result.error_class == "auth_or_entitlement"
    assert result.error_class != "model_not_found"


def test_an_empty_answer_is_not_healthy():
    (result,) = probe.run_probe(targets=[PRIMARY], invoke=_invoke({PRIMARY.model: "  "}))
    assert result.reachable is False
    assert result.error_class == probe.EMPTY_RESPONSE


def test_a_model_that_hangs_is_given_up_on_and_the_rest_are_still_checked():
    release = threading.Event()

    def invoke(target):
        if target.model == PRIMARY.model:
            release.wait(5)  # far longer than the probe's timeout
        return "OK"

    try:
        results = probe.run_probe(invoke=invoke, timeout=0.05)
    finally:
        release.set()

    assert results[0].reachable is False
    assert results[0].error_class == "timeout_or_unavailable"
    assert all(r.reachable for r in results[1:])


def test_latency_is_recorded_for_success_and_failure():
    results = probe.run_probe(
        targets=CHAIN[:2],
        invoke=_invoke({CHAIN[1].model: _groq(groq.RateLimitError, 429)}),
        clock=_Clock(),
    )
    assert [r.latency_ms for r in results] == [250, 250]


def test_a_probe_never_raises_whatever_the_provider_does():
    class Weird(Exception):
        """Not a provider error any SDK would raise."""

    results = probe.run_probe(invoke=_invoke({PRIMARY.model: Weird("odd")}))
    assert len(results) == len(CHAIN)
    assert results[0].error_class == "other"


# ---------------------------------------------------------------------------
# What a person sees: logs, metrics, handler output
# ---------------------------------------------------------------------------

def test_a_failing_model_logs_a_warning_naming_model_and_class(caplog):
    with caplog.at_level(logging.INFO, logger=probe.__name__):
        probe.run_probe(
            invoke=_invoke({LAST_RESORT.model: _gemini(429, "RESOURCE_EXHAUSTED")})
        )

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    line = warnings[0]
    assert f"model={LAST_RESORT.model} " in line
    assert "error_class=rate_limited" in line
    assert "reachable=false" in line
    # Every key before the free text, as Part A's review asked.
    assert line.index("error_class=") < line.index("reason=")


def test_a_failure_log_never_carries_the_provider_message(caplog):
    with caplog.at_level(logging.INFO, logger=probe.__name__):
        probe.run_probe(invoke=_invoke({PRIMARY.model: _groq(groq.RateLimitError, 429)}))
    assert SECRET not in caplog.text


def test_a_healthy_run_logs_no_warning(caplog):
    with caplog.at_level(logging.INFO, logger=probe.__name__):
        probe.run_probe(invoke=_invoke({}))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert sum("MODEL_PROBE" in r.getMessage() for r in caplog.records) == len(CHAIN)


def _emf_records(capsys):
    records = []
    for line in capsys.readouterr().out.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "_aws" in parsed:
            records.append(parsed)
    return records


def _value(record, name):
    """EMF may store a value as a list of floats; one write, one value."""
    value = record[name]
    return value[0] if isinstance(value, list) else value


def _records_for(records, name):
    return [r for r in records if name in r]


@pytest.mark.parametrize("dead_models", [0, 1, len(CHAIN)])
def test_the_alarm_metric_counts_failing_models_and_is_written_when_zero(
    capsys, dead_models
):
    outcomes = {
        target.model: _groq(groq.NotFoundError, 404) for target in CHAIN[:dead_models]
    }
    probe.publish_metrics(probe.run_probe(invoke=_invoke(outcomes)))

    (record,) = _records_for(_emf_records(capsys), probe.FAILURES_METRIC)
    directive = record["_aws"]["CloudWatchMetrics"][0]
    assert directive["Namespace"] == "Saayam/GenAI"
    assert directive["Dimensions"] == [["service"]]
    assert record["service"] == "model_health_probe"
    assert _value(record, probe.FAILURES_METRIC) == dead_models


def test_each_model_gets_its_own_reachable_and_latency_series(capsys):
    probe.publish_metrics(
        probe.run_probe(
            invoke=_invoke({LAST_RESORT.model: _gemini(404, "NOT_FOUND")}),
            clock=_Clock(),
        )
    )
    records = _emf_records(capsys)

    reachable = {r["model"]: _value(r, probe.REACHABLE_METRIC)
                 for r in _records_for(records, probe.REACHABLE_METRIC)}
    latency = {r["model"]: _value(r, probe.LATENCY_METRIC)
               for r in _records_for(records, probe.LATENCY_METRIC)}

    assert reachable == {t.model: (0 if t is LAST_RESORT else 1) for t in CHAIN}
    assert latency == {t.model: 250 for t in CHAIN}
    for record in _records_for(records, probe.REACHABLE_METRIC):
        assert sorted(record["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]) == [
            "model", "provider"]


def test_the_lambda_handler_runs_hermetically_and_reports_missing_keys(
    monkeypatch, capsys
):
    # With no keys loaded every call fails before reaching a provider. The
    # handler still checks every model, returns a summary and writes the
    # alarm metric.
    monkeypatch.setattr(client, "GROQ_API_KEY", None)
    monkeypatch.setattr(client, "GEMINI_API_KEY", None)

    summary = LF.model_health_probe_handler({}, None)

    assert summary["checked"] == len(CHAIN)
    assert summary["failed"] == len(CHAIN)
    assert summary["healthy"] is False
    (record,) = _records_for(_emf_records(capsys), probe.FAILURES_METRIC)
    assert _value(record, probe.FAILURES_METRIC) == len(CHAIN)


def test_the_summary_never_carries_provider_detail():
    results = probe.run_probe(invoke=_invoke({PRIMARY.model: _groq(groq.RateLimitError, 429)}))
    summary = probe.summarize(results)
    assert SECRET not in json.dumps(summary)
    assert all("reason" not in row for row in summary["results"])


def test_the_probe_is_not_reachable_through_the_public_router():
    """Anyone who can reach the API could otherwise spend provider quota."""
    response = LF.lambda_handler({"service": "model_health_probe"}, None)
    assert response["statusCode"] == 400
