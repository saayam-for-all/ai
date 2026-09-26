"""Unit contract for the shared model fallback chain (issue #193).

These tests pin the public seam for generic ordering and error behaviour so the
same fallback loop is not reimplemented and tested four different ways in
classification, subject generation, answer generation, and organization
search.

The production module is expected to expose:

* ``ModelTarget(provider, model)`` -- one configured attempt;
* ``run_model_chain(...)`` -- try targets in order until one is valid; and
* ``ModelChainExhausted`` -- the explicit whole-chain failure.

No test in this file calls a live provider.
"""

from __future__ import annotations

import logging

import pytest
from groq import GroqError

from utils.model_fallback import (
    ModelChainExhausted,
    ModelTarget,
    run_model_chain,
)


pytestmark = pytest.mark.unit


def _configured_targets():
    """Observe the private default chain through the public runner."""
    attempts = []

    def invoke(target):
        attempts.append(target)
        return None

    with pytest.raises(ModelChainExhausted):
        run_model_chain(
            invoke=invoke,
            is_valid=bool,
            operation="inspect-configuration",
        )

    return attempts


def test_checked_in_chain_is_bounded_groq_then_gemini():
    targets = _configured_targets()
    assert targets
    assert all(target.provider == "groq" for target in targets[:-1])
    assert targets[-1].provider == "gemini"

    identities = [(target.provider, target.model) for target in targets]
    assert len(identities) == len(set(identities))


def test_gpt_oss_targets_request_low_reasoning_effort():
    gpt_oss_targets = [
        target for target in _configured_targets() if "gpt-oss" in target.model
    ]
    assert gpt_oss_targets
    assert all(target.reasoning_effort == "low" for target in gpt_oss_targets)


@pytest.fixture
def fallback_api():
    """Expose the small public API together to keep individual tests concise."""
    return ModelTarget, ModelChainExhausted, run_model_chain


@pytest.fixture
def targets(fallback_api):
    ModelTarget, _, _ = fallback_api
    return (
        ModelTarget(provider="groq", model="groq-primary"),
        ModelTarget(provider="groq", model="groq-secondary"),
        ModelTarget(provider="groq", model="groq-tertiary"),
        ModelTarget(provider="gemini", model="gemini-final"),
    )


def _invoke_from(outcomes, attempts):
    """Return a fake provider call driven by ``model -> value/exception``."""
    def invoke(target):
        attempts.append((target.provider, target.model))
        outcome = outcomes[target.model]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return invoke


def test_primary_success_stops_the_chain(fallback_api, targets):
    _, _, run_model_chain = fallback_api
    attempts = []

    result = run_model_chain(
        targets=targets,
        invoke=_invoke_from({"groq-primary": "primary result"}, attempts),
        is_valid=bool,
        operation="test-primary-success",
    )

    assert result == "primary result"
    assert attempts == [("groq", "groq-primary")]


def test_primary_failure_tries_the_next_groq_model(fallback_api, targets):
    _, _, run_model_chain = fallback_api
    attempts = []
    outcomes = {
        "groq-primary": GroqError("404 model_not_found"),
        "groq-secondary": "secondary result",
    }

    result = run_model_chain(
        targets=targets,
        invoke=_invoke_from(outcomes, attempts),
        is_valid=bool,
        operation="test-secondary-success",
    )

    assert result == "secondary result"
    assert attempts == [
        ("groq", "groq-primary"),
        ("groq", "groq-secondary"),
    ]


def test_all_groq_models_failing_reaches_gemini(fallback_api, targets):
    _, _, run_model_chain = fallback_api
    attempts = []
    outcomes = {
        "groq-primary": GroqError("404 model_not_found"),
        "groq-secondary": TimeoutError("request timed out"),
        "groq-tertiary": GroqError("429 rate limited"),
        "gemini-final": "gemini result",
    }

    result = run_model_chain(
        targets=targets,
        invoke=_invoke_from(outcomes, attempts),
        is_valid=bool,
        operation="test-gemini-success",
    )

    assert result == "gemini result"
    assert attempts == [
        ("groq", "groq-primary"),
        ("groq", "groq-secondary"),
        ("groq", "groq-tertiary"),
        ("gemini", "gemini-final"),
    ]


def test_empty_or_invalid_result_advances_the_chain(fallback_api, targets):
    _, _, run_model_chain = fallback_api
    attempts = []
    outcomes = {
        "groq-primary": "",
        "groq-secondary": {"category": "not-a-valid-candidate"},
        "groq-tertiary": {"category": "valid"},
    }

    result = run_model_chain(
        targets=targets,
        invoke=_invoke_from(outcomes, attempts),
        is_valid=lambda value: value == {"category": "valid"},
        operation="test-result-validation",
    )

    assert result == {"category": "valid"}
    assert attempts == [
        ("groq", "groq-primary"),
        ("groq", "groq-secondary"),
        ("groq", "groq-tertiary"),
    ]


def test_every_target_is_attempted_once_in_configured_order(fallback_api, targets):
    _, ModelChainExhausted, run_model_chain = fallback_api
    attempts = []
    outcomes = {
        target.model: RuntimeError(f"{target.model} unavailable")
        for target in targets
    }

    with pytest.raises(ModelChainExhausted):
        run_model_chain(
            targets=targets,
            invoke=_invoke_from(outcomes, attempts),
            is_valid=bool,
            operation="test-bounded-attempts",
        )

    assert attempts == [(target.provider, target.model) for target in targets]
    assert len(attempts) == len(set(attempts)), "a model was attempted more than once"


def test_total_failure_raises_a_clear_error(fallback_api, targets):
    _, ModelChainExhausted, run_model_chain = fallback_api
    attempts = []
    outcomes = {
        target.model: RuntimeError(f"{target.model} unavailable")
        for target in targets
    }

    with pytest.raises(ModelChainExhausted) as raised:
        run_model_chain(
            targets=targets,
            invoke=_invoke_from(outcomes, attempts),
            is_valid=bool,
            operation="predict_category",
        )

    message = str(raised.value)
    assert "predict_category" in message
    assert "exhaust" in message.lower() or "failed" in message.lower()


def test_warning_names_the_failed_model_and_reason(
    fallback_api, targets, caplog
):
    _, _, run_model_chain = fallback_api
    attempts = []
    outcomes = {
        "groq-primary": GroqError("404 model_not_found"),
        "groq-secondary": "secondary result",
    }

    with caplog.at_level(logging.WARNING):
        run_model_chain(
            targets=targets,
            invoke=_invoke_from(outcomes, attempts),
            is_valid=bool,
            operation="predict_category",
        )

    assert "groq-primary" in caplog.text
    assert "model_not_found" in caplog.text
