"""
Guards the two failure modes behind "every request lands in General".

1. A retired Groq model (or any Groq API error) must NOT crash the request.
   The classifier must continue through the configured Groq targets and then
   use Gemini if none of them succeeds.

2. Model IDs and per-model request options must come from model_routing.json,
   rather than hardcoded literals that can silently go stale.

No network calls and no API keys required: the Groq client is stubbed.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from groq import GroqError

import lambda_function as LF
import services.classification_service as cs
from utils import token_usage
from utils.model_fallback import ModelChainExhausted, ModelTarget


# Category prediction degrades rather than failing when the model or its
# artefacts are unavailable.
pytestmark = pytest.mark.unit


_ROUTING_CONFIG = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "model_routing.json")
    .read_text(encoding="utf-8")
)
_CONFIGURED_GROQ_MODELS = [
    entry["model"]
    for entry in _ROUTING_CONFIG["model_chain"]
    if entry["provider"] == "groq"
]
_CONFIGURED_GEMINI_MODEL = next(
    entry["model"]
    for entry in _ROUTING_CONFIG["model_chain"]
    if entry["provider"] == "gemini"
)


def _groq_response(payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


class _ModelAwareGroq:
    """Fake raw client whose result is selected by the requested model id."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                outcome = outer.outcomes[kwargs["model"]]
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class _RecordingGemini:
    """Fake raw Gemini client that records the model and prompt it receives."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []
        outer = self

        class _Models:
            def generate_content(self, **kwargs):
                outer.calls.append(kwargs)
                if outer.error is not None:
                    raise outer.error
                return SimpleNamespace(text=json.dumps(outer.payload))

        self.models = _Models()


def test_classifier_does_not_own_hardcoded_model_ids():
    service = cs.GroqClassificationService()
    assert not hasattr(service, "model")
    assert not hasattr(service, "gemini_model")


def test_gpt_oss_uses_low_reasoning_effort():
    service = cs.GroqClassificationService()
    configured = ModelTarget(
        provider="groq",
        model="openai/gpt-oss-20b",
        reasoning_effort="low",
    )
    unconfigured = ModelTarget(provider="groq", model="some-other-model")

    assert service._groq_extra_kwargs(configured) == {"reasoning_effort": "low"}
    assert service._groq_extra_kwargs(unconfigured) == {}


def _assert_groq_error_falls_back(monkeypatch, exc):
    """A failed Groq attempt must advance to the next configured model."""
    primary, secondary = _CONFIGURED_GROQ_MODELS[:2]
    groq = _ModelAwareGroq(
        {
            primary: exc,
            secondary: _groq_response({"category": "1", "confidence": 0.9}),
        }
    )
    gemini = _RecordingGemini(payload={"category": "1", "confidence": 0.9})
    monkeypatch.setattr(cs, "client", groq)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", gemini)

    result = cs.GroqClassificationService()._predict_one_level(
        "I need help with math",
        ["1", "4"],
        accumulator=token_usage.new_accumulator(),
        depth=0,
    )

    assert result == {"category": "1", "confidence": 0.9}
    assert [call["model"] for call in groq.calls] == [primary, secondary]
    assert not gemini.calls


def test_retired_model_error_does_not_crash_request(monkeypatch):
    # What a decommissioned model actually raises (404 model_not_found).
    _assert_groq_error_falls_back(
        monkeypatch,
        GroqError("Error code: 404 - model `llama-3.1-8b-instant` does not exist")
    )


def test_json_validate_failed_does_not_crash_request(monkeypatch):
    # What a reasoning model raises when it starves the JSON grammar (400).
    _assert_groq_error_falls_back(
        monkeypatch,
        GroqError("Error code: 400 - json_validate_failed"),
    )


def test_parsing_errors_still_handled(monkeypatch):
    # The pre-existing error classes must remain covered.
    _assert_groq_error_falls_back(
        monkeypatch,
        json.JSONDecodeError("bad", "doc", 0),
    )
    _assert_groq_error_falls_back(
        monkeypatch,
        ValueError("Groq response content is empty"),
    )


@pytest.mark.parametrize(
    ("method_name", "successful_payload", "expected"),
    [
        (
            "_predict_one_level",
            {"category": "1", "confidence": 0.91},
            {"category": "1", "confidence": 0.91},
        ),
        (
            "_predict_ranked_level",
            {"categories": [{"category": "1", "confidence": 0.91}]},
            [{"category": "1", "confidence": 0.91}],
        ),
    ],
)
def test_primary_failure_tries_secondary_groq_before_gemini(
    monkeypatch, method_name, successful_payload, expected
):
    """Both raw classification calls must use the shared model chain."""
    primary, secondary = _CONFIGURED_GROQ_MODELS[:2]
    groq = _ModelAwareGroq(
        {
            primary: GroqError("404 model_not_found"),
            secondary: _groq_response(successful_payload),
        }
    )
    gemini = _RecordingGemini(payload=successful_payload)
    monkeypatch.setattr(cs, "client", groq)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", gemini)

    service = cs.GroqClassificationService()
    result = getattr(service, method_name)(
        "I need help with math",
        ["1", "4"],
        accumulator=token_usage.new_accumulator(),
        depth=0,
    )

    assert result == expected
    assert [call["model"] for call in groq.calls] == [primary, secondary]
    assert not gemini.calls, "Gemini must wait until every Groq model fails"

    # Retrying must change only the model-specific options, not the task.
    assert groq.calls[0]["messages"] == groq.calls[1]["messages"]
    assert groq.calls[0]["response_format"] == {"type": "json_object"}
    assert groq.calls[1]["response_format"] == {"type": "json_object"}
    assert groq.calls[0]["reasoning_effort"] == "low"
    assert groq.calls[1]["reasoning_effort"] == "low"


def test_healthy_primary_is_not_retried(monkeypatch):
    primary = _CONFIGURED_GROQ_MODELS[0]
    payload = {"categories": [{"category": "1", "confidence": 0.95}]}
    groq = _ModelAwareGroq({primary: _groq_response(payload)})
    gemini = _RecordingGemini(payload=payload)
    monkeypatch.setattr(cs, "client", groq)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", gemini)

    result = cs.GroqClassificationService()._predict_ranked_level(
        "I need help with math",
        ["1", "4"],
        accumulator=token_usage.new_accumulator(),
        depth=0,
    )

    assert result == [{"category": "1", "confidence": 0.95}]
    assert [call["model"] for call in groq.calls] == [primary]
    assert not gemini.calls


def test_all_groq_failures_reach_the_configured_gemini_model(monkeypatch):
    groq = _ModelAwareGroq(
        {
            model: GroqError(f"{model} unavailable")
            for model in _CONFIGURED_GROQ_MODELS
        }
    )
    payload = {"categories": [{"category": "1", "confidence": 0.88}]}
    gemini = _RecordingGemini(payload=payload)
    monkeypatch.setattr(cs, "client", groq)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", gemini)

    result = cs.GroqClassificationService()._predict_ranked_level(
        "I need help with math",
        ["1", "4"],
        accumulator=token_usage.new_accumulator(),
        depth=0,
    )

    assert result == [{"category": "1", "confidence": 0.88}]
    assert [call["model"] for call in groq.calls] == _CONFIGURED_GROQ_MODELS
    assert [call["model"] for call in gemini.calls] == [_CONFIGURED_GEMINI_MODEL]


def test_total_chain_failure_is_a_clear_502(monkeypatch):
    monkeypatch.setattr(
        LF,
        "predict_categories",
        lambda _description: (_ for _ in ()).throw(
            ModelChainExhausted(
                "predict_category failed: model chain exhausted after 4 attempts"
            )
        ),
    )

    response = LF.predict_category_handler(
        {"body": json.dumps({"description": "I need help with math"})},
        None,
    )

    assert response["statusCode"] == 502
    assert response["body"] == {
        "error": "Category prediction failed",
        "code": "CATEGORY_PREDICTION_UNAVAILABLE",
    }
