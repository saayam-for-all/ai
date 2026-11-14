"""Unit tests for target-aware LangChain client construction."""

from types import SimpleNamespace

import pytest

import utils.client as client_module
from utils.model_fallback import ModelTarget, run_model_chain


pytestmark = pytest.mark.unit

def _set_keys(monkeypatch, groq=None, gemini=None):
    monkeypatch.setattr(client_module, "_load_keys", lambda: (groq, gemini))


def _recording_constructor(calls, result):
    def construct(**kwargs):
        calls.append(kwargs)
        return result

    return construct


def test_groq_factory_uses_the_target_model_temperature_and_credentials(monkeypatch):
    calls = []
    expected = object()
    _set_keys(monkeypatch, groq="test-groq-key")
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
    _set_keys(monkeypatch, groq="test-groq-key")
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
    _set_keys(monkeypatch, gemini="test-gemini-key")
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

def test_factory_reuses_cached_model_for_same_configuration(monkeypatch):
    calls = []
    expected = object()
    _set_keys(monkeypatch, groq="test-groq-key")
    monkeypatch.setattr(
        client_module,
        "ChatGroq",
        _recording_constructor(calls, expected),
    )
    target = ModelTarget(
        provider="groq",
        model="groq-primary",
        reasoning_effort="low",
    )

    first = client_module.create_chat_model(target, temperature=0.3)
    second = client_module.create_chat_model(target, temperature=0.3)

    assert first is second is expected
    assert len(calls) == 1


def test_factory_does_not_reuse_model_for_different_configuration(monkeypatch):
    calls = []

    def construct(**kwargs):
        model = object()
        calls.append((kwargs, model))
        return model

    _set_keys(monkeypatch, groq="test-groq-key")
    monkeypatch.setattr(client_module, "ChatGroq", construct)

    target = ModelTarget(
        provider="groq",
        model="groq-primary",
        reasoning_effort="low",
    )

    first = client_module.create_chat_model(target, temperature=0.3)
    same_config = client_module.create_chat_model(target, temperature=0.3)
    different_temperature = client_module.create_chat_model(
        target, temperature=0.4
    )

    assert first is same_config
    assert first is not different_temperature
    assert len(calls) == 2

@pytest.mark.parametrize(
    ("target", "keys", "expected_message"),
    [
        (
            ModelTarget(provider="groq", model="groq-primary"),
            (None, "test-gemini-key"),
            "Groq API key is not configured",
        ),
        (
            ModelTarget(provider="gemini", model="gemini-final"),
            ("test-groq-key", None),
            "Gemini API key is not configured",
        ),
    ],
)
def test_factory_rejects_a_target_whose_provider_has_no_key(
    monkeypatch, target, keys, expected_message
):
    monkeypatch.setattr(client_module, "_load_keys", lambda: keys)

    with pytest.raises(ValueError, match=expected_message):
        client_module.create_chat_model(target, temperature=0.3)


def test_factory_rejects_an_unsupported_provider(monkeypatch):
    _set_keys(monkeypatch, groq="test-groq-key", gemini="test-gemini-key")
    target = ModelTarget(provider="meta", model="some-model")

    with pytest.raises(ValueError, match="Unsupported model provider: meta"):
        client_module.create_chat_model(target, temperature=0.3)


def test_constructor_failure_can_fall_through_to_another_provider(monkeypatch):
    attempts = []
    gemini_model = SimpleNamespace(provider="gemini")
    _set_keys(monkeypatch, groq="test-groq-key", gemini="test-gemini-key")

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


def test_legacy_groq_defaults_include_low_reasoning_effort():
    assert client_module.GROQ_REASONING_EFFORT == "low"


def test_shared_groq_model_is_built_with_low_reasoning_effort(monkeypatch):
    """get_groq_llm serves subject generation; it must request low effort."""
    built = []
    _set_keys(monkeypatch, groq="test-groq-key")
    monkeypatch.setattr(
        client_module, "ChatGroq", _recording_constructor(built, object())
    )

    assert client_module.get_groq_llm() is not None
    assert built and built[0]["reasoning_effort"] == "low"


def test_accessors_reuse_one_client_per_container(monkeypatch):
    built = []
    _set_keys(monkeypatch, groq="test-groq-key", gemini="test-gemini-key")
    monkeypatch.setattr(
        client_module, "Groq", lambda api_key: built.append(("groq", api_key)) or object()
    )
    monkeypatch.setattr(
        client_module.genai,
        "Client",
        lambda api_key: built.append(("gemini", api_key)) or object(),
    )

    assert client_module.get_groq_client() is client_module.get_groq_client()
    assert client_module.get_gemini_client() is client_module.get_gemini_client()
    assert built == [("groq", "test-groq-key"), ("gemini", "test-gemini-key")]
