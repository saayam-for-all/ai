"""
Unit tests for the Generate Subject service.

These tests mock the LLM entirely — they make NO network calls and do NOT touch
AWS SSM or any external model. Importing utils.subject_generator triggers the
SSM bootstrap in utils.client, which fails gracefully (no creds) and leaves the
LLM handles as None; the tests then inject a fake LLM in the module namespace.
"""
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
