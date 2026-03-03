"""
LangChain model layer: Groq primary with Gemini fallback.
Used by the generate-answer flow only.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

load_dotenv()

# Template: system + conversation history + current user message (same structure as before).
CONVERSATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),
    MessagesPlaceholder("chat_history"),
    ("human", "{user_message}"),
])

_llm_with_fallback: Runnable | None = None

# Model config (aligned with previous GroqAnswerGenerationService)
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_TEMPERATURE = 0.7
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.7


def get_llm_with_fallback() -> Runnable:
    """Return a chat model runnable: Groq primary, Gemini fallback. Cached per process."""
    global _llm_with_fallback
    if _llm_with_fallback is not None:
        return _llm_with_fallback

    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()

    primary: Any = None
    fallback: Any = None

    if groq_key:
        try:
            from langchain_groq import ChatGroq
            primary = ChatGroq(
                api_key=groq_key,
                model=GROQ_MODEL,
                temperature=GROQ_TEMPERATURE,
            )
        except Exception:
            primary = None

    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            fallback = ChatGoogleGenerativeAI(
                api_key=gemini_key,
                model=GEMINI_MODEL,
                temperature=GEMINI_TEMPERATURE,
            )
        except Exception:
            fallback = None

    if primary is not None and fallback is not None:
        _llm_with_fallback = primary.with_fallbacks([fallback])
    elif primary is not None:
        _llm_with_fallback = primary
    elif fallback is not None:
        _llm_with_fallback = fallback
    else:
        raise ValueError(
            "At least one of GROQ_API_KEY or GEMINI_API_KEY (or GOOGLE_API_KEY) must be set."
        )

    return _llm_with_fallback


def _history_to_langchain_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    """Convert normalized conversation history (role/content dicts) to LangChain messages."""
    out: list[BaseMessage] = []
    for m in history:
        role = (m.get("role") or "").lower()
        content = str(m.get("content", ""))
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def build_conversation_messages(
    system_prompt: str,
    conversation_history: list[dict[str, str]],
    user_message: str,
) -> list[BaseMessage]:
    """
    Build the message list for the generate-answer chain: system + history + current user.
    Uses the same structure as the previous implementation; prompt text comes from
    get_conversational_prompt() in utils.prompts.
    """
    history_lc = _history_to_langchain_messages(conversation_history)
    prompt_value = CONVERSATION_PROMPT.invoke({
        "system_prompt": system_prompt,
        "chat_history": history_lc,
        "user_message": user_message,
    })
    return list(prompt_value.messages)
