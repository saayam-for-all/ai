"""Offline tests of SQLite-backed, session-scoped summarized memory."""

import sqlite3
from unittest.mock import Mock

import pytest

from services.memory_store import VersionConflict
from services.session_memory import update_session_memory
from services.sqlite_memory_store import SQLiteMemoryStore, SessionDeleted

pytestmark = pytest.mark.integration


def history(n):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(n)
    ]


def test_summary_is_durable_but_raw_turns_are_not(tmp_path):
    path = tmp_path / "session.db"
    store = SQLiteMemoryStore(path)
    summarizer = Mock(return_value="Need a ride on Fridays")
    messages = history(25)
    messages[0]["content"] = "Private old turn about transport"

    summary, active = update_session_memory(store, "session-a", messages, summarizer)
    assert summary == "Need a ride on Fridays"
    assert active == messages[5:]
    summarizer.assert_called_once_with("", messages[:5])

    reloaded = SQLiteMemoryStore(path)
    saved, version = reloaded.load("session-a")
    assert version == 1
    assert saved["memory"] == summary
    assert saved["summarized_count"] == 5
    assert "pending" not in saved and "recent" not in saved
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_memory)")}
        assert "recent" not in columns and "pending" not in columns
        rows = conn.execute("SELECT memory FROM session_memory").fetchall()
        assert all("Private old turn" not in row[0] for row in rows)

    update_session_memory(reloaded, "session-a", messages, summarizer)
    assert summarizer.call_count == 1
    assert reloaded.load("session-a")[1] == 1


@pytest.mark.parametrize("n", range(21, 31))
def test_every_turn_is_in_the_summary_or_the_prompt_window(tmp_path, n):
    from utils import GroqAnswerGenerationService

    store = SQLiteMemoryStore(tmp_path / "coverage.db")
    summarized = []

    def summarizer(previous, batch):
        summarized.extend(m["content"] for m in batch)
        return "summary"

    messages = history(n)
    _, active = update_session_memory(store, "s1", messages, summarizer)
    window = [
        m.content for m in GroqAnswerGenerationService._normalize_history(messages)
    ]

    assert {m["content"] for m in messages} <= set(summarized) | set(window)
    assert len(active) <= 20


def test_new_session_starts_empty_and_delete_is_scoped(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "sessions.db")
    summarize = Mock(return_value="Session A insight")
    update_session_memory(store, "session-a", history(25), summarize)

    other_summary, _ = update_session_memory(store, "session-b", history(2), summarize)
    assert other_summary == ""
    assert store.load("session-b") == ({}, 0)

    store.delete("session-a")
    with pytest.raises(SessionDeleted):
        store.load("session-a")


def test_redact_secrets_before_summarizer_and_db_write(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "secrets.db")
    messages = history(25)
    messages[0]["content"] = "password: hunter2 card 4111 1111 1111 1111"
    summarizer = Mock(return_value="password: hunter2 and 4111 1111 1111 1111")

    summary, active = update_session_memory(store, "s1", messages, summarizer)
    batch = summarizer.call_args.args[1]
    assert "hunter2" not in str(batch)
    assert "4111" not in str(batch)
    assert "hunter2" not in summary
    assert "4111" not in summary
    assert "hunter2" not in store.load("s1")[0]["memory"]
    assert len(active) == 20


def test_editing_summarized_history_restarts_the_summary(tmp_path):
    """An edited transcript is a different conversation: summarize it afresh.

    Refusing it refused the answer on every later request; reusing the old
    summary would answer from a conversation the client no longer has.
    """
    store = SQLiteMemoryStore(tmp_path / "edit.db")
    messages = history(25)
    update_session_memory(store, "s1", messages, Mock(return_value="First insight"))
    messages[0]["content"] = "changed"

    summarizer = Mock(return_value="Fresh insight")
    summary, _ = update_session_memory(store, "s1", messages, summarizer)

    assert summary == "Fresh insight"
    # Started over from the first message, with no carried-over summary.
    assert summarizer.call_args.args[0] == ""
    assert summarizer.call_args.args[1][0]["content"] == "changed"
    assert store.load("s1")[0]["memory"] == "Fresh insight"


