"""Provider keys load from SSM on first use, not at import (#237).
Successful reads are cached; failed reads back off, then retry."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import utils.client as client_module


pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent


_COLD_START_SCRIPT = textwrap.dedent(
    """
    import json, sys, urllib.request
    import boto3

    created = []

    class _Stub:
        def get_parameters(self, **kwargs):
            return {"Parameters": []}

    def _client(service_name, *args, **kwargs):
        created.append(service_name)
        return _Stub()

    def _no_network(*args, **kwargs):
        raise AssertionError("cold-start check opened a URL")

    boto3.client = _client
    urllib.request.urlopen = _no_network

    import lambda_function as LF
    after_import = list(created)
    response = LF.emergency_contacts_handler(
        {"queryStringParameters": {"country": "IN"},
         "requestContext": {"identity": {"sourceIp": "8.8.8.8"}}},
        None,
    )
    print(json.dumps({
        "after_import": after_import,
        "after_handler": created,
        "status": response["statusCode"],
    }))
    """
)


@pytest.mark.integration
def test_cold_start_and_emergency_contacts_never_create_an_ssm_client():
    # Subprocess: conftest has already imported lambda_function in this one.
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("EMERGENCY_NUMBERS_")
    }
    result = subprocess.run(
        [sys.executable, "-c", _COLD_START_SCRIPT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    assert "ssm" not in report["after_import"], "SSM client created at import"
    assert "ssm" not in report["after_handler"], "SSM client created by Emergency Contacts"
    assert report["status"] == 200


def test_emergency_contacts_does_not_load_provider_keys(handlers, monkeypatch):
    calls = []
    monkeypatch.setattr(client_module, "_load_keys", lambda: calls.append(1))

    response = handlers.emergency_contacts_handler(
        {"queryStringParameters": {"country": "IN"},
         "requestContext": {"identity": {"sourceIp": "8.8.8.8"}}},
        None,
    )

    assert response["statusCode"] == 200
    assert calls == []


class _FakeSSM:
    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def get_parameters(self, Names, WithDecryption):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return {
            "Parameters": [
                {"Name": name, "Value": value}
                for name, value in outcome.items()
                if name in Names
            ]
        }


def _install_ssm(monkeypatch, fake):
    monkeypatch.setattr(
        client_module,
        "boto3",
        type("FakeBoto3", (), {"client": staticmethod(lambda *a, **k: fake)}),
    )


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(client_module, "time", fake)
    return fake


_BACKOFF = client_module.FAILURE_BACKOFF_SECONDS

_BOTH_KEYS = {
    client_module.GROQ_PARAM: "groq-key",
    client_module.GEMINI_PARAM: "gemini-key",
}

_ACCESS_DENIED = ClientError(
    {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
    "GetParameters",
)


def test_a_successful_read_is_cached(monkeypatch):
    fake = _FakeSSM(_BOTH_KEYS)
    _install_ssm(monkeypatch, fake)

    assert client_module._load_keys() == ("groq-key", "gemini-key")
    assert client_module._load_keys() == ("groq-key", "gemini-key")
    assert fake.calls == 1


def test_parameter_not_found_is_a_successful_read_and_is_cached(monkeypatch):
    fake = _FakeSSM({})
    _install_ssm(monkeypatch, fake)

    assert client_module._load_keys() == (None, None)
    assert client_module._load_keys() == (None, None)
    assert fake.calls == 1


@pytest.mark.parametrize(
    "failure",
    [_ACCESS_DENIED, TimeoutError("ssm timed out")],
    ids=["client-error", "unexpected-error"],
)
def test_a_failed_read_is_not_cached_and_the_next_call_retries(
    monkeypatch, clock, failure
):
    fake = _FakeSSM(failure, _BOTH_KEYS)
    _install_ssm(monkeypatch, fake)

    assert client_module._load_keys() == (None, None)
    clock.advance(_BACKOFF)
    assert client_module._load_keys() == ("groq-key", "gemini-key")
    assert fake.calls == 2


def test_calls_inside_the_backoff_window_do_not_call_ssm(monkeypatch, clock):
    fake = _FakeSSM(_ACCESS_DENIED)
    _install_ssm(monkeypatch, fake)

    assert client_module._load_keys() == (None, None)
    for _ in range(5):
        clock.advance((_BACKOFF - 1) / 5)
        assert client_module._load_keys() == (None, None)
        assert client_module.get_groq_client() is None
        assert client_module.get_groq_llm() is None

    assert fake.calls == 1


def test_a_retry_that_fails_again_starts_a_new_window(monkeypatch, clock):
    fake = _FakeSSM(_ACCESS_DENIED, _ACCESS_DENIED, _BOTH_KEYS)
    _install_ssm(monkeypatch, fake)

    client_module._load_keys()
    clock.advance(_BACKOFF)
    assert client_module._load_keys() == (None, None)
    clock.advance(_BACKOFF - 1)
    assert client_module._load_keys() == (None, None)
    assert fake.calls == 2
    clock.advance(1)
    assert client_module._load_keys() == ("groq-key", "gemini-key")
    assert fake.calls == 3


def test_ssm_client_is_created_with_short_timeouts(monkeypatch):
    created = []

    def _client(service_name, **kwargs):
        created.append((service_name, kwargs))
        return _FakeSSM({})

    monkeypatch.setattr(
        client_module, "boto3", type("RecordingBoto3", (), {"client": staticmethod(_client)})
    )

    client_module._load_keys()

    ((service_name, kwargs),) = created
    config = kwargs["config"]
    assert service_name == "ssm"
    assert config.connect_timeout == 2
    assert config.read_timeout == 2
    assert config.retries == {"mode": "standard", "total_max_attempts": 2}


def test_accessors_recover_once_keys_become_available(monkeypatch, clock):
    fake = _FakeSSM(_ACCESS_DENIED, _BOTH_KEYS)
    _install_ssm(monkeypatch, fake)
    built = []
    monkeypatch.setattr(
        client_module, "Groq", lambda api_key: built.append(api_key) or object()
    )

    assert client_module.get_groq_client() is None
    clock.advance(_BACKOFF)
    first = client_module.get_groq_client()
    second = client_module.get_groq_client()

    assert first is not None and first is second
    assert built == ["groq-key"]


def test_key_found_lines_are_printed_once_per_container(monkeypatch, capsys):
    _install_ssm(monkeypatch, _FakeSSM({client_module.GROQ_PARAM: "groq-key"}))

    client_module._load_keys()
    client_module._load_keys()

    out = capsys.readouterr().out
    assert out.count("INIT LOG: Groq Key Found: True") == 1
    assert out.count("INIT LOG: Gemini Key Found: False") == 1


def test_accessors_return_none_without_keys(monkeypatch):
    monkeypatch.setattr(client_module, "_load_keys", lambda: (None, None))

    assert client_module.get_groq_client() is None
    assert client_module.get_gemini_client() is None
    assert client_module.get_groq_llm() is None
    assert client_module.get_gemini_llm() is None
    assert client_module.has_groq() is False


def test_accessor_swallows_a_constructor_failure(monkeypatch):
    monkeypatch.setattr(client_module, "_load_keys", lambda: ("groq-key", None))

    def broken(**_kwargs):
        raise RuntimeError("bad SDK")

    monkeypatch.setattr(client_module, "Groq", broken)

    assert client_module.get_groq_client() is None


def test_gemini_client_accessor_swallows_a_constructor_failure(monkeypatch):
    monkeypatch.setattr(client_module, "_load_keys", lambda: (None, "gemini-key"))

    def broken(**_kwargs):
        raise RuntimeError("bad SDK")

    monkeypatch.setattr(client_module.genai, "Client", broken)

    assert client_module.get_gemini_client() is None


def test_groq_llm_accessor_swallows_a_constructor_failure(monkeypatch):
    monkeypatch.setattr(client_module, "_load_keys", lambda: ("groq-key", None))

    def broken(**_kwargs):
        raise RuntimeError("bad SDK")

    monkeypatch.setattr(client_module, "ChatGroq", broken)

    assert client_module.get_groq_llm() is None


def test_gemini_llm_accessor_swallows_a_constructor_failure(monkeypatch):
    monkeypatch.setattr(client_module, "_load_keys", lambda: (None, "gemini-key"))

    def broken(**_kwargs):
        raise RuntimeError("bad SDK")

    monkeypatch.setattr(client_module, "ChatGoogleGenerativeAI", broken)

    assert client_module.get_gemini_llm() is None
