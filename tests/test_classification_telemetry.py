"""The CLASSIFICATION_OUTCOME line and the alarms built on it (issue #197, stack 5).

The line exists so that "everything is General" and "the model is down" stop
looking the same. These tests check that each outcome is told apart, that the
line is valid CloudWatch EMF, that it never carries the description, that it
is printed even when the prediction fails, and that it can never break a
request. The last part checks the alarm and query definitions against the
metrics the line actually emits.
"""

import contextlib
import io
import json
import logging
import re
from types import SimpleNamespace

import pytest

import services.classification_service as cs
from tools import setup_observability as setup
from utils import classification_telemetry as telemetry
from utils.model_fallback import ModelChainExhausted, _DEFAULT_MODEL_CHAIN

pytestmark = pytest.mark.unit

PRIMARY = f"{_DEFAULT_MODEL_CHAIN[0].provider}/{_DEFAULT_MODEL_CHAIN[0].model}"
SECONDARY = f"{_DEFAULT_MODEL_CHAIN[1].provider}/{_DEFAULT_MODEL_CHAIN[1].model}"


def _usage(*models, tokens=120):
    calls = [dict(zip(("provider", "model"), m.split("/", 1))) for m in models]
    return {"total_tokens": tokens, "calls": calls}


def _outcome(results, usage=None, error=None, elderly=False):
    return telemetry.build_outcome(
        results, usage or _usage(PRIMARY), error=error,
        elapsed_ms=12.34, elderly_routed=elderly, description_chars=26,
    )


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("results", "error", "outcome", "flag"),
    [
        ([{"category_number": "3.3.1", "confidence": 0.9}], None, "categorised", None),
        ([{"category_number": "0.0.0.0.0", "confidence": 0.4}], None, "general", "General"),
        ([], None, "empty", "Empty"),
        (None, ModelChainExhausted("down"), "error", "Error"),
    ],
)
def test_each_outcome_is_told_apart_and_sets_only_its_own_flag(results, error, outcome, flag):
    """General, empty and error each get a distinct outcome and exactly one flag.

    This is the distinction that was missing when an outage went unnoticed:
    from outside, all three used to look like "General".
    """
    record = _outcome(results, error=error)
    assert record["outcome"] == outcome
    flags = {name: record[name] for name in ("General", "Empty", "Error")}
    assert flags == {name: int(name == flag) for name in flags}


def test_error_type_names_the_exception():
    """An error line says what failed, so an alarm can be triaged from the log."""
    assert _outcome(None, error=ModelChainExhausted("x"))["error_type"] == "ModelChainExhausted"


@pytest.mark.parametrize(("category", "depth"), [("3", 1), ("3.3", 2), ("3.3.1", 3), ("0.0.0.0.0", 0)])
def test_depth_is_how_far_down_the_taxonomy_the_answer_is(category, depth):
    """Depth counts levels of the chosen category; General is depth 0, not 5."""
    assert _outcome([{"category_number": category}])["depth"] == depth


@pytest.mark.parametrize(
    ("models", "fallback"),
    [((PRIMARY,), 0), ((PRIMARY, PRIMARY), 0), ((PRIMARY, SECONDARY), 1), ((SECONDARY,), 1), ((), 0)],
)
def test_fallback_is_any_answer_from_a_model_other_than_the_primary(models, fallback):
    """A fallback means the answer was not from the model the golden set measured."""
    assert _outcome([{"category_number": "1"}], _usage(*models))["Fallback"] == fallback


def test_cost_and_routing_fields_come_from_the_request():
    """Calls, tokens, latency and the router decision are carried through."""
    record = _outcome([{"category_number": "6.5"}], _usage(PRIMARY, PRIMARY, tokens=240), elderly=True)
    assert (record["ModelCalls"], record["Tokens"], record["LatencyMs"], record["ElderlyRouted"]) == (2, 240, 12.3, 1)


def test_a_malformed_usage_record_still_yields_a_record():
    """A usage value that is not an accumulator degrades to zero cost, not an exception."""
    record = _outcome([{"category_number": "1"}], usage="not a dict")
    assert record["ModelCalls"] == 0 and record["Tokens"] == 0


# ---------------------------------------------------------------------------
# EMF
# ---------------------------------------------------------------------------

