
"""Offline tests for the real memory summarization adapter."""

import pytest

from unittest.mock import Mock

from langchain_core.messages import AIMessage

from services import memory_summarizer

pytestmark = pytest.mark.unit


def test_summarizer_uses_conversation_facts(monkeypatch):
    """Verify that real conversation data reaches the model adapter."""
    model = Mock()
    model.invoke.return_value = AIMessage(
        content="User needs dialysis transportation three times weekly."
    )

    factory = Mock(return_value=model)

    monkeypatch.setattr(
        memory_summarizer, "create_chat_model", factory
    )

    expired = [
        {"role": "user", "content": "I need dialysis transportation."},
        {"role": "user", "content": "Three times per week."},
    ]

    result = memory_summarizer.summarize_memory("", expired)

    assert "dialysis transportation" in result
    assert model.invoke.call_count == 1

    sent_messages = model.invoke.call_args.args[0]

    assert "dialysis transportation" in sent_messages[1].content
    assert "Three times per week" in sent_messages[1].content


def test_summarizer_uses_existing_memory(monkeypatch):
    """Verify that prior memory is included in the next summary request."""
    model = Mock()
    model.invoke.return_value = AIMessage(
        content="Needs transport three times weekly before 8 AM."
    )

    monkeypatch.setattr(
        memory_summarizer,
        "create_chat_model",
        Mock(return_value=model),
    )

    previous = "Needs transport three times weekly."
    expired = [
        {"role": "user", "content": "I must arrive before 8 AM."}
    ]

    result = memory_summarizer.summarize_memory(
        previous, expired
    )

    assert "8 AM" in result

    sent_messages = model.invoke.call_args.args[0]
    assert previous in sent_messages[1].content


def test_empty_batch_does_not_call_model(monkeypatch):
    """An empty batch should preserve memory without model usage."""
    factory = Mock()

    monkeypatch.setattr(
        memory_summarizer, "create_chat_model", factory
    )

    result = memory_summarizer.summarize_memory(
        "Existing memory",
        [],
    )

    assert result == "Existing memory"
    factory.assert_not_called()


def test_groq_failure_falls_back_to_gemini(monkeypatch):
    """A Groq error should allow Gemini to produce the memory."""
    def fake_model_factory(target, *, temperature):
        model = Mock()

        if target.provider == "groq":
            model.invoke.side_effect = RuntimeError("Groq unavailable")
        else:
            model.invoke.return_value = AIMessage(
                content="User needs transportation assistance."
            )

        return model

    factory = Mock(side_effect=fake_model_factory)

    monkeypatch.setattr(
        memory_summarizer, "create_chat_model", factory
    )

    result = memory_summarizer.summarize_memory(
        "",
        [{"role": "user", "content": "I need a ride."}],
    )

    assert "transportation assistance" in result
    assert any(
        call.args[0].provider == "gemini"
        for call in factory.call_args_list
    )


def test_overlong_summary_is_returned_not_rejected(monkeypatch):
    """An overlong summary is capped by session_memory, not discarded here.

    Rejecting it exhausted the model chain, saved nothing and re-summarized
    the same batch on every later request.
    """
    model = Mock()
    model.invoke.return_value = AIMessage(content="x" * 2100)
    factory = Mock(return_value=model)

    monkeypatch.setattr(memory_summarizer, "create_chat_model", factory)

    result = memory_summarizer.summarize_memory(
        "", [{"role": "user", "content": "I need a ride."}]
    )

    assert len(result) == 2100
    # The first provider's answer was kept; no fallback was attempted.
    assert factory.call_count == 1
