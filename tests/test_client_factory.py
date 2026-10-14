"""Unit tests for target-aware LangChain client construction."""

from types import SimpleNamespace
import runpy

import httpx
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
            "timeout": 4.0,
            "max_retries": 0,
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
            "timeout": 4.0,
            "max_retries": 1,
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


@pytest.mark.integration
@pytest.mark.parametrize("provider", ["groq", "gemini"])
@pytest.mark.parametrize("client_kind", ["raw", "langchain"])
@pytest.mark.parametrize("failure", ["rate_limit", "timeout"])
def test_clients_send_one_bounded_request(monkeypatch, provider, client_kind, failure):
    """Exercise real SDK retry logic with a fake transport, without API keys/I/O."""
    monkeypatch.setattr(
        client_module.boto3,
        "client",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_parameters=lambda **_kwargs: {
                "Parameters": [
                    {"Name": client_module.GROQ_PARAM, "Value": "test-groq-key"},
                    {"Name": client_module.GEMINI_PARAM, "Value": "test-gemini-key"},
                ]
            }
        ),
    )
    # Isolate bootstrap from the already-imported module used by other tests.
    clients = runpy.run_path(client_module.__file__)
    requests = []

    def send(_self, request, **_kwargs):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("provider timed out", request=request)
        return httpx.Response(
            429,
            request=request,
            headers={"retry-after": "60"},
            json={"error": {"code": 429, "message": "rate limited"}},
        )

    monkeypatch.setattr(httpx.Client, "send", send)
    if client_kind == "langchain":
        llm = clients["create_chat_model"](
            ModelTarget(provider=provider, model=(
                "openai/gpt-oss-20b" if provider == "groq" else "gemini-2.5-flash"
            )),
            temperature=0.3,
        )
        invoke = lambda: llm.invoke("test prompt")
    elif provider == "groq":
        invoke = lambda: clients["client"].chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": "test prompt"}],
        )
    else:
        invoke = lambda: clients["_gemini_client"].models.generate_content(
            model="gemini-2.5-flash", contents="test prompt"
        )

    with pytest.raises(Exception):
        invoke()

    assert len(requests) == 1, "the SDK must leave retrying to the fallback chain"
    assert requests[0].extensions["timeout"] == {
        "connect": 4.0, "read": 4.0, "write": 4.0, "pool": 4.0,
    }
