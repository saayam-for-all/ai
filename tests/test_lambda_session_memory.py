
"""Test the local session-memory integration in the Lambda handler."""

import pytest

from unittest.mock import Mock

import lambda_function

pytestmark = pytest.mark.integration


def make_history(count):
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": (
                "I need transportation every Friday."
                if i == 0 else f"Message {i}"
            ),
        }
        for i in range(count)
    ]


def make_event(history, session_id="session-A"):
    return {
        "body": {
            "category": "Transportation",
            "subject": "Transport assistance",
            "description": "I need a ride.",
            "session_id": session_id,
            "conversation_history": history,
        }
    }


def test_memory_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SAAYAM_SESSION_MEMORY_DEMO", raising=False)

    answer = Mock(return_value="Normal answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(25)),
        None,
    )

    assert result["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs


def test_lambda_restores_sqlite_session_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("SAAYAM_SESSION_MEMORY_DEMO", "1")
    monkeypatch.setenv(
        "SAAYAM_MEMORY_SQLITE_PATH",
        str(tmp_path / "sessions.db"),
    )
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)

    from services import memory_summarizer

    summarizer = Mock(
        return_value="User needs transportation every Friday."
    )
    monkeypatch.setattr(
        memory_summarizer,
        "summarize_memory",
        summarizer,
    )

    answer = Mock(return_value="Memory-aware answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    first = lambda_function.generate_answer_handler(
        make_event(make_history(20)),
        None,
    )

    assert first["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs

    second = lambda_function.generate_answer_handler(
        make_event(make_history(25)),
        None,
    )

    assert second["statusCode"] == 200
    assert answer.call_args.kwargs["memory_context"] == (
        "User needs transportation every Friday."
    )

    summarizer.assert_called_once()


def test_different_session_does_not_inherit_memory(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SAAYAM_SESSION_MEMORY_DEMO", "1")
    monkeypatch.setenv(
        "SAAYAM_MEMORY_SQLITE_PATH",
        str(tmp_path / "sessions.db"),
    )
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)

    from services import memory_summarizer

    monkeypatch.setattr(
        memory_summarizer,
        "summarize_memory",
        Mock(return_value="Memory from Session A"),
    )

    answer = Mock(return_value="Answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    lambda_function.generate_answer_handler(
        make_event(make_history(25), "session-A"),
        None,
    )

    result = lambda_function.generate_answer_handler(
        make_event(make_history(2), "session-B"),
        None,
    )

    assert result["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs


def _enable_memory_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("SAAYAM_SESSION_MEMORY_DEMO", "1")
    monkeypatch.setenv(
        "SAAYAM_MEMORY_SQLITE_PATH",
        str(tmp_path / "sessions.db"),
    )
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)


def test_value_error_from_answer_generation_is_not_a_bad_request(
    monkeypatch, tmp_path
):
    _enable_memory_demo(monkeypatch, tmp_path)

    # What GroqAnswerGenerationService raises when Groq has failed and
    # Gemini is not configured: a provider outage, not a client error.
    answer = Mock(side_effect=ValueError("Gemini client not initialized"))
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(2)),
        None,
    )

    assert result["statusCode"] == 502
    assert result["body"]["code"] == "ANSWER_GENERATION_FAILED"


def test_invalid_session_id_is_still_a_bad_request(monkeypatch, tmp_path):
    _enable_memory_demo(monkeypatch, tmp_path)

    answer = Mock(return_value="Answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(2), "bad id!"),
        None,
    )

    assert result["statusCode"] == 400
    assert result["body"]["error"] == "Invalid session memory request"
    answer.assert_not_called()


def test_memory_config_error_answers_without_memory(monkeypatch, tmp_path):
    _enable_memory_demo(monkeypatch, tmp_path)

    from services import memory_summarizer
    from utils.model_fallback import ModelRoutingConfigError

    # A broken route is a server fault; it must not be a 400 that blames the
    # caller, and it must not cost the person their answer.
    monkeypatch.setattr(
        memory_summarizer,
        "summarize_memory",
        Mock(side_effect=ModelRoutingConfigError("bad route")),
    )

    answer = Mock(return_value="Answer without memory")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(25)),
        None,
    )

    assert result["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs


def test_version_conflict_answers_without_memory(monkeypatch, tmp_path):
    _enable_memory_demo(monkeypatch, tmp_path)

    from services import memory_summarizer
    from services.memory_store import VersionConflict
    from services.sqlite_memory_store import SQLiteMemoryStore

    monkeypatch.setattr(
        memory_summarizer,
        "summarize_memory",
        Mock(return_value="Summary"),
    )
    # Another tab on the same session saved first.
    monkeypatch.setattr(
        SQLiteMemoryStore,
        "save",
        Mock(side_effect=VersionConflict("Conversation state changed")),
    )

    answer = Mock(return_value="Answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(25)),
        None,
    )

    assert result["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs


def test_deleted_session_is_gone_not_bad_request(monkeypatch, tmp_path):
    _enable_memory_demo(monkeypatch, tmp_path)

    from services.sqlite_memory_store import SQLiteMemoryStore

    SQLiteMemoryStore(tmp_path / "sessions.db").delete("session-A")

    answer = Mock(return_value="Answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(2)),
        None,
    )

    assert result["statusCode"] == 410
    answer.assert_not_called()


def test_memory_modules_are_not_imported_when_demo_is_off(monkeypatch):
    """Production must not load, or depend on, the demo's memory code."""
    import sys

    monkeypatch.delenv("SAAYAM_SESSION_MEMORY_DEMO", raising=False)
    memory_modules = [
        "services.memory_validation",
        "services.sqlite_memory_store",
        "services.session_memory",
        "services.memory_summarizer",
    ]
    for name in memory_modules:
        monkeypatch.delitem(sys.modules, name, raising=False)

    monkeypatch.setattr(
        lambda_function, "generate_ai_answer", Mock(return_value="Answer")
    )

    result = lambda_function.generate_answer_handler(
        make_event(make_history(25)),
        None,
    )

    assert result["statusCode"] == 200
    assert not any(name in sys.modules for name in memory_modules)


def test_oversized_history_answers_without_memory(monkeypatch, tmp_path):
    """Past 500 messages the chat loses memory, not its answers."""
    _enable_memory_demo(monkeypatch, tmp_path)

    answer = Mock(return_value="Answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    result = lambda_function.generate_answer_handler(
        make_event(make_history(501)),
        None,
    )

    assert result["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs


def test_restarted_history_answers_without_the_old_memory(monkeypatch, tmp_path):
    """A transcript restarted under the same session_id is still answered."""
    _enable_memory_demo(monkeypatch, tmp_path)

    from services import memory_summarizer

    monkeypatch.setattr(
        memory_summarizer,
        "summarize_memory",
        Mock(return_value="Memory of the first conversation"),
    )

    answer = Mock(return_value="Answer")
    monkeypatch.setattr(lambda_function, "generate_ai_answer", answer)

    lambda_function.generate_answer_handler(make_event(make_history(25)), None)
    assert answer.call_args.kwargs["memory_context"] == (
        "Memory of the first conversation"
    )

    result = lambda_function.generate_answer_handler(
        make_event(make_history(2)),
        None,
    )

    assert result["statusCode"] == 200
    assert "memory_context" not in answer.call_args.kwargs
