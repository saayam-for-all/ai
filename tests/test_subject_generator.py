"""
Unit tests for the Generate Subject service.

These tests mock the LLM entirely. They make NO network calls and do NOT touch
AWS SSM or any external model. Importing utils.subject_generator triggers the
SSM bootstrap in utils.client, which fails gracefully (no creds) and leaves the
LLM handles as None; the tests then inject a fake LLM in the module namespace.
"""

import pytest

# Subject generation from a request description.
pytestmark = pytest.mark.unit
import utils.subject_generator as sg


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """Stands in for a LangChain chat model: .invoke(prompt) -> obj with .content."""
    def __init__(self, content):
        self._content = content

    def invoke(self, _prompt):
        return _FakeMessage(self._content)


def _use_fake(monkeypatch, content):
    monkeypatch.setattr(sg, "groq_llm", _FakeLLM(content))
    monkeypatch.setattr(sg, "_use_groq", True)
    monkeypatch.setattr(sg, "gemini_llm", None)
    monkeypatch.setattr(sg, "_use_gemini", False)


# ---------- _clean_subject ----------

def test_clean_subject_strips_leading_label():
    assert sg._clean_subject("Subject: Roommate Wanted") == "Roommate Wanted"
    assert sg._clean_subject("Title - Toothache Relief") == "Toothache Relief"


def test_clean_subject_strips_surrounding_quotes():
    assert sg._clean_subject('"Ear Congestion and Ringing"') == "Ear Congestion and Ringing"
    assert sg._clean_subject("'General Checkup'") == "General Checkup"


def test_clean_subject_strips_label_and_quotes_together():
    assert sg._clean_subject('Subject: "Heart Concern"') == "Heart Concern"


def test_clean_subject_empty_falls_back():
    assert sg._clean_subject("") == "General Inquiry"
    assert sg._clean_subject("   ") == "General Inquiry"


# ---------- _truncate_with_word_boundary ----------

def test_truncate_enforces_max_length():
    out = sg._truncate_with_word_boundary("word " * 40, 70)
    assert len(out) <= 70


# ---------- generate_subject_from_description ----------

def test_generate_cleans_label_and_quotes(monkeypatch):
    _use_fake(monkeypatch, 'Subject: "Single Male Roommate for Rent"')
    result = sg.generate_subject_from_description("Looking for a roommate to share a room for rent.")
    assert result == "Single Male Roommate for Rent"


def test_generate_enforces_max_length(monkeypatch):
    _use_fake(monkeypatch, "This is an excessively long subject line " * 5)
    result = sg.generate_subject_from_description("Some description text here.", max_length=70)
    assert len(result) <= 70


def test_generate_empty_description_returns_fallback():
    assert sg.generate_subject_from_description("") == "General Inquiry"
    assert sg.generate_subject_from_description("   ") == "General Inquiry"


def test_generate_falls_back_to_description_when_no_llm(monkeypatch):
    monkeypatch.setattr(sg, "_use_groq", False)
    monkeypatch.setattr(sg, "groq_llm", None)
    monkeypatch.setattr(sg, "_use_gemini", False)
    monkeypatch.setattr(sg, "gemini_llm", None)
    desc = "I need help finding a food bank near me this week."
    result = sg.generate_subject_from_description(desc)
    assert result  # non-empty
    assert len(result) <= 70


# ---------- prompt guard ----------
# The tuned prompt lives on the deployed generate-subject branch. dev previously
# carried an older, generic version, so a merge in the wrong direction would
# silently undo the tuning while every other test still passed. These assertions
# fail loudly if that happens.

class _RecordingLLM:
    """Captures the prompt the service builds."""
    def __init__(self):
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return _FakeMessage("Recorded")


def _capture_prompt(monkeypatch, description="I need help with math"):
    recorder = _RecordingLLM()
    monkeypatch.setattr(sg, "groq_llm", recorder)
    monkeypatch.setattr(sg, "_use_groq", True)
    monkeypatch.setattr(sg, "gemini_llm", None)
    monkeypatch.setattr(sg, "_use_gemini", False)
    sg.generate_subject_from_description(description)
    assert recorder.prompt, "service did not build a prompt"
    return recorder.prompt


def test_prompt_keeps_concern_framing_rule(monkeypatch):
    # A subject must read as the person's own concern, not as a diagnosis.
    prompt = _capture_prompt(monkeypatch)
    assert "Heart Concern" in prompt
    assert "diagnosis" in prompt.lower()


def test_prompt_keeps_no_status_word_rule(monkeypatch):
    # Guards against subjects like "Knee Injury Physiotherapy Needed".
    prompt = _capture_prompt(monkeypatch)
    for word in ("Needed", "Required", "Seeking"):
        assert word in prompt, f"status word rule lost the {word!r} example"


def test_prompt_forbids_subject_label_in_output(monkeypatch):
    # The model must not prepend "Subject:"; _clean_subject is the safety net.
    prompt = _capture_prompt(monkeypatch)
    assert "Output ONLY the subject text" in prompt


def test_prompt_includes_the_description(monkeypatch):
    prompt = _capture_prompt(monkeypatch, "my roommate moved out suddenly")
    assert "my roommate moved out suddenly" in prompt