def test_trimmed_history_drops_the_stale_summary(tmp_path):
    """A transcript shorter than what was summarized must not reuse it."""
    store = SQLiteMemoryStore(tmp_path / "trim.db")
    update_session_memory(
        store, "s1", history(25), Mock(return_value="Old conversation")
    )

    summarizer = Mock()
    summary, _ = update_session_memory(store, "s1", history(3), summarizer)

    assert summary == ""
    summarizer.assert_not_called()
    state, _ = store.load("s1")
    assert state["memory"] == ""
    assert state["summarized_count"] == 0


def test_long_backlog_is_summarized_a_bounded_share_per_request(tmp_path):
    """400 messages on a new session must not mean 76 model calls at once."""
    from services.session_memory import BATCH_SIZE, MAX_BATCHES_PER_REQUEST

    store = SQLiteMemoryStore(tmp_path / "backlog.db")
    messages = history(400)
    summarizer = Mock(side_effect=lambda previous, batch: f"through {batch[-1]['content']}")

    update_session_memory(store, "s1", messages, summarizer)

    assert summarizer.call_count == MAX_BATCHES_PER_REQUEST
    assert store.load("s1")[0]["summarized_count"] == (
        MAX_BATCHES_PER_REQUEST * BATCH_SIZE
    )

    # The next request picks up where this one stopped.
    update_session_memory(store, "s1", messages, summarizer)
    assert store.load("s1")[0]["summarized_count"] == (
        2 * MAX_BATCHES_PER_REQUEST * BATCH_SIZE
    )


def test_each_batch_is_saved_before_the_next_runs(tmp_path):
    """A failure partway through keeps the batches already summarized."""
    store = SQLiteMemoryStore(tmp_path / "partial.db")
    calls = []

    def flaky(previous, batch):
        calls.append(batch)
        if len(calls) == 2:
            raise RuntimeError("model chain exhausted")
        return "first batch"

    with pytest.raises(RuntimeError):
        update_session_memory(store, "s1", history(40), flaky)

    state, _ = store.load("s1")
    assert state["memory"] == "first batch"
    assert state["summarized_count"] == 5


def test_sqlite_optimistic_locking(tmp_path):
    path = tmp_path / "conflict.db"
    first = SQLiteMemoryStore(path)
    second = SQLiteMemoryStore(path)
    initial = {"memory": "help", "summarized_count": 5, "summarized_hash": "a" * 64}
    assert first.save("s1", initial, 0) == 1
    with pytest.raises(VersionConflict):
        second.save("s1", initial, 0)


def test_expiry_removes_access_to_old_summary(tmp_path, monkeypatch):
    from services import sqlite_memory_store

    monkeypatch.setattr(sqlite_memory_store.time, "time", lambda: 1000)
    store = SQLiteMemoryStore(tmp_path / "expiry.db", ttl_seconds=10)
    state = {"memory": "hello", "summarized_count": 5, "summarized_hash": "a" * 64}
    store.save("s1", state, 0)
    monkeypatch.setattr(sqlite_memory_store.time, "time", lambda: 1011)
    assert store.load("s1") == ({}, 0)
    assert store.purge_expired() == 1

def test_deleted_session_cannot_recreate_memory(tmp_path):
    from services.sqlite_memory_store import SessionDeleted

    store = SQLiteMemoryStore(tmp_path / "sessions.db")
    summarizer = Mock(return_value="Transportation every Friday")
    messages = history(25)

    update_session_memory(
        store, "session-A", messages, summarizer
    )

    store.delete("session-A")

    with pytest.raises(SessionDeleted):
        store.load("session-A")

    with pytest.raises(SessionDeleted):
        update_session_memory(
            store, "session-A", messages, summarizer
        )

    assert summarizer.call_count == 1


def test_deletion_does_not_affect_new_session(tmp_path):
    from services.sqlite_memory_store import SessionDeleted

    store = SQLiteMemoryStore(tmp_path / "sessions.db")
    summarizer = Mock(return_value="New session context")

    store.delete("session-A")

    with pytest.raises(SessionDeleted):
        update_session_memory(
            store, "session-A", history(25), summarizer
        )

    memory, _ = update_session_memory(
        store, "session-B", history(25), summarizer
    )

    assert memory == "New session context"
    assert summarizer.call_count == 1