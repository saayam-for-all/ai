"""Provider key names come from settings, so the test function can use its own key (#252).

The deployed functions keep the default Parameter Store names. The test function
points GROQ_PARAM_NAME at a test-only key and sets GEMINI_PARAM_NAME to an empty
string. It must then ask Parameter Store for the Groq key alone, because a single
name its role cannot read would fail the whole request.
"""
import pytest

import utils.client as client_module

# Which Parameter Store names the key loader asks for, per setting.
pytestmark = pytest.mark.unit

LIVE_GROQ = "/dev/saayam/GenAI/groq/key"
LIVE_GEMINI = "/dev/saayam/GenAI/gemini/key"
TEST_GROQ = "/dev/saayam/GenAI/test/groq/key"


class _RecordingSSM:
    def __init__(self, calls):
        self.calls = calls

    def get_parameters(self, Names, WithDecryption):
        self.calls.append(list(Names))
        return {"Parameters": [{"Name": n, "Value": f"key-for-{n}"} for n in Names]}


@pytest.fixture
def load_keys(monkeypatch):
    """Load the keys under the given names with a recording Parameter Store."""
    calls = []

    def _load(**settings):
        for name in ("GROQ_PARAM_NAME", "GEMINI_PARAM_NAME"):
            monkeypatch.delenv(name, raising=False)
        for name, value in settings.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(
            client_module,
            "boto3",
            type("RecordingBoto3", (), {"client": staticmethod(lambda *a, **k: _RecordingSSM(calls))}),
        )
        return client_module._load_keys(), calls

    return _load


def test_the_deployed_functions_keep_the_default_names(load_keys):
    keys, calls = load_keys()
    assert calls == [[LIVE_GROQ, LIVE_GEMINI]]
    assert keys == (f"key-for-{LIVE_GROQ}", f"key-for-{LIVE_GEMINI}")


def test_the_test_function_asks_only_for_its_own_groq_key(load_keys):
    keys, calls = load_keys(GROQ_PARAM_NAME=TEST_GROQ, GEMINI_PARAM_NAME="")
    assert calls == [[TEST_GROQ]]
    assert keys == (f"key-for-{TEST_GROQ}", None)


def test_no_names_means_no_request_and_no_keys(load_keys):
    keys, calls = load_keys(GROQ_PARAM_NAME="", GEMINI_PARAM_NAME="")
    assert calls == []
    assert keys == (None, None)
