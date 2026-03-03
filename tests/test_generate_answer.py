"""
Tests for the generate-answer flow (LangChain refactor).
Run with: pytest tests/ -v
No API keys required; LLM is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import utils  # for patch.object(utils, "get_llm_with_fallback", ...)
from utils.generate_answer_service import generate_ai_answer
from utils.langchain_models import build_conversation_messages
from utils.prompts import get_conversational_prompt


# --- Unit tests: message building and prompt structure (no LLM) ---


def test_build_conversation_messages_no_history():
    """Message list has system + single user message when history is empty."""
    system_prompt = get_conversational_prompt(
        category="General",
        subject="Food help",
        location="",
        gender="",
        age="",
    )
    messages = build_conversation_messages(
        system_prompt=system_prompt,
        conversation_history=[],
        user_message="Subject: Food help\nQuestion: Where can I get groceries?",
    )
    assert len(messages) >= 2
    assert messages[0].type == "system"
    assert "Food help" in (messages[0].content if hasattr(messages[0], "content") else str(messages[0]))
    # Last message is human
    last = messages[-1]
    assert last.type == "human"
    assert "Subject: Food help" in (last.content if hasattr(last, "content") else str(last))
    assert "Where can I get groceries" in (last.content if hasattr(last, "content") else str(last))


def test_build_conversation_messages_with_history():
    """Conversation history is included in the message list."""
    system_prompt = get_conversational_prompt(
        category="General",
        subject="Test",
        location="",
        gender="",
        age="",
    )
    history = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
    ]
    messages = build_conversation_messages(
        system_prompt=system_prompt,
        conversation_history=history,
        user_message="Subject: Test\nQuestion: Follow-up?",
    )
    # system + 2 history + 1 current user = 4
    assert len(messages) == 4
    assert messages[1].type == "human"
    assert messages[2].type == "ai"
    assert "Follow-up" in (messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1]))


def test_get_conversational_prompt_uses_category():
    """Category-specific prompt text is present for a known category."""
    prompt = get_conversational_prompt(
        category="FOOD_ASSISTANCE",
        subject="Food",
        location="NYC",
        gender="",
        age="",
    )
    assert "food" in prompt.lower() or "Food" in prompt
    assert "NYC" in prompt or "location" in prompt.lower()


# --- Integration-style test with mocked LLM (no API keys) ---


def test_generate_ai_answer_returns_llm_response():
    """generate_ai_answer returns the string from the LLM when LLM is mocked."""
    mock_response = MagicMock()
    mock_response.content = "Here is a helpful answer."
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    # Patch in the module where generate_answer is defined (utils), so the method sees the mock.
    with patch.object(utils, "get_llm_with_fallback", return_value=mock_llm):
        result = generate_ai_answer(
            category="General",
            subject="Test",
            description="What is 2+2?",
            location=None,
            gender=None,
            age=None,
            conversation_history=None,
        )

    assert result == "Here is a helpful answer."
    mock_llm.invoke.assert_called_once()
    # Invoke was called with a list of messages (system + user at least)
    call_args = mock_llm.invoke.call_args[0][0]
    assert len(call_args) >= 2