def test_the_line_is_valid_embedded_metric_format():
    """Every declared metric is a number at the top level, and the dimension is present.

    CloudWatch silently drops a metric whose value is missing or not a
    number, so a typo here would give an alarm that can never fire.
    """
    line = telemetry.to_emf(_outcome([{"category_number": "1"}]), timestamp_ms=1_700_000_000_000)
    directive = line["_aws"]["CloudWatchMetrics"][0]
    assert line["_aws"]["Timestamp"] == 1_700_000_000_000
    assert directive["Namespace"] == telemetry.NAMESPACE
    for dimension_set in directive["Dimensions"]:
        assert all(isinstance(line[key], str) for key in dimension_set)
    for metric in directive["Metrics"]:
        assert isinstance(line[metric["Name"]], (int, float)) and not isinstance(line[metric["Name"]], bool)
    assert {m["Name"] for m in directive["Metrics"]} == set(telemetry.METRICS)


# ---------------------------------------------------------------------------
# Wired into predict_categories
# ---------------------------------------------------------------------------

class _FirstChoiceGroq:
    """A fake Groq client that ranks first the first category it is offered."""

    def __init__(self, failing_models=()):
        self.failing_models = set(failing_models)
        outer = self

        class _Completions:
            def create(self, **kwargs):
                if kwargs["model"] in outer.failing_models:
                    raise RuntimeError("404 model_not_found")
                prompt = kwargs["messages"][0]["content"]
                offered = re.findall(r"^([\d.]+):", prompt.split("Categories:\n", 1)[1], re.M)
                content = json.dumps({"categories": [{"category": offered[0], "confidence": 0.9}]})
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                    usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
                )

        self.chat = SimpleNamespace(completions=_Completions())


def _predict(monkeypatch, description, failing_models=()):
    """Run the real predict_categories; return (outcome lines, raised exception or None)."""
    monkeypatch.setattr(cs, "client", _FirstChoiceGroq(failing_models))
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", None)
    buffer, raised = io.StringIO(), None
    with contextlib.redirect_stdout(buffer):
        try:
            cs.predict_categories(description)
        except Exception as error:  # noqa: BLE001 - returned for the test to assert on
            raised = error
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if f'"{telemetry.EVENT}"' in line]
    return lines, raised


def test_a_prediction_prints_exactly_one_outcome_line(monkeypatch):
    """One request, one line; the existing TOKEN_USAGE line is still printed too."""
    lines, raised = _predict(monkeypatch, "Hello, is anyone there?")
    assert raised is None and len(lines) == 1
    assert lines[0]["outcome"] == "general" and lines[0]["ModelCalls"] == 1


def test_an_exhausted_model_chain_still_prints_its_line_and_still_raises(monkeypatch):
    """The failing request is the one most worth counting, and the handler still sees the error."""
    every_groq = [t.model for t in _DEFAULT_MODEL_CHAIN if t.provider == "groq"]
    lines, raised = _predict(monkeypatch, "My kitchen sink is leaking", failing_models=every_groq)
    assert isinstance(raised, ModelChainExhausted)
    assert len(lines) == 1 and lines[0]["outcome"] == "error" and lines[0]["Error"] == 1


def test_a_retired_primary_model_is_counted_as_a_fallback(monkeypatch):
    """The answer still arrives, and the line says it came from a fallback model."""
    lines, raised = _predict(monkeypatch, "My kitchen sink is leaking", failing_models=[_DEFAULT_MODEL_CHAIN[0].model])
    assert raised is None and lines[0]["Fallback"] == 1 and lines[0]["Error"] == 0


def test_the_description_is_never_logged(monkeypatch):
    """Only the length of the person's text is recorded, never the text."""
    description = "My name is Priya Raman and my kitchen sink is leaking"
    lines, _ = _predict(monkeypatch, description)
    serialised = json.dumps(lines[0])
    assert "Priya" not in serialised and "sink" not in serialised
    assert lines[0]["description_chars"] == len(description)


def test_the_router_decision_is_recorded(monkeypatch):
    """A request the elderly router diverts is flagged, so its share can be watched."""
    lines, _ = _predict(monkeypatch, "Our aging roof leaks every time it rains.")
    assert lines[0]["ElderlyRouted"] == 1


