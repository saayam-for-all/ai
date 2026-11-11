
"""Unit tests for lazy, target-aware LangChain client construction."""

import sys
import types
from types import SimpleNamespace

import pytest

import utils.client as client_module
from utils.model_fallback import ModelTarget, run_model_chain


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_model_cache():
    """Keep model-cache tests isolated from one another."""
    client_module._create_chat_model_cached.cache_clear()
    yield
    client_module._create_chat_model_cached.cache_clear()


@pytest.fixture
def configured_client(monkeypatch):
    """Provide configured credentials without making an AWS request."""
    monkeypatch.setattr(client_module, "_credentials_loaded", True)
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")

    monkeypatch.setattr(client_module, "client", None)
    monkeypatch.setattr(client_module, "_gemini_client", None)
    monkeypatch.setattr(client_module, "groq_llm", None)
    monkeypatch.setattr(client_module, "gemini_llm", None)

    monkeypatch.setattr(client_module, "_use_groq", False)
    monkeypatch.setattr(client_module, "_use_gemini", False)


def _recording_constructor(calls, result):
    def construct(**kwargs):
        calls.append(kwargs)
        return result

    return construct


def _provider_module(module_name, **attributes):
    """Create a fake provider module for testing lazy imports."""
    module = types.ModuleType(module_name)

    for name, value in attributes.items():
        setattr(module, name, value)

    return module


def test_groq_factory_uses_target_model_temperature_and_credentials(
    monkeypatch,
    configured_client,
):
    calls = []
    expected = object()

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        _provider_module(
            "langchain_groq",
            ChatGroq=_recording_constructor(calls, expected),
        ),
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


def test_groq_factory_omits_unconfigured_reasoning_effort(
    monkeypatch,
    configured_client,
):
    calls = []

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        _provider_module(
            "langchain_groq",
            ChatGroq=_recording_constructor(calls, object()),
        ),
    )

    client_module.create_chat_model(
        ModelTarget(
            provider="groq",
            model="groq-without-reasoning",
        ),
        temperature=0.3,
    )

    assert "reasoning_effort" not in calls[0]


def test_gemini_factory_uses_target_model_temperature_and_credentials(
    monkeypatch,
    configured_client,
):
    calls = []
    expected = object()

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        _provider_module(
            "langchain_google_genai",
            ChatGoogleGenerativeAI=_recording_constructor(
                calls,
                expected,
            ),
        ),
    )

    target = ModelTarget(
        provider="gemini",
        model="gemini-final",
    )

    actual = client_module.create_chat_model(target, temperature=0.42)

    assert actual is expected
    assert calls == [
        {
            "google_api_key": "test-gemini-key",
            "model": "gemini-final",
            "temperature": 0.42,
        }
    ]


def test_same_model_configuration_reuses_cached_instance(
    monkeypatch,
    configured_client,
):
    calls = []
    expected = object()

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        _provider_module(
            "langchain_groq",
            ChatGroq=_recording_constructor(calls, expected),
        ),
    )

    target = ModelTarget(
        provider="groq",
        model="groq-primary",
        reasoning_effort="low",
    )

    first = client_module.create_chat_model(target, temperature=0.3)
    second = client_module.create_chat_model(target, temperature=0.3)

    assert first is expected
    assert second is expected
    assert first is second
    assert len(calls) == 1


def test_different_model_configurations_use_separate_cache_entries(
    monkeypatch,
    configured_client,
):
    calls = []

    def construct(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        _provider_module(
            "langchain_groq",
            ChatGroq=construct,
        ),
    )

    first = client_module.create_chat_model(
        ModelTarget(
            provider="groq",
            model="groq-primary",
            reasoning_effort="low",
        ),
        temperature=0.3,
    )

    second = client_module.create_chat_model(
        ModelTarget(
            provider="groq",
            model="groq-secondary",
            reasoning_effort="low",
        ),
        temperature=0.3,
    )

    third = client_module.create_chat_model(
        ModelTarget(
            provider="groq",
            model="groq-primary",
            reasoning_effort="medium",
        ),
        temperature=0.5,
    )

    assert first is not second
    assert first is not third
    assert second is not third
    assert len(calls) == 3

    assert calls[0]["model"] == "groq-primary"
    assert calls[1]["model"] == "groq-secondary"
    assert calls[2]["model"] == "groq-primary"
    assert calls[2]["reasoning_effort"] == "medium"
    assert calls[2]["temperature"] == 0.5


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
    monkeypatch,
    configured_client,
    target,
    key_name,
    expected_message,
):
    monkeypatch.setattr(client_module, key_name, None)

    with pytest.raises(ValueError, match=expected_message):
        client_module.create_chat_model(target, temperature=0.3)


