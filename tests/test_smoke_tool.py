"""The smoke test run after every deploy to `test` (#252), checked without AWS.

tools/smoke_check.py sends each sample in tests/smoke/ to the test function. These
tests pin that every sample is well formed and reaches the router service it
names, and that a server error or a missing field fails the run while every
response is still printed for the contributor who added the sample.
"""
import json
from pathlib import Path

import pytest

import lambda_function as LF
from tools import smoke_check as smoke

# The post-deploy smoke test: samples, routing, pass/fail and the report.
pytestmark = pytest.mark.unit

SMOKE_DIR = Path(__file__).resolve().parent / "smoke"
SAMPLES = smoke.load_samples(SMOKE_DIR)
HANDLERS = {
    "predict_category": "predict_category_handler",
    "generate_subject": "generate_subject_handler",
    "generate_answer": "generate_answer_handler",
    "emergency_contacts": "emergency_contacts_handler",
    "search_orgs": "search_orgs_handler",
}


def _sample(**overrides):
    sample = {"name": "a sample", "service": "predict_category", "body": {"description": "x"},
              "expect": {"status": 200, "body_keys": ["categories"]}}
    sample.update(overrides)
    return sample


def test_the_samples_cover_every_routed_service():
    assert {s["service"] for s in SAMPLES} == set(HANDLERS)
    assert any(s.get("body", {}).get("mode") == "volunteer_skills" for s in SAMPLES)


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["file"])
def test_every_sample_reaches_the_service_it_names(sample, monkeypatch):
    called = []
    for service, handler in HANDLERS.items():
        monkeypatch.setattr(LF, handler, lambda event, context, s=service: called.append(s) or {"statusCode": 200})
    LF.lambda_handler(smoke.build_event(sample), None)
    assert called == [sample["service"]]


def test_the_service_goes_in_the_body_or_the_query():
    in_body = smoke.build_event(_sample())
    assert json.loads(in_body["body"]) == {"description": "x", "service": "predict_category"}
    in_query = smoke.build_event({"name": "n", "service": "emergency_contacts", "query": {"country": "IN"}})
    assert in_query["queryStringParameters"] == {"country": "IN", "service": "emergency_contacts"}
    assert "body" not in in_query


@pytest.mark.parametrize("bad, problem", [
    ({"service": "predict_category"}, '"name" must be a non-empty string'),
    (_sample(body=["not", "an", "object"]), '"body" must be an object'),
    (_sample(expect={"status": "200"}), '"expect.status" must be a number'),
    (_sample(expect={"body_keys": "categories"}), '"expect.body_keys" must be a list'),
    (_sample(extra=1), "unknown fields ['extra']"),
])
def test_a_malformed_sample_is_named_with_its_problem(tmp_path, bad, problem):
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json") as e:
        smoke.load_samples(tmp_path)
    assert problem in str(e.value)


def test_proxy_and_plain_responses_are_both_read():
    assert smoke.parse_response({"statusCode": 200, "body": '{"subject": "s"}'}) == (200, {"subject": "s"})
    assert smoke.parse_response({"statusCode": 400, "body": {"error": "e"}}) == (400, {"error": "e"})
    assert smoke.parse_response("not json") == (None, "not json")


@pytest.mark.parametrize("status, body, expect, reason", [
    (502, {}, {}, "status 502"),
    (400, {}, {"status": 200}, "status 400, expected 200"),
    (200, {"other": 1}, {"body_keys": ["categories"]}, "the body is missing ['categories']"),
    (200, "text", {"body_keys": ["categories"]}, "the body is not a JSON object"),
    (None, None, {}, "no statusCode in the response"),
])
def test_a_failing_response_says_why(status, body, expect, reason):
    assert reason in smoke.check({"expect": expect}, status, body)


def test_a_passing_response_has_no_reasons_and_a_function_error_always_fails():
    sample = _sample()
    assert smoke.check(sample, 200, {"categories": []}) == []
    assert smoke.check(sample, 200, {"categories": []}, "Unhandled") == [
        "the function raised an error (Unhandled)"]


def test_the_run_reports_every_sample_and_fails_on_any_failure(tmp_path, capsys):
    answers = iter([({"statusCode": 200, "body": '{"categories": [1]}'}, None),
                    ({"statusCode": 502, "body": '{"error": "down"}'}, None)])
    results = smoke.run("ai-app-test", [_sample(name="first"), _sample(name="second")],
                        lambda fn, event: next(answers))
    summary = tmp_path / "summary.md"
    assert smoke.report(results, summary_path=str(summary)) is False
    printed = capsys.readouterr().out
    assert "ok   first" in printed and "FAIL second" in printed
    assert 'body: {"error": "down"}' in printed
    assert "1 of 2 sample requests passed." in printed
    assert "| second | 502 |" in summary.read_text(encoding="utf-8")


def test_a_call_that_raises_is_a_failure_not_a_crash():
    def boom(fn, event):
        raise TimeoutError("read timed out")
    [result] = smoke.run("ai-app-test", [_sample()], boom)
    assert result["reasons"] == ["the call failed: TimeoutError: read timed out"]


def test_main_exits_non_zero_only_when_a_sample_fails(monkeypatch, tmp_path):
    (tmp_path / "one.json").write_text(json.dumps(_sample()), encoding="utf-8")
    answer = {"payload": {"statusCode": 200, "body": '{"categories": []}'}}
    monkeypatch.setattr(smoke, "lambda_invoker", lambda region: lambda fn, event: (answer["payload"], None))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert smoke.main(["--function", "ai-app-test", "--fixtures", str(tmp_path)]) == 0
    answer["payload"] = {"statusCode": 500, "body": "{}"}
    assert smoke.main(["--function", "ai-app-test", "--fixtures", str(tmp_path)]) == 1
    assert smoke.main(["--function", "ai-app-test", "--fixtures", str(tmp_path / "empty")]) == 1
