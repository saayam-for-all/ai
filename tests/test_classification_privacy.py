"""Help-request and volunteer text stays out of logs and error bodies (issue #216).

A description is the user's own words. The model chain logs a reason on every
failover, and provider SDKs put whole HTTP response bodies in their exception
messages: Groq's ``json_validate_failed`` body carries ``failed_generation``, the
model's output, which can quote the description. These tests pin that a
failover log keeps what diagnoses an outage (type, HTTP status, error code) and
nothing else, and that the help-request ``500`` no longer returns ``str(e)``.

The first three tests are Surabhi Nair's, from PR #220.

No test in this file calls a live provider.
"""

import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors
from groq import APITimeoutError, BadRequestError, RateLimitError

import lambda_function
import services.classification_service as cs
from utils import token_usage
from utils.model_fallback import (
    ModelChainExhausted,
    ModelResponseError,
    ModelTarget,
    describe_model_error,
    run_model_chain,
)

pytestmark = pytest.mark.unit

PRIVATE_TEXT = "PRIVATE_VOLUNTEER_DESCRIPTION_12345"
_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _groq_error(cls, status, code):
    """A Groq SDK error built the way the SDK builds one, quoting the text."""
    body = {"error": {"code": code, "message": f"bad input: {PRIVATE_TEXT}",
                      "failed_generation": f'{{"evidence": "{PRIVATE_TEXT}"}}'}}
    return cls(
        f"Error code: {status} - {json.dumps(body)}",
        response=httpx.Response(status, request=_REQUEST),
        body=body,
    )


def _run_failing_chain(error):
    def failing_model(_target):
        raise error

    with pytest.raises(ModelChainExhausted):
        run_model_chain(
            invoke=failing_model,
            is_valid=bool,
            operation="predict_category",
            targets=[ModelTarget(provider="groq", model="test-model")],
        )


# ---------------------------------------------------------------------------
# From PR #220
# ---------------------------------------------------------------------------

def test_model_failure_does_not_log_private_text(caplog):
    with caplog.at_level(logging.WARNING):
        _run_failing_chain(RuntimeError(f"Model failed while processing {PRIVATE_TEXT}"))

    assert PRIVATE_TEXT not in caplog.text
    assert "RuntimeError" in caplog.text


def test_prediction_error_does_not_expose_private_text(monkeypatch, capsys):
    def failing_prediction(description):
        raise RuntimeError(f"Failed to classify {description}")

    monkeypatch.setattr(lambda_function, "predict_categories", failing_prediction)

    response = lambda_function.predict_category_handler(
        {"body": {"description": PRIVATE_TEXT}}, None
    )
    captured = capsys.readouterr()

    assert response["statusCode"] == 500
    assert response["body"] == {"error": "Category prediction failed"}
    assert PRIVATE_TEXT not in captured.out
    assert PRIVATE_TEXT not in captured.err
    assert PRIVATE_TEXT not in str(response)
    assert "RuntimeError" in captured.out  # the failure is still findable


def test_model_not_found_error_logs_safe_reason(caplog):
    with caplog.at_level(logging.WARNING):
        _run_failing_chain(RuntimeError(f"404 model_not_found: {PRIVATE_TEXT}"))

    assert "model_not_found" in caplog.text
    assert PRIVATE_TEXT not in caplog.text


# ---------------------------------------------------------------------------
# What a failover log keeps, with the SDKs' real exception types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "error, expected",
    [
        (_groq_error(RateLimitError, 429, "rate_limit_exceeded"),
         "RateLimitError status=429 code=rate_limit_exceeded"),
        (_groq_error(BadRequestError, 400, "json_validate_failed"),
         "BadRequestError status=400 code=json_validate_failed"),
        (APITimeoutError(request=_REQUEST), "APITimeoutError"),
        (genai_errors.ServerError(503, {"error": {
            "code": 503, "message": PRIVATE_TEXT, "status": "UNAVAILABLE"}}),
         "ServerError status=503 code=UNAVAILABLE"),
        (genai_errors.ClientError(429, {"error": {
            "code": 429, "message": PRIVATE_TEXT, "status": "RESOURCE_EXHAUSTED"}}),
         "ClientError status=429 code=RESOURCE_EXHAUSTED"),
    ],
    ids=["groq-429", "groq-json-validate", "groq-timeout", "gemini-503", "gemini-429"],
)
def test_a_provider_error_keeps_status_and_code_but_not_text(error, expected, caplog):
    """A 429 or a timeout must still show in CloudWatch; the text must not."""
    assert describe_model_error(error) == expected

    with caplog.at_level(logging.WARNING):
        _run_failing_chain(error)

    assert expected in caplog.text
    assert PRIVATE_TEXT not in caplog.text


def test_our_own_response_errors_are_logged_verbatim(caplog):
    """A ModelResponseError is written by our code, so its message is kept."""
    with caplog.at_level(logging.WARNING):
        _run_failing_chain(ModelResponseError("groq response content is empty"))

    assert "ModelResponseError: groq response content is empty" in caplog.text


def test_a_free_text_error_with_no_code_logs_only_its_type():
    assert describe_model_error(ValueError(PRIVATE_TEXT)) == "ValueError"


# ---------------------------------------------------------------------------
# End to end through the help-request classifier
# ---------------------------------------------------------------------------

def test_classification_failover_never_logs_the_description(monkeypatch, capsys, caplog):
    groq_error = _groq_error(BadRequestError, 400, "json_validate_failed")
    gemini_error = genai_errors.ServerError(
        503, {"error": {"code": 503, "message": PRIVATE_TEXT, "status": "UNAVAILABLE"}}
    )

    def raise_groq(**_kwargs):
        raise groq_error

    def raise_gemini(**_kwargs):
        raise gemini_error

    groq_stub = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=raise_groq))
    )
    gemini_stub = SimpleNamespace(models=SimpleNamespace(generate_content=raise_gemini))
    monkeypatch.setattr(cs, "client", groq_stub)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", gemini_stub)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ModelChainExhausted):
        cs.GroqClassificationService()._predict_ranked_level(
            PRIVATE_TEXT, ["1", "4"], accumulator=token_usage.new_accumulator(), depth=0
        )

    captured = capsys.readouterr()
    logged = captured.out + captured.err + caplog.text
    assert PRIVATE_TEXT not in logged
    assert "status=400 code=json_validate_failed" in caplog.text
    assert "status=503 code=UNAVAILABLE" in caplog.text