def test_factory_rejects_an_unsupported_provider(configured_client):
    target = ModelTarget(
        provider="meta",
        model="some-model",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported model provider: meta",
    ):
        client_module.create_chat_model(target, temperature=0.3)


def test_constructor_failure_can_fall_through_to_another_provider(
    monkeypatch,
    configured_client,
):
    attempts = []
    gemini_model = SimpleNamespace(provider="gemini")

    def failing_groq(**_kwargs):
        raise TimeoutError("Groq client construction timed out")

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        _provider_module(
            "langchain_groq",
            ChatGroq=failing_groq,
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        _provider_module(
            "langchain_google_genai",
            ChatGoogleGenerativeAI=lambda **_kwargs: gemini_model,
        ),
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


def test_credentials_are_loaded_lazily_and_only_once(monkeypatch):
    calls = []

    class FakeSSM:
        def get_parameters(self, Names, WithDecryption):
            calls.append((Names, WithDecryption))
            return {
                "Parameters": [
                    {"Name": name, "Value": f"secret-{index}"}
                    for index, name in enumerate(Names)
                ]
            }

    boto3_module = _provider_module(
        "boto3",
        client=lambda *args, **kwargs: FakeSSM(),
    )

    monkeypatch.setitem(sys.modules, "boto3", boto3_module)

    monkeypatch.setattr(client_module, "_credentials_loaded", False)
    monkeypatch.setattr(client_module, "GROQ_API_KEY", None)
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", None)

    assert calls == []

    client_module._load_api_keys()
    client_module._load_api_keys()

    assert len(calls) == 1
    assert calls[0][0] == [
        client_module.GROQ_PARAM,
        client_module.GEMINI_PARAM,
    ]
    assert calls[0][1] is True

    assert client_module.GROQ_API_KEY == "secret-0"
    assert client_module.GEMINI_API_KEY == "secret-1"


def test_groq_raw_sdk_client_is_initialized_lazily_and_reused(
    monkeypatch,
    configured_client,
):
    calls = []
    expected = object()

    monkeypatch.setitem(
        sys.modules,
        "groq",
        _provider_module(
            "groq",
            Groq=_recording_constructor(calls, expected),
        ),
    )

    assert client_module.client is None

    first = client_module.get_groq_client()
    second = client_module.get_groq_client()

    assert first is expected
    assert second is expected
    assert len(calls) == 1
    assert calls[0] == {"api_key": "test-groq-key"}
    assert client_module._use_groq is True


def test_gemini_raw_sdk_client_is_initialized_lazily_and_reused(
    monkeypatch,
    configured_client,
):
    calls = []
    expected = object()

    class FakeGenAI:
        @staticmethod
        def Client(**kwargs):
            calls.append(kwargs)
            return expected

    monkeypatch.setitem(
        sys.modules,
        "google",
        _provider_module(
            "google",
            genai=FakeGenAI,
        ),
    )

    assert client_module._gemini_client is None

    first = client_module.get_gemini_client()
    second = client_module.get_gemini_client()

    assert first is expected
    assert second is expected
    assert len(calls) == 1
    assert calls[0] == {"api_key": "test-gemini-key"}
    assert client_module._use_gemini is True


def test_shared_groq_model_is_built_with_low_reasoning_effort(
    monkeypatch,
    configured_client,
):
    """The shared Groq model must request low reasoning effort."""
    built = []

    class RecordingChatGroq:
        def __init__(self, **kwargs):
            built.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        _provider_module(
            "langchain_groq",
            ChatGroq=RecordingChatGroq,
        ),
    )

    first = client_module.get_groq_llm()
    second = client_module.get_groq_llm()

    assert first is second
    assert len(built) == 1
    assert built[0]["reasoning_effort"] == "low"
    assert built[0]["model"] == client_module.GROQ_MODEL
    assert client_module._use_groq is True


def test_legacy_groq_defaults_include_low_reasoning_effort():
    assert client_module.GROQ_REASONING_EFFORT == "low"
