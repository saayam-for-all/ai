"""Shared model fallback configuration and execution utilities.

Contains model-routing configuration validation, model target and error types,
and the runner that tries configured models in order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, TypeVar
import httpx


logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


_MODEL_ROUTING_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "model_routing.json"
)
_SUPPORTED_PROVIDERS = frozenset({"groq", "gemini"})
_SUPPORTED_REASONING_EFFORTS = frozenset({"low", "medium", "high"})


class ModelRoutingConfigError(ValueError):
    """The checked-in model-routing configuration is missing or invalid."""


class ModelChainExhausted(RuntimeError):
    """Every configured model failed to produce a valid result."""


@dataclass(frozen=True)
class ModelTarget:
    """One provider/model attempt in the order it should be tried."""

    provider: str
    model: str
    reasoning_effort: str | None = None


def _non_empty_string(value: Any, field: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelRoutingConfigError(
            f"model_chain[{index}].{field} must be a non-empty string"
        )
    return value.strip()


def _load_model_chain(
    path: Path = _MODEL_ROUTING_PATH,
) -> tuple[ModelTarget, ...]:
    """Load and validate the bounded Groq-to-Gemini chain from JSON."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelRoutingConfigError(
            f"Model routing configuration not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ModelRoutingConfigError(
            f"Model routing configuration is not valid JSON: {path}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ModelRoutingConfigError("Model routing configuration must be an object")
    if raw.get("schema_version") != 1:
        raise ModelRoutingConfigError("Unsupported model routing schema_version")

    configured = raw.get("model_chain")
    if not isinstance(configured, list) or not configured:
        raise ModelRoutingConfigError("model_chain must be a non-empty list")

    targets: list[ModelTarget] = []
    for index, entry in enumerate(configured):
        if not isinstance(entry, dict):
            raise ModelRoutingConfigError(
                f"model_chain[{index}] must be an object"
            )

        provider = _non_empty_string(entry.get("provider"), "provider", index).lower()
        model = _non_empty_string(entry.get("model"), "model", index)
        if provider not in _SUPPORTED_PROVIDERS:
            raise ModelRoutingConfigError(
                f"model_chain[{index}].provider is unsupported: {provider}"
            )

        reasoning_effort = entry.get("reasoning_effort")
        if reasoning_effort is not None:
            reasoning_effort = _non_empty_string(
                reasoning_effort, "reasoning_effort", index
            ).lower()
            if reasoning_effort not in _SUPPORTED_REASONING_EFFORTS:
                raise ModelRoutingConfigError(
                    f"model_chain[{index}].reasoning_effort is unsupported: "
                    f"{reasoning_effort}"
                )
        if provider != "groq" and reasoning_effort is not None:
            raise ModelRoutingConfigError(
                f"model_chain[{index}].reasoning_effort is only valid for Groq"
            )

        targets.append(
            ModelTarget(
                provider=provider,
                model=model,
                reasoning_effort=reasoning_effort,
            )
        )

    identities = [(target.provider, target.model) for target in targets]
    if len(identities) != len(set(identities)):
        raise ModelRoutingConfigError("model_chain contains a duplicate target")
    if targets[-1].provider != "gemini":
        raise ModelRoutingConfigError("the final model_chain target must be Gemini")
    if any(target.provider != "groq" for target in targets[:-1]):
        raise ModelRoutingConfigError(
            "all model_chain targets before the final Gemini fallback must be Groq"
        )

    return tuple(targets)
def _error_class_from_status(status: int) -> str:
    """Convert an HTTP status code into an error category."""

    if status == 404:
        return "model_not_found"

    if status in (401, 403):
        return "auth_or_entitlement"

    if status == 429:
        return "rate_limited"

    if 500 <= status <= 599:
        return "timeout_or_unavailable"

    return "other"


