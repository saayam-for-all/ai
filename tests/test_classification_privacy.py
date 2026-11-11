import logging

import lambda_function
from utils.model_fallback import ModelTarget, run_model_chain

PRIVATE_TEXT = "PRIVATE_VOLUNTEER_DESCRIPTION_12345"


def test_model_failure_does_not_log_private_text(caplog):
    def failing_model(target):
        raise RuntimeError(f"Model failed while processing {PRIVATE_TEXT}")

    with caplog.at_level(logging.WARNING):
        try:
            run_model_chain(
                invoke=failing_model,
                is_valid=bool,
                operation="predict_category",
                targets=[ModelTarget(provider="groq", model="test-model")],
            )
        except Exception as exc:
            assert type(exc).__name__ == "ModelChainExhausted"

    assert PRIVATE_TEXT not in caplog.text
    assert "RuntimeError" in caplog.text


def test_prediction_error_does_not_expose_private_text(monkeypatch, capsys):
    def failing_prediction(description):
        raise RuntimeError(f"Failed to classify {PRIVATE_TEXT}")

    monkeypatch.setattr(
        lambda_function,
        "predict_categories",
        failing_prediction,
    )

    response = lambda_function.predict_category_handler(
        {"body": {"description": PRIVATE_TEXT}},
        None,
    )

    captured = capsys.readouterr()

    assert response["statusCode"] == 500
    assert response["body"] == {"error": "Category prediction failed"}
    assert PRIVATE_TEXT not in captured.out
    assert PRIVATE_TEXT not in captured.err
    assert PRIVATE_TEXT not in str(response)


def test_model_not_found_error_logs_safe_reason(caplog):
    def failing_model(target):
        raise RuntimeError(f"404 model_not_found: {PRIVATE_TEXT}")

    with caplog.at_level(logging.WARNING):
        try:
            run_model_chain(
                invoke=failing_model,
                is_valid=bool,
                operation="predict_category",
                targets=[ModelTarget(provider="groq", model="test-model")],
            )
        except Exception as exc:
            assert type(exc).__name__ == "ModelChainExhausted"

    assert "model_not_found" in caplog.text
    assert PRIVATE_TEXT not in caplog.text
