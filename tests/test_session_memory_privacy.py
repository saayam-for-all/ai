
"""Privacy and deletion regression tests for session memory."""

import pytest

from services.session_memory import update_session_memory
from services.sqlite_memory_store import (
    SQLiteMemoryStore,
    SessionDeleted,
)

pytestmark = pytest.mark.integration


def build_history(sensitive_text):
    """Build 25 synthetic messages, with a secret in expired history."""
    history = [
        {
            "role": "user",
            "content": (
                "I need transportation on Tuesdays. "
                + sensitive_text
            ),
        },
        {
            "role": "assistant",
            "content": "What arrival time would you prefer?",
        },
        {
            "role": "user",
            "content": "Before noon.",
        },
        {
            "role": "assistant",
            "content": "I can help document those requirements.",
        },
        {
            "role": "user",
            "content": "Please help me prepare the request.",
        },
    ]

    for i in range(19):
        history.append({
            "role": "assistant" if i % 2 == 0 else "user",
            "content": (
                "We can continue preparing the request."
                if i % 2 == 0
                else "Okay, please continue."
            ),
        })

    history.append({
        "role": "user",
        "content": "What transportation details did I mention?",
    })

    assert len(history) == 25
    return history


@pytest.mark.parametrize(
    "sensitive_text,secret",
    [
        (
            "My password is ExampleOnlyPass987!",
            "ExampleOnlyPass987!",
        ),
        (
            "My credit card number is 4111 1111 1111 1111.",
            "4111 1111 1111 1111",
        ),
    ],
    ids=["password", "payment-card"],
)
def test_secret_not_sent_to_summarizer(
    tmp_path, sensitive_text, secret
):
    """Sensitive values must not reach the memory summarizer."""
    store = SQLiteMemoryStore(tmp_path / "privacy.db")
    history = build_history(sensitive_text)

    captured_batches = []

    def fake_summarizer(previous_summary, messages):
        captured_batches.append(messages)
        return (
            "User needs transportation on Tuesdays "
            "and prefers arrival before noon."
        )

    memory, _ = update_session_memory(
        store,
        "privacy-session-001",
        history,
        fake_summarizer,
    )

    assert captured_batches, "Summarization was not triggered"

    summarized_input = " ".join(
        str(message)
        for batch in captured_batches
        for message in batch
    )

    assert secret not in summarized_input
    assert secret not in memory

    saved_state, _ = store.load("privacy-session-001")
    assert secret not in saved_state["memory"]


def test_sqlite_does_not_store_raw_transcript(tmp_path):
    """SQLite should persist summaries, not the original conversation."""
    db_path = tmp_path / "summary_only.db"
    store = SQLiteMemoryStore(db_path)

    history = build_history(
        "Synthetic private conversation marker XYZ789."
    )

    def fake_summarizer(previous_summary, messages):
        return "User needs transportation on Tuesdays."

    update_session_memory(
        store,
        "privacy-session-002",
        history,
        fake_summarizer,
    )

    saved_state, _ = store.load("privacy-session-002")

    assert saved_state["memory"] == (
        "User needs transportation on Tuesdays."
    )

    # Verify the original marker was not persisted in the DB file.
    database_content = db_path.read_bytes()

    assert b"XYZ789" not in database_content


def test_deleted_session_cannot_be_recreated(tmp_path):
    """An old transcript must not recreate a deleted session."""
    store = SQLiteMemoryStore(tmp_path / "deletion.db")

    history = build_history("No sensitive information.")

    def fake_summarizer(previous_summary, messages):
        return "User needs transportation on Tuesdays."

    update_session_memory(
        store,
        "privacy-session-003",
        history,
        fake_summarizer,
    )

    store.delete("privacy-session-003")

    with pytest.raises(SessionDeleted):
        store.load("privacy-session-003")

    with pytest.raises(SessionDeleted):
        update_session_memory(
            store,
            "privacy-session-003",
            history,
            fake_summarizer,
        )

    # A new chat is allowed to create its own independent memory.
    new_memory, _ = update_session_memory(
        store,
        "privacy-session-004",
        history,
        fake_summarizer,
    )

    assert "Tuesdays" in new_memory


def test_redaction_that_lengthens_summary_does_not_stick_session(tmp_path):
    """A summary inside the cap must not leave it once secrets are redacted."""
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    # 1999 chars: inside the cap until "pin is 1234" grows to
    # "[REDACTED SECRET]".
    proposed = "pin is 1234 " + "x" * 1987

    summary, _ = update_session_memory(
        store,
        "session-redact",
        build_history(""),
        lambda previous, batch: proposed,
    )

    assert len(summary) <= 2000
    assert "1234" not in summary
    assert "[REDACTED SECRET]" in summary

    state, _ = store.load("session-redact")
    assert state["memory"] == summary
    assert state["summarized_count"] > 0


def test_overlong_model_summary_is_capped_and_saved(tmp_path):
    """A 2100-char model summary is stored cut to the cap, so the cursor moves."""
    store = SQLiteMemoryStore(tmp_path / "memory.db")

    summary, _ = update_session_memory(
        store,
        "session-overlong",
        build_history(""),
        lambda previous, batch: "y" * 2100,
    )

    assert summary == "y" * 2000

    state, _ = store.load("session-overlong")
    assert state["memory"] == summary
    assert state["summarized_count"] > 0


@pytest.mark.parametrize(
    "text",
    [
        "the otp is valid until 5pm",
        "My PIN code is 560001, near MG Road",
        "Pincode: 560001",
        "Call me on +91 98765 43210",
    ],
)
def test_redaction_keeps_ordinary_prose_and_postal_codes(text):
    from services.memory_privacy import redact_sensitive

    assert redact_sensitive(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "otp is 482913",
        "OTP: 4829",
        "cvv=123",
        "pin is 1234",
        "one-time code: 991122",
    ],
)
def test_redaction_removes_numeric_codes(text):
    from services.memory_privacy import redact_sensitive

    redacted = redact_sensitive(text)

    assert "[REDACTED SECRET]" in redacted
    assert not any(ch.isdigit() for ch in redacted)


def test_bare_pin_label_is_redacted_even_when_it_may_be_a_postal_code():
    """A six-digit UPI PIN and a postal code look identical after "PIN:".

    Redaction errs toward privacy: the value is dropped and the rest of the
    sentence is kept. Users who write "PIN code" or "pincode" keep the value.
    """
    from services.memory_privacy import redact_sensitive

    assert redact_sensitive("My PIN: 560001, I live in Bangalore") == (
        "My [REDACTED SECRET], I live in Bangalore"
    )