def classify_provider_error(error: Exception) -> str:
    """
    Classify Groq and Google Gemini provider errors.

    Supports:
    - Groq SDK
    - google-genai SDK
    - Older google-api-core exceptions
    - LangChain Google exceptions
    - Wrapped exceptions
    """

    seen = set()
    current = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        # Find which exception class was raised.
        class_name = type(current).__name__
        module_name = type(current).__module__

        # Some failures have no HTTP status code.
        if isinstance(
            current,
            (
                TimeoutError,
                ConnectionError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ),
        ):
            return "timeout_or_unavailable"

        # Groq connection and timeout errors.
        if module_name.startswith("groq") and class_name in (
            "APITimeoutError",
            "APIConnectionError",
        ):
            return "timeout_or_unavailable"

        # Newer LangChain Google errors.
        if module_name.startswith("langchain_google_genai"):

            if class_name == "GoogleModelNotFoundError":
                return "model_not_found"

            if class_name in (
                "GoogleAuthenticationError",
                "GooglePermissionDeniedError",
            ):
                return "auth_or_entitlement"

            if class_name == "GoogleRateLimitError":
                return "rate_limited"

            if class_name == "GoogleAPIError":
                return "timeout_or_unavailable"

        # Groq uses status_code.
        # Google SDKs typically use code.
        status = getattr(current, "status_code", None)

        if status is None:
            status = getattr(current, "code", None)

        if isinstance(status, int) and not isinstance(status, bool):
            return _error_class_from_status(status)

        # Check underlying error if an SDK wrapped it.
        current = current.__cause__ or current.__context__

    return "other"


def _failure_reason(error: Exception) -> str:
    """Return a compact single-line reason suitable for a warning log."""
    detail = " ".join(str(error).split())
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def run_model_chain(
    *,
    invoke: Callable[[ModelTarget], ResultT],
    is_valid: Callable[[ResultT], bool],
    operation: str,
    targets: Sequence[ModelTarget] | None = None,
) -> ResultT:
    """Try each configured target once and return the first valid result.

    ``invoke`` owns the provider-specific request.  It receives the target so a
    service can use the correct SDK, model id, prompt, and per-model options.
    ``is_valid`` owns the service contract: a category result, subject, answer,
    and organization list do not share the same definition of valid.

    Provider errors and invalid results are fallback signals.  Every failed
    attempt emits one warning naming the operation, provider, model, and reason.
    If no target succeeds, ``ModelChainExhausted`` makes the outage explicit to
    the calling service instead of returning an empty success.
    """
    chain = _DEFAULT_MODEL_CHAIN if targets is None else tuple(targets)
    operation = str(operation or "model_operation").strip()
    attempted: set[tuple[str, str]] = set()

    for target in chain:
        identity = (target.provider, target.model)
        if identity in attempted:
            # The checked-in configuration rejects duplicates.  Keep the same
            # bounded guarantee for a caller that supplies a custom test chain.
            logger.warning(
                "MODEL_FAILOVER operation=%s provider=%s model=%s "
                "reason=duplicate_target_skipped error_class=other",
                operation,
                target.provider,
                target.model,
            )
            continue
        attempted.add(identity)

        try:
            result = invoke(target)
        except Exception as error:
            logger.warning(
                "MODEL_FAILOVER operation=%s provider=%s model=%s reason=%s error_class=%s",
                operation,
                target.provider,
                target.model,
                _failure_reason(error),
                classify_provider_error(error),
            )
            continue

        try:
            valid = bool(is_valid(result))
        except Exception as error:
            logger.warning(
                "MODEL_FAILOVER operation=%s provider=%s model=%s "
                "reason=result_validation_failed: %s error_class=%s",
                operation,
                target.provider,
                target.model,
                _failure_reason(error),
                classify_provider_error(error),
            )
            continue

        if valid:
            return result

        logger.warning(
            "MODEL_FAILOVER operation=%s provider=%s model=%s "
            "reason=invalid_or_empty_result error_class=other",
            operation,
            target.provider,
            target.model,
        )

    raise ModelChainExhausted(
        f"{operation} failed: model chain exhausted after "
        f"{len(attempted)} attempt(s)"
    )


# Load and validate the checked-in configuration once, after every type and
# function has been defined.  Lambda cold starts fail early on a bad deployment;
# individual requests reuse this immutable tuple without reopening the JSON.
_DEFAULT_MODEL_CHAIN = _load_model_chain()