def test_telemetry_that_fails_never_breaks_the_request(monkeypatch, caplog):
    """If building the line raises, the prediction is still returned and the failure is logged."""
    def explode(*args, **kwargs):
        raise TypeError("boom")
    monkeypatch.setattr(telemetry, "build_outcome", explode)
    monkeypatch.setattr(cs, "client", _FirstChoiceGroq())
    monkeypatch.setattr(cs, "_use_groq", True)
    with caplog.at_level(logging.ERROR), contextlib.redirect_stdout(io.StringIO()):
        results, _ = cs.predict_categories("Hello, is anyone there?")
    assert results and "could not build or print the outcome line" in caplog.text


# ---------------------------------------------------------------------------
# Alarm and query definitions
# ---------------------------------------------------------------------------

DEFINITIONS = setup.load_definitions()


def test_definitions_use_the_namespace_and_dimension_the_line_emits():
    """An alarm on a namespace or dimension nobody writes to would never fire."""
    assert DEFINITIONS["namespace"] == telemetry.NAMESPACE
    assert DEFINITIONS["dimensions"] == {"Service": telemetry.SERVICE}


@pytest.mark.parametrize("alarm", DEFINITIONS["alarms"], ids=lambda a: a["name"])
def test_every_alarm_is_a_rate_over_metrics_the_line_emits(alarm):
    """Each alarm divides emitted metrics by Requests, guarded by a minimum volume."""
    request = setup.alarm_request(alarm, DEFINITIONS)
    named = {q["MetricStat"]["Metric"]["MetricName"] for q in request["Metrics"] if "MetricStat" in q}
    assert named <= set(telemetry.METRICS) and "Requests" in named
    (rate,) = [q for q in request["Metrics"] if q.get("ReturnData")]
    assert rate["Expression"].startswith(f"IF(requests >= {alarm['min_requests']},")
    assert 0 < request["Threshold"] < 1 and request["TreatMissingData"] == "notBreaching"


def test_an_sns_topic_is_notified_on_alarm_and_on_recovery():
    """With a topic, both the alarm and its all-clear are sent; without one, neither."""
    alarm = DEFINITIONS["alarms"][0]
    with_topic = setup.alarm_request(alarm, DEFINITIONS, "arn:aws:sns:us-east-1:1:t")
    assert with_topic["AlarmActions"] == with_topic["OKActions"] == ["arn:aws:sns:us-east-1:1:t"]
    assert "AlarmActions" not in setup.alarm_request(alarm, DEFINITIONS)


@pytest.mark.parametrize("query", DEFINITIONS["queries"], ids=lambda q: q["name"])
def test_every_query_reads_only_outcome_lines(query):
    """Each saved query filters on the event name, so it never mixes in other log lines."""
    assert query["query"].startswith(f'filter event = "{telemetry.EVENT}"')


def test_dry_run_prints_the_plan_and_sends_nothing(monkeypatch, capsys):
    """The default must be safe to run by anyone, with no AWS credentials."""
    monkeypatch.setattr(setup, "apply", lambda *a, **k: pytest.fail("dry run called AWS"))
    assert setup.main([]) == 0
    assert "Dry run: nothing was sent" in capsys.readouterr().out


def test_apply_refuses_the_placeholder_log_group():
    """--apply without a real log group would save queries against nothing."""
    with pytest.raises(SystemExit):
        setup.main(["--apply"])


def test_apply_upserts_alarms_and_updates_existing_queries_in_place():
    """Running twice must not duplicate saved queries: an existing name is updated by id."""
    sent = {"alarms": [], "queries": []}
    existing_name = DEFINITIONS["queries"][0]["name"]

    class _Paginator:
        def paginate(self):
            return [{"queryDefinitions": [{"name": existing_name, "queryDefinitionId": "q-1"}]}]

    cloudwatch = SimpleNamespace(put_metric_alarm=lambda **r: sent["alarms"].append(r))
    logs = SimpleNamespace(
        get_paginator=lambda name: _Paginator(),
        put_query_definition=lambda **r: sent["queries"].append(r),
    )
    with contextlib.redirect_stdout(io.StringIO()):
        setup.apply(setup.plan(DEFINITIONS, "/aws/lambda/pc"), cloudwatch, logs)

    assert len(sent["alarms"]) == len(DEFINITIONS["alarms"])
    assert len(sent["queries"]) == len(DEFINITIONS["queries"])
    assert sent["queries"][0]["queryDefinitionId"] == "q-1"
    assert all("queryDefinitionId" not in q for q in sent["queries"][1:])
    assert all(q["logGroupNames"] == ["/aws/lambda/pc"] for q in sent["queries"])
