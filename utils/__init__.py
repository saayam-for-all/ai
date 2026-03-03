"""
Service module with abstraction layer for easy provider switching.
Python 3.14+ compatible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from typing import TypedDict, Literal

from utils.langchain_models import build_conversation_messages, get_llm_with_fallback
from utils.prompts import get_conversational_prompt

class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str

class AnswerGenerationServiceInterface(ABC):
    """Abstract interface for answer generation services."""

    @abstractmethod
    def generate_answer(
        self,
        category: str,
        subject: str,
        description: str,
        location: str | None = None,
        gender: str | None = None,
        age: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate an answer string."""
        raise NotImplementedError

class GroqAnswerGenerationService(AnswerGenerationServiceInterface):
    """Groq implementation of answer generation service with Gemini fallback."""

    def __init__(
        self,
        model: str = "llama-3.1-8b-instant",
        temperature: float = 0.7,
        gemini_model: str = "gemini-2.5-flash",
    ):
        self.model = model
        self.temperature = temperature
        self.gemini_model = gemini_model

    @staticmethod
    def _normalize_history(
        history: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        if not history:
            return []
        allowed = {"user", "assistant"}
        return [
            {"role": str(m["role"]), "content": str(m["content"])}
            for m in history
            if isinstance(m, dict)
            and m.get("role") in allowed
            and "content" in m
        ]

    def generate_answer(
        self,
        category: str,
        subject: str,
        description: str,
        location: str | None = None,
        gender: str | None = None,
        age: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        system_prompt = get_conversational_prompt(
            category=category,
            subject=subject,
            location=location or "",
            gender=gender or "",
            age=age or "",
        )
        user_message = f"Subject: {subject}\nQuestion: {description}"
        normalized_history = self._normalize_history(conversation_history)
        messages = build_conversation_messages(
            system_prompt=system_prompt,
            conversation_history=normalized_history,
            user_message=user_message,
        )
        llm = get_llm_with_fallback()
        response = llm.invoke(messages)
        return (response.content or "").strip() if hasattr(response, "content") else str(response).strip()