"""
Service module with abstraction layer for easy provider switching.
Python 3.14+ compatible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from typing import TypedDict, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from utils.client import (
    GROQ_MODEL,
    GROQ_TEMPERATURE,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    groq_llm,
    gemini_llm,
)
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
        model: str = GROQ_MODEL,
        temperature: float = GROQ_TEMPERATURE,
        gemini_model: str = GEMINI_MODEL,
    ):
        self.model = model
        self.temperature = temperature
        self.gemini_model = gemini_model
        self.gemini_temperature = GEMINI_TEMPERATURE

    @staticmethod
    def _normalize_history(
        history: list[dict[str, str]] | None,
    ) -> list[BaseMessage]:
        if not history:
            return []
        allowed = {"user", "assistant"}
        out: list[BaseMessage] = []
        for m in history:
            if not (isinstance(m, dict) and m.get("role") in allowed and "content" in m):
                continue
            role = str(m["role"])
            content = str(m["content"])
            if role == "user":
                out.append(HumanMessage(content=content))
            elif role == "assistant":
                out.append(AIMessage(content=content))
        return out

    def _generate_with_gemini(self, messages: list[BaseMessage]) -> str:
        """Fallback to Gemini API if Groq fails."""
        if not gemini_llm:
            raise ValueError("Gemini client not initialized")
        resp = gemini_llm.invoke(messages)
        content = resp.content if hasattr(resp, "content") else str(resp)
        return (content or "").strip()

    def _try_groq(self, messages: list[BaseMessage]) -> str | None:
        if not groq_llm:
            return None
        try:
            resp = groq_llm.invoke(messages)
            content = resp.content if hasattr(resp, "content") else str(resp)
            return (content or "").strip() or None
        except Exception:
            return None

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

        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            *self._normalize_history(conversation_history),
            HumanMessage(content=f"Subject: {subject}\nQuestion: {description}"),
        ]

        return (
            self._try_groq(messages)
            or self._generate_with_gemini(messages)
        )
