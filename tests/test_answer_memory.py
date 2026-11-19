
"""Tests for memory-aware answer generation."""

from unittest.mock import Mock

import pytest

from utils import GroqAnswerGenerationService
from utils.generate_answer_service import generate_ai_answer

pytestmark = pytest.mark.unit


def make_service(monkeypatch):
    service = GroqAnswerGenerationService.__new__(
        GroqAnswerGenerationService
    )

    captured = {}

    def fake_model(target, messages, usage):
        captured["messages"] = messages
        return "Generated answer"

    monkeypatch.setattr(service, "_invoke_answer_target", fake_model)

    return service, captured


def test_memory_reaches_answer_prompt(monkeypatch):
    service, captured = make_service(monkeypatch)

    history = [
        {"role": "user", "content": "Can you help me?"},
        {"role": "assistant", "content": "Yes."},
        {"role": "user", "content": "What time should I leave?"},
    ]

    result = service.generate_answer(
        category="Transportation",
        subject="Medical transportation",
        description="Needs transportation",
        conversation_history=history,
        memory_context="Dialysis appointment is before 8 AM.",
    )

    messages = captured["messages"]

    assert result == "Generated answer"
    assert "Dialysis appointment" in messages[1].content
    assert messages[-1].content == "What time should I leave?"


def test_no_memory_preserves_existing_message_flow(monkeypatch):
    service, captured = make_service(monkeypatch)

    service.generate_answer(
        category="Transportation",
        subject="Medical transportation",
        description="I need a ride.",
    )

    messages = captured["messages"]

    assert len(messages) == 2
    assert messages[-1].content.endswith("I need a ride.")


def test_oversized_memory_is_rejected(monkeypatch):
    service, captured = make_service(monkeypatch)

    with pytest.raises(ValueError, match="size limit"):
        service.generate_answer(
            category="Transportation",
            subject="Medical transportation",
            description="I need a ride.",
            memory_context="x" * 2001,
        )

    assert "messages" not in captured


def test_wrapper_forwards_memory(monkeypatch):
    import utils.generate_answer_service as module

    fake_service = Mock()
    fake_service.generate_answer.return_value = "Answer"

    monkeypatch.setattr(
        module,
        "GroqAnswerGenerationService",
        Mock(return_value=fake_service),
    )

    result = generate_ai_answer(
        category="Transportation",
        subject="Medical transportation",
        description="I need a ride.",
        memory_context="Needs wheelchair-accessible transport.",
    )

    assert result == "Answer"
    assert fake_service.generate_answer.call_args.kwargs[
        "memory_context"
    ] == "Needs wheelchair-accessible transport."
