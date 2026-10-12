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


# ---------------------------------------------------------------------------
# The routing configuration is validated before any request is served
# ---------------------------------------------------------------------------

import json  # noqa: E402

from utils.model_fallback import ModelRoutingConfigError, _load_model_chain  # noqa: E402

_GROQ = {"provider": "groq", "model": "g1"}
_GEMINI = {"provider": "gemini", "model": "m1"}


def _routing_file(tmp_path, payload):
    path = tmp_path / "model_routing.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "payload,message",
    [
        ("{not json", "not valid JSON"),
        ([], "configuration must be an object"),
        ({"schema_version": 2, "model_chain": [_GEMINI]}, "schema_version"),
        ({"schema_version": 1, "model_chain": []}, "non-empty list"),
        ({"schema_version": 1, "model_chain": ["groq"]}, r"model_chain\[0\] must be an object"),
        ({"schema_version": 1, "model_chain": [{"provider": " ", "model": "m"}]},
         r"provider must be a non-empty string"),
        ({"schema_version": 1, "model_chain": [{"provider": "openai", "model": "m"}]},
         "provider is unsupported"),
        ({"schema_version": 1, "model_chain": [{**_GROQ, "reasoning_effort": "max"}, _GEMINI]},
         "reasoning_effort is unsupported"),
        ({"schema_version": 1, "model_chain": [{**_GEMINI, "reasoning_effort": "low"}]},
         "only valid for Groq"),
        ({"schema_version": 1, "model_chain": [_GROQ, _GROQ, _GEMINI]}, "duplicate target"),
        ({"schema_version": 1, "model_chain": [_GROQ]}, "final model_chain target must be Gemini"),
        ({"schema_version": 1, "model_chain": [_GEMINI, {**_GEMINI, "model": "m2"}]},
         "before the final Gemini fallback must be Groq"),
    ],
    ids=["not-json", "not-object", "schema-version", "empty-chain", "entry-not-object",
         "blank-provider", "unknown-provider", "unknown-effort", "effort-on-gemini",
         "duplicate", "gemini-not-last", "gemini-before-last"],
)
def test_an_invalid_routing_configuration_is_refused(tmp_path, payload, message):
    """A bad model_routing.json fails the cold start, not a request later.

    The chain is loaded once at import, so each of these would otherwise
    surface as a confusing provider error on the first request.
    """
    with pytest.raises(ModelRoutingConfigError, match=message):
        _load_model_chain(_routing_file(tmp_path, payload))


def test_a_missing_routing_configuration_is_refused(tmp_path):
    with pytest.raises(ModelRoutingConfigError, match="not found"):
        _load_model_chain(tmp_path / "absent.json")


def test_a_duplicate_target_in_a_supplied_chain_is_tried_once(caplog):
    """The one-attempt-per-model bound also holds for a caller's own chain."""
    target = ModelTarget(provider="groq", model="g1")
    attempts = []

    with pytest.raises(ModelChainExhausted):
        run_model_chain(
            invoke=attempts.append,
            is_valid=bool,
            operation="op",
            targets=[target, target],
        )

    assert attempts == [target]
    assert "duplicate_target_skipped" in caplog.text


def test_a_validator_that_raises_advances_the_chain(caplog):
    """A result that crashes validation is a failed attempt, not an outage."""
    first = ModelTarget(provider="groq", model="g1")
    second = ModelTarget(provider="gemini", model="m1")

    def is_valid(result):
        if result == "unparseable":
            raise ValueError("cannot read result")
        return True

    result = run_model_chain(
        invoke=lambda target: "unparseable" if target == first else "answer",
        is_valid=is_valid,
        operation="op",
        targets=[first, second],
    )

    assert result == "answer"
    assert "result_validation_failed" in caplog.text
