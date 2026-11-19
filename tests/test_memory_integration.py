
"""Offline integration test for SQLite-backed session memory."""

import pytest

from services.session_memory import update_session_memory
from services.sqlite_memory_store import SQLiteMemoryStore

pytestmark = pytest.mark.integration


def test_complete_memory_pipeline_across_requests(tmp_path):
    """Verify rolling summary persistence across multiple requests."""

    store = SQLiteMemoryStore(tmp_path / "integration.db")
    session_id = "integration-session-001"

    summarizer_calls = []

    def fake_summarizer(previous_summary, messages):
        summarizer_calls.append((previous_summary, messages))

        return (
            "User needs dialysis transportation "
            "three times weekly."
        )

    history = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": (
                "I need dialysis transportation three times weekly."
                if i == 0
                else f"message {i}"
            ),
        }
        for i in range(25)
    ]

    # First request: only three messages have expired.
    # The batch threshold has not been reached.
    memory, _ = update_session_memory(
        store,
        session_id,
        history[:20],
        fake_summarizer,
    )

    assert memory == ""
    assert len(summarizer_calls) == 0

    # Second request: five messages have expired,
    # triggering the first summary.
    memory, _ = update_session_memory(
        store,
        session_id,
        history,
        fake_summarizer,
    )

    assert "dialysis transportation" in memory
    assert len(summarizer_calls) == 1

    # Verify important early context reached summarization.
    previous_summary, expired_messages = summarizer_calls[0]

    assert previous_summary == ""
    assert any(
        "dialysis transportation" in message["content"]
        for message in expired_messages
    )

    # Verify the generated summary was stored in SQLite.
    saved_state, saved_version = store.load(session_id)

    assert saved_state["memory"] == memory

    # Third request: replaying the same history must not
    # trigger another summarization request.
    repeated_memory, _ = update_session_memory(
        store,
        session_id,
        history,
        fake_summarizer,
    )

    assert repeated_memory == memory
    assert len(summarizer_calls) == 1

    _, final_version = store.load(session_id)

    assert final_version == saved_version
