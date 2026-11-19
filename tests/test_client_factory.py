"""Unit tests for target-aware LangChain client construction."""

from contextlib import contextmanager
from types import SimpleNamespace
import socket
import threading
import time

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

import utils.client as client_module
from utils.model_fallback import ModelTarget, _load_model_chain, run_model_chain


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_chat_model_cache():
    """lru_cache would otherwise return clients built before monkeypatches."""
    client_module.create_chat_model.cache_clear()
    yield
    client_module.create_chat_model.cache_clear()


def _recording_constructor(calls, result):
    def construct(**kwargs):
        calls.append(kwargs)
        return result

    return construct


@contextmanager
def _silent_http_server():
    """Accept TCP connections and never reply — no external network needed."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    held = []
    stop = threading.Event()

    def _accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(srv.accept())
            except socket.timeout:
                continue
            except OSError:
                break

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}"
    finally:
        stop.set()
        srv.close()
        for conn, _addr in held:
            try:
                conn.close()
            except OSError:
                pass
        thread.join(timeout=1)


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
            "request_timeout": client_module.DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS,
            "max_retries": client_module.DEFAULT_MODEL_MAX_RETRIES,
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
            "timeout": client_module.DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS,
            "max_retries": client_module.DEFAULT_MODEL_MAX_RETRIES,
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


def test_legacy_groq_defaults_include_low_reasoning_effort():
    assert client_module.GROQ_REASONING_EFFORT == "low"


def test_default_timeout_budget_fits_under_api_gateway_limit():
    """Configured chain × per-call limit (plus client overhead) stays under 29 s."""
    chain_length = len(_load_model_chain())
    # Silent-server checks on the pinned test versions showed timed-out calls
    # lasting ~0.6–1.2 s longer than the configured limit.
    per_call_ceiling = client_module.DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS + 1.2
    worst_case = (
        chain_length
        * per_call_ceiling
        * (1 + client_module.DEFAULT_MODEL_MAX_RETRIES)
    )
    assert client_module.DEFAULT_MODEL_MAX_RETRIES == 0
    assert worst_case < 29


def test_factory_passes_timeout_and_max_retries_to_both_providers(monkeypatch):
    groq_calls = []
    gemini_calls = []
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(
        client_module,
        "ChatGroq",
        _recording_constructor(groq_calls, object()),
    )
    monkeypatch.setattr(
        client_module,
        "ChatGoogleGenerativeAI",
        _recording_constructor(gemini_calls, object()),
    )

    client_module.create_chat_model(
        ModelTarget(provider="groq", model="groq-a"),
        temperature=0.1,
        timeout=3.5,
        max_retries=1,
    )
    client_module.create_chat_model(
        ModelTarget(provider="gemini", model="gemini-a"),
        temperature=0.1,
        timeout=3.5,
        max_retries=1,
    )

    assert groq_calls[0]["request_timeout"] == 3.5
    assert groq_calls[0]["max_retries"] == 1
    assert gemini_calls[0]["timeout"] == 3.5
    assert gemini_calls[0]["max_retries"] == 1


def test_different_timeout_limits_produce_different_cached_clients(monkeypatch):
    built = []

    class _DistinctClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            built.append(self)

    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(client_module, "ChatGroq", _DistinctClient)
    target = ModelTarget(provider="groq", model="groq-cache")

    first = client_module.create_chat_model(target, temperature=0.2, timeout=2.0)
    second = client_module.create_chat_model(target, temperature=0.2, timeout=2.0)
    third = client_module.create_chat_model(target, temperature=0.2, timeout=9.0)

    assert first is second
    assert first is not third
    assert len(built) == 2


def test_create_chat_model_groq_gives_up_on_a_silent_server(monkeypatch):
    """request_timeout from create_chat_model must make a hung Groq call raise."""
    with _silent_http_server() as base_url:
        RealChatGroq = ChatGroq

        def _chat_groq_at_silent_server(**kwargs):
            kwargs["base_url"] = base_url
            return RealChatGroq(**kwargs)

        monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
        monkeypatch.setattr(client_module, "ChatGroq", _chat_groq_at_silent_server)
        client_module.create_chat_model.cache_clear()

        model = client_module.create_chat_model(
            ModelTarget(provider="groq", model="groq-hang"),
            temperature=0.1,
            timeout=0.5,
            max_retries=0,
        )
        started = time.perf_counter()
        with pytest.raises(Exception):
            model.invoke("ping")
        assert time.perf_counter() - started < 3


def test_create_chat_model_gemini_gives_up_on_a_silent_server(monkeypatch):
    """timeout from create_chat_model must make a hung Gemini call raise."""
    with _silent_http_server() as base_url:
        RealGemini = ChatGoogleGenerativeAI

        def _gemini_at_silent_server(**kwargs):
            kwargs["base_url"] = base_url
            return RealGemini(**kwargs)

        monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")
        monkeypatch.setattr(
            client_module, "ChatGoogleGenerativeAI", _gemini_at_silent_server
        )
        client_module.create_chat_model.cache_clear()

        model = client_module.create_chat_model(
            ModelTarget(provider="gemini", model="gemini-hang"),
            temperature=0.1,
            timeout=0.5,
            max_retries=0,
        )
        started = time.perf_counter()
        with pytest.raises(Exception):
            model.invoke("ping")
        assert time.perf_counter() - started < 3


def test_timed_out_invoke_falls_through_to_the_next_target(monkeypatch):
    """A real timed-out Groq call must let run_model_chain try the next target."""
    attempts = []
    gemini_model = SimpleNamespace(name="gemini-ok")
    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(client_module, "GEMINI_API_KEY", "test-gemini-key")

    with _silent_http_server() as base_url:
        RealChatGroq = ChatGroq

        def _chat_groq_at_silent_server(**kwargs):
            kwargs["base_url"] = base_url
            return RealChatGroq(**kwargs)

        monkeypatch.setattr(client_module, "ChatGroq", _chat_groq_at_silent_server)
        monkeypatch.setattr(
            client_module,
            "ChatGoogleGenerativeAI",
            lambda **_kwargs: gemini_model,
        )
        client_module.create_chat_model.cache_clear()

        targets = (
            ModelTarget(provider="groq", model="groq-hang"),
            ModelTarget(provider="gemini", model="gemini-final"),
        )

        def invoke(target):
            attempts.append(target.provider)
            model = client_module.create_chat_model(
                target, temperature=0.3, timeout=0.5, max_retries=0
            )
            if hasattr(model, "invoke"):
                return model.invoke("ping")
            return model

        started = time.perf_counter()
        result = run_model_chain(
            targets=targets,
            invoke=invoke,
            is_valid=bool,
            operation="timeout-failover",
        )
        elapsed = time.perf_counter() - started

    assert result is gemini_model
    assert attempts == ["groq", "gemini"]
    assert elapsed < 3.0


class _FakeSSM:
    def get_parameters(self, Names, WithDecryption):
        return {"Parameters": [{"Name": n, "Value": "test-key"} for n in Names]}


def test_shared_groq_model_is_built_with_low_reasoning_effort(monkeypatch):
    """groq_llm serves subject and answer generation; it must request low effort."""
    import importlib
    import boto3
    import langchain_google_genai
    import langchain_groq

    built = []

    class _RecordingChatGroq:
        def __init__(self, **kwargs):
            built.append(kwargs)

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeSSM())
    monkeypatch.setattr(langchain_groq, "ChatGroq", _RecordingChatGroq)
    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", lambda **k: object())
    try:
        importlib.reload(client_module)
        assert built and built[0]["reasoning_effort"] == "low"
    finally:
        monkeypatch.undo()
        importlib.reload(client_module)


