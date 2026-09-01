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


#: Most recent turns of the client transcript that are forwarded to the model.
#: The More Information modal caps a person at five questions, so ten messages
#: covers a full session and leaves room for a client that counts differently.
#: Nothing enforces that cap on our side, and a transcript we do not bound is a
#: prompt we do not bound.
MAX_HISTORY_MESSAGES = 20

#: Longest single message forwarded. The modal enforces 250 characters in the
#: browser, which is a UI convenience and not a limit anyone else is held to.
MAX_MESSAGE_CHARS = 4000

#: Appended to the system prompt when the person has asked a follow-up. It
#: carries the request they are asking about without putting it in the position
#: the model treats as the question.
REQUEST_CONTEXT = """

---
The person you are helping raised this help request:
Subject: {subject}
Description: {description}

Use it as background for what they ask next. Answer the question in the final
message; do not restate or re-answer the request itself unless they ask you to.
"""

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
        """Turn the client's transcript into messages, dropping what is not one.

        The transcript arrives from a browser, so nothing about its shape is
        guaranteed: entries that are not objects, roles we do not accept, and
        missing or blank content are dropped rather than passed to the model.

        Only the most recent MAX_HISTORY_MESSAGES turns are kept. An unbounded
        transcript from a client is an unbounded prompt and an unbounded bill,
        and the oldest turns are the least useful ones to spend that on.
        """
        # A sequence, or nothing. The handler already drops a non-list, but
        # this is a public service method and the aggregator invokes the
        # package directly, so it cannot rely on a caller having checked. A
        # string or an int here used to raise TypeError from inside the loop.
        if not history or not isinstance(history, (list, tuple)):
            return []
        allowed = {"user", "assistant"}
        out: list[BaseMessage] = []
        for m in history:
            if not (isinstance(m, dict) and m.get("role") in allowed and "content" in m):
                continue
            role = str(m["role"])
            content = str(m["content"]).strip()[:MAX_MESSAGE_CHARS]
            if not content:
                continue
            if role == "user":
                out.append(HumanMessage(content=content))
            elif role == "assistant":
                out.append(AIMessage(content=content))
        return out[-MAX_HISTORY_MESSAGES:]

    @staticmethod
    def _split_trailing_question(
        messages: list[BaseMessage],
    ) -> tuple[list[BaseMessage], HumanMessage | None]:
        """Separate the newest user turn from the turns that came before it.

        The More Information chat appends the person's new question to
        `conversation_history` and sends nothing else, so from the second turn
        onwards the last entry *is* the question. Returning it separately is
        what lets it be asked as the question rather than replayed as history.

        A transcript ending in an assistant turn - a resumed session, a client
        that posts the reply back - has no pending question, and is answered
        exactly as a single-shot call is.
        """
        if messages and isinstance(messages[-1], HumanMessage):
            return messages[:-1], messages[-1]
        return messages, None

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

        prior, question = self._split_trailing_question(
            self._normalize_history(conversation_history)
        )

        if question is None:
            # Single shot: the description is the question, which is what this
            # endpoint was originally built for and what the aggregator's
            # direct invoke still sends. Unchanged, deliberately.
            messages: list[BaseMessage] = [
                SystemMessage(content=system_prompt),
                *prior,
                HumanMessage(content=f"Subject: {subject}\nQuestion: {description}"),
            ]
        else:
            # A follow-up. The last message is the one a model answers, so the
            # person's question has to be last - it used to sit one turn
            # upstream while the final turn replayed the original request
            # description, which meant every follow-up was answered as if they
            # had re-asked their original request (issue #183). The request
            # itself is still available to the model, as the background it is.
            messages = [
                SystemMessage(
                    content=system_prompt
                    + REQUEST_CONTEXT.format(
                        subject=subject or "(not given)",
                        description=description or "(not given)",
                    )
                ),
                *prior,
                question,
            ]

        return (
            self._try_groq(messages)
            or self._generate_with_gemini(messages)
        )
