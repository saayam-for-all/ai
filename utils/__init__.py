"""
Service module with abstraction layer for easy provider switching.
Python 3.14+ compatible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from typing import TypedDict, Literal

from utils.prompts import get_conversational_prompt
from utils.client import client, _use_groq, _gemini_client

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

    def _generate_with_gemini(self, messages: list[dict[str, str]]) -> str:
        """Fallback to Gemini API if Groq fails."""
        if not _gemini_client:
            raise ValueError("Gemini client not initialized")

        def as_line(m: dict[str, str]) -> str:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                prefix = "System"
            elif role == "user":
                prefix = "User"
            elif role == "assistant":
                prefix = "Assistant"
            else:
                prefix = role or "Message"
            return f"{prefix}: {content}"

        full_prompt = "\n".join(as_line(m) for m in messages)

        resp = _gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=full_prompt,
        )
        return (resp.text or "").strip()  # type: ignore

    def _try_groq(self, messages: list[dict[str, str]]) -> str | None:
        if not (_use_groq and client):
            return None
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
            content = (
                resp.choices[0].message.content
                if resp.choices and resp.choices[0].message
                else None
            )
            return content.strip() if content else None
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

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *self._normalize_history(conversation_history),
            {"role": "user", "content": f"Subject: {subject}\nQuestion: {description}"},
        ]

        return (
            self._try_groq(messages)
            or self._generate_with_gemini(messages)
        )