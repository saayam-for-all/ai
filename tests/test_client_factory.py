"""Unit tests for target-aware LangChain client construction."""

from types import SimpleNamespace

import pytest

import utils.client as client_module
from utils.model_fallback import ModelTarget, run_model_chain


pytestmark = pytest.mark.unit


def _recording_constructor(calls, result):
    def construct(**kwargs):
        calls.append(kwargs)
        return result

    return construct


def test_groq_factory_uses_the_target_model_temperature_and_credentials(monkeypatch):
    calls = []
    expected = object()
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(
        client_module,
        "ChatGroq",
        _recording_constructor(calls, expected),
    )
    target = ModelTarget(
        provider="groq",
        model="groq-secondary",
        reasoning_effort="low",
    )

    actual = client_module.create_chat_model(target, temperature=0.17)

    assert actual is expected
    assert calls == [
        {
            "api_key": "test-groq-key",
            "model": "groq-secondary",
            "temperature": 0.17,
            "reasoning_effort": "low",
        }
    ]


def test_groq_factory_omits_unconfigured_reasoning_effort(monkeypatch):
    calls = []
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(
        client_module,
        "ChatGroq",
        _recording_constructor(calls, object()),
    )

    client_module.create_chat_model(
        ModelTarget(provider="groq", model="groq-without-reasoning"),
        temperature=0.3,
    )

    assert "reasoning_effort" not in calls[0]


def test_gemini_factory_uses_the_target_model_temperature_and_credentials(monkeypatch):
    calls = []
    expected = object()
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(
        client_module,
        "ChatGoogleGenerativeAI",
        _recording_constructor(calls, expected),
    )
    target = ModelTarget(provider="gemini", model="gemini-final")

    actual = client_module.create_chat_model(target, temperature=0.42)

    assert actual is expected
    assert calls == [
        {
            "google_api_key": "test-gemini-key",
            "model": "gemini-final",
            "temperature": 0.42,
        }
    ]


@pytest.mark.parametrize(
    ("target", "key_name", "expected_message"),
    [
        (
            ModelTarget(provider="groq", model="groq-primary"),
            "GROQ_API_KEY",
            "Groq API key is not configured",
        ),
        (
            ModelTarget(provider="gemini", model="gemini-final"),
            "GEMINI_API_KEY",
            "Gemini API key is not configured",
        ),
    ],
)
def test_factory_rejects_a_target_whose_provider_has_no_key(
    monkeypatch, target, key_name, expected_message
):
    monkeypatch.setattr(client_module, key_name, None)

    with pytest.raises(ValueError, match=expected_message):
        client_module.create_chat_model(target, temperature=0.3)


def test_factory_rejects_an_unsupported_provider(monkeypatch):
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")
    target = ModelTarget(provider="meta", model="some-model")

    with pytest.raises(ValueError, match="Unsupported model provider: meta"):
        client_module.create_chat_model(target, temperature=0.3)


def test_constructor_failure_can_fall_through_to_another_provider(monkeypatch):
    attempts = []
    gemini_model = SimpleNamespace(provider="gemini")
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")

    def failing_groq(**_kwargs):
        raise TimeoutError("Groq client construction timed out")

    monkeypatch.setattr(client_module, "ChatGroq", failing_groq)
    monkeypatch.setattr(
        client_module,
        "ChatGoogleGenerativeAI",
        lambda **_kwargs: gemini_model,
    )
    targets = (
        ModelTarget(provider="groq", model="groq-primary"),
        ModelTarget(provider="gemini", model="gemini-final"),
    )

    def invoke(target):
        attempts.append((target.provider, target.model))
        return client_module.create_chat_model(target, temperature=0.3)

    result = run_model_chain(
        targets=targets,
        invoke=invoke,
        is_valid=bool,
        operation="construct-chat-model",
    )

    assert result is gemini_model
    assert attempts == [
        ("groq", "groq-primary"),
        ("gemini", "gemini-final"),
    ]
