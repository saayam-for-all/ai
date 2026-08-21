"""
Guards the two failure modes behind "every request lands in General".

1. A retired Groq model (or any Groq API error) must NOT crash the request.
   Before this fix the except clause caught only json/Key/Type/Value errors, so a
   404 from a decommissioned model propagated out of predict_categories, the
   handler returned no categories, and the frontend fell back to General.
   Groq API errors must degrade to the Gemini fallback instead.

2. The Groq model must come from the single source of truth (utils.client.GROQ_MODEL)
   rather than a second hardcoded literal that can silently go stale.

No network calls and no API keys required: the Groq client is stubbed.
"""
import json

from groq import GroqError

import services.classification_service as cs
from utils.client import GROQ_MODEL


class _RaisingGroq:
    """Stub Groq client whose completion call always fails like a retired model."""

    def __init__(self, exc):
        self._exc = exc
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.last_kwargs = kwargs
                raise outer._exc

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()
        self.last_kwargs = None


def test_service_model_defaults_to_client_source_of_truth():
    service = cs.GroqClassificationService()
    assert service.model == GROQ_MODEL, (
        f"classifier model {service.model!r} drifted from utils.client.GROQ_MODEL "
        f"{GROQ_MODEL!r}; keep one source of truth"
    )


def test_gpt_oss_uses_low_reasoning_effort():
    # gpt-oss defaults to high reasoning effort, which starves the grammar-constrained
    # JSON output and returns empty content (Groq: json_validate_failed).
    service = cs.GroqClassificationService(model="openai/gpt-oss-20b")
    assert service._groq_extra_kwargs() == {"reasoning_effort": "low"}
    # Non gpt-oss models must not receive the parameter.
    assert cs.GroqClassificationService(model="some-other-model")._groq_extra_kwargs() == {}


def _assert_groq_error_falls_back(exc):
    """A Groq API error must be caught, not propagated, so Gemini can take over."""
    original_client, original_use_groq = cs.client, cs._use_groq
    stub = _RaisingGroq(exc)
    cs.client, cs._use_groq = stub, True

    fell_back = {"called": False}

    def _fake_gemini(prompt, candidates, accumulator, depth):
        fell_back["called"] = True
        return None

    original_gemini = cs.GroqClassificationService._predict_with_gemini_single
    cs.GroqClassificationService._predict_with_gemini_single = (
        lambda self, prompt, candidates, accumulator, depth: _fake_gemini(
            prompt, candidates, accumulator, depth
        )
    )
    try:
        service = cs.GroqClassificationService()
        accumulator = {
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "calls": [],
        }
        # Must not raise: the whole point of the fix.
        service._predict_one_level(
            "I need help with math", ["1", "4"], accumulator=accumulator, depth=0
        )
        assert fell_back["called"], "Groq failure did not reach the Gemini fallback"
    finally:
        cs.GroqClassificationService._predict_with_gemini_single = original_gemini
        cs.client, cs._use_groq = original_client, original_use_groq


def test_retired_model_error_does_not_crash_request():
    # What a decommissioned model actually raises (404 model_not_found).
    _assert_groq_error_falls_back(
        GroqError("Error code: 404 - model `llama-3.1-8b-instant` does not exist")
    )


def test_json_validate_failed_does_not_crash_request():
    # What a reasoning model raises when it starves the JSON grammar (400).
    _assert_groq_error_falls_back(GroqError("Error code: 400 - json_validate_failed"))


def test_parsing_errors_still_handled():
    # The pre-existing error classes must remain covered.
    _assert_groq_error_falls_back(json.JSONDecodeError("bad", "doc", 0))
    _assert_groq_error_falls_back(ValueError("Groq response content is empty"))


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
            passed += 1
    print(f"\n{passed}/{passed} passed")
