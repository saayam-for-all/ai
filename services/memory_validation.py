
"""Validate client conversation history before memory processing."""

from utils import MAX_MESSAGE_CHARS

MAX_INPUT_MESSAGES = 500
ALLOWED_ROLES = {"user", "assistant"}


class InvalidMemoryRequest(ValueError):
    """The history is malformed, not merely unusable for memory; a 400.

    Other ValueErrors - a misconfigured model route, a missing provider key,
    an oversized transcript - cost the answer its memory, not the answer.
    """


def normalize_memory_history(history):
    """Return valid, bounded messages without truncating old history."""
    if not isinstance(history, list):
        raise InvalidMemoryRequest("Conversation history must be a list")

    # Not InvalidMemoryRequest: every later turn of the chat is longer still,
    # so refusing here refused that session an answer for good.
    if len(history) > MAX_INPUT_MESSAGES:
        raise ValueError("Conversation history exceeds input limit")

    normalized = []

    for message in history:
        if not isinstance(message, dict):
            continue

        role = message.get("role")

        if role not in ALLOWED_ROLES:
            continue

        if "content" not in message:
            continue

        # Same rule as GroqAnswerGenerationService._normalize_history: the
        # summary window is computed from this list, so a message counted
        # there and dropped here shifts the window and loses a turn.
        content = str(message["content"]).strip()[:MAX_MESSAGE_CHARS]

        if not content:
            continue

        normalized.append({
            "role": role,
            "content": content,
        })

    return normalized
