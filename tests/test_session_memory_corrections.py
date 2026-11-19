
"""Regression tests for changing facts in session memory."""

import pytest

from services.sqlite_memory_store import SQLiteMemoryStore
from services.session_memory import update_session_memory

pytestmark = pytest.mark.integration


# The transcript builders live here rather than being imported from
# scripts/evaluate_memory_corrections.py, so this regression test does not
# depend on the evaluation tooling being committed.
def build_initial_history():
    """Create 25 messages, placing old facts outside the recent 20."""
    history = [
        {
            "role": "user",
            "content": "I need transportation every Friday.",
        },
        {
            "role": "assistant",
            "content": "What time must you arrive?",
        },
        {
            "role": "user",
            "content": "Before 8 AM.",
        },
        {
            "role": "assistant",
            "content": "Any accessibility requirements?",
        },
        {
            "role": "user",
            "content": "I need a wheelchair-accessible vehicle.",
        },
    ]

    for i in range(19):
        history.append({
            "role": "assistant" if i % 2 == 0 else "user",
            "content": (
                "I can help document the request."
                if i % 2 == 0
                else "Okay, please continue."
            ),
        })

    history.append({
        "role": "user",
        "content": "What were my transportation requirements?",
    })

    assert len(history) == 25
    return history


def append_correction(history):
    """Correct the original schedule without changing accessibility."""
    history.extend([
        {
            "role": "assistant",
            "content": "I can help update your requirements.",
        },
        {
            "role": "user",
            "content": (
                "Correction: My schedule has changed. "
                "I now need transportation every Monday, "
                "arriving before 10 AM. "
                "I still require a wheelchair-accessible vehicle. "
                "My previous schedule is outdated."
            ),
        },
        {
            "role": "assistant",
            "content": "Understood. I'll use your updated requirements.",
        },
        {
            "role": "user",
            "content": (
                "What are my CURRENT transportation requirements? "
                "State only the current schedule and accessibility needs."
            ),
        },
    ])

    assert len(history) == 29
    return history


def expire_correction(history):
    """Push the correction out of the latest 20 messages."""
    for i in range(23):
        history.append({
            "role": "assistant" if i % 2 == 0 else "user",
            "content": (
                "We can continue discussing the request."
                if i % 2 == 0
                else "Okay, continue."
            ),
        })

    history.append({
        "role": "user",
        "content": (
            "Remind me of my CURRENT transportation schedule "
            "and vehicle accessibility requirement. "
            "Do not use any outdated information."
        ),
    })

    assert len(history) == 53

    recent = " ".join(
        message["content"]
        for message in history[-20:]
    ).casefold()

    assert "monday" not in recent
    assert "10 am" not in recent
    assert "wheelchair" not in recent

    return history


def test_corrected_schedule_survives_expiration(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "corrections.db")
    session_id = "correction-session-001"

    summarizer_calls = []

    def fake_summarizer(previous_summary, messages):
        """Simulate summarization deterministically, without Groq."""
        summarizer_calls.append(messages)

        text = " ".join(
            message["content"] for message in messages
        ).lower()

        if "monday" in text:
            return (
                "Transportation every Monday before 10 AM. "
                "Wheelchair-accessible vehicle required."
            )

        if "friday" in text:
            return (
                "Transportation every Friday before 8 AM. "
                "Wheelchair-accessible vehicle required."
            )

        return previous_summary

    history = build_initial_history()

    # Phase 1: Initial requirements expire and enter SQLite.
    memory, _ = update_session_memory(
        store, session_id, history, fake_summarizer
    )

    assert "Friday" in memory
    assert "8 AM" in memory
    assert len(summarizer_calls) == 1

    # Phase 2: The correction is recent, so the stored summary
    # remains unchanged until those messages are summarized.
    append_correction(history)

    memory, _ = update_session_memory(
        store, session_id, history, fake_summarizer
    )

    assert "Friday" in memory
    assert "Monday" not in memory
    assert not any(
        "Correction:" in message["content"]
        for call in summarizer_calls
        for message in call
    )

    # Phase 3: After enough messages, the correction is
    # incorporated into persistent memory.
    expire_correction(history)

    # 24 messages arrived at once: a 5-batch backlog, more than one request
    # summarizes. The first request stops short of the correction and the
    # next one reaches it.
    memory, _ = update_session_memory(
        store, session_id, history, fake_summarizer
    )

    assert "Monday" not in memory

    memory, _ = update_session_memory(
        store, session_id, history, fake_summarizer
    )

    assert "Monday" in memory
    assert "10 AM" in memory
    assert "wheelchair" in memory.lower()
    assert "Friday" not in memory

    # Replaying the same transcript must not trigger more calls.
    call_count = len(summarizer_calls)

    repeated_memory, _ = update_session_memory(
        store, session_id, history, fake_summarizer
    )

    assert repeated_memory == memory
    assert len(summarizer_calls) == call_count

    # Confirm the corrected summary actually reached SQLite.
    saved_state, _ = store.load(session_id)
    assert saved_state["memory"] == memory
