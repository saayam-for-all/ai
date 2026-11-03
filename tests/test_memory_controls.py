
"""Tests for local session memory controls."""

import pytest

import lambda_function

from services.sqlite_memory_store import SQLiteMemoryStore

pytestmark = pytest.mark.integration


def enable_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("SAAYAM_SESSION_MEMORY_DEMO", "1")
    monkeypatch.setenv(
        "SAAYAM_MEMORY_SQLITE_PATH",
        str(tmp_path / "sessions.db"),
    )
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)

    return SQLiteMemoryStore(tmp_path / "sessions.db")


def make_event(action, session_id):
    return {
        "body": {
            "action": action,
            "session_id": session_id,
        }
    }


def test_user_can_view_saved_memory(monkeypatch, tmp_path):
    store = enable_demo(monkeypatch, tmp_path)

    store.save(
        "session-A",
        {
            "memory": "Needs transportation on Fridays",
            "summarized_count": 5,
            "summarized_hash": "a" * 64,
        },
        0,
    )

    response = lambda_function.local_memory_controls_handler(
        make_event("view", "session-A"),
        None,
    )

    assert response["statusCode"] == 200
    assert response["body"]["memory"] == (
        "Needs transportation on Fridays"
    )


def test_deleting_memory_invalidates_session(monkeypatch, tmp_path):
    store = enable_demo(monkeypatch, tmp_path)

    store.save(
        "session-A",
        {
            "memory": "Important earlier context",
            "summarized_count": 5,
            "summarized_hash": "a" * 64,
        },
        0,
    )

    deleted = lambda_function.local_memory_controls_handler(
        make_event("delete", "session-A"),
        None,
    )

    assert deleted["statusCode"] == 200
    assert deleted["body"]["new_session_required"] is True

    viewed = lambda_function.local_memory_controls_handler(
        make_event("view", "session-A"),
        None,
    )

    assert viewed["statusCode"] == 410


def test_memory_controls_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SAAYAM_SESSION_MEMORY_DEMO", raising=False)

    response = lambda_function.local_memory_controls_handler(
        make_event("view", "session-A"),
        None,
    )

    assert response["statusCode"] == 404


def test_invalid_session_id_is_rejected(monkeypatch, tmp_path):
    enable_demo(monkeypatch, tmp_path)

    response = lambda_function.local_memory_controls_handler(
        make_event("view", "../other-session"),
        None,
    )

    assert response["statusCode"] == 400


def test_unusable_store_path_returns_503(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("regular file")

    monkeypatch.setenv("SAAYAM_SESSION_MEMORY_DEMO", "1")
    monkeypatch.setenv(
        "SAAYAM_MEMORY_SQLITE_PATH",
        str(blocker / "sessions.db"),
    )
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)

    response = lambda_function.local_memory_controls_handler(
        make_event("view", "session-A"),
        None,
    )

    assert response["statusCode"] == 503
    assert response["body"]["error"] == (
        "Memory controls temporarily unavailable"
    )
