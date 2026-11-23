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
import re
from typing import Any, TypeVar


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


class ModelResponseError(ValueError):
    """A model call failed for a reason our own code describes.

    Raise this, not a bare ``ValueError``, when a service rejects a provider
    response ("groq response content is empty"). Its message is written by us
    and never contains the request text or the model's output, so the failover
    log may quote it. Every other exception is reduced to safe fields by
    ``describe_model_error``.
    """


# Provider error codes worth keeping when an SDK reports them only inside its
# message text. The rest of that text is not logged: the Groq SDK puts the whole
# HTTP response body in the message, and for ``json_validate_failed`` the body
# carries ``failed_generation``, the model's output, which can quote the user.
_KNOWN_ERROR_CODES = (
    "context_length_exceeded",
    "invalid_api_key",
    "json_validate_failed",
    "model_decommissioned",
    "model_not_found",
    "rate_limit_exceeded",
    "request_too_large",
    "service_unavailable",
)
_KNOWN_ERROR_CODE = re.compile(r"\b(" + "|".join(_KNOWN_ERROR_CODES) + r")\b")


def _error_status(error: Exception) -> int | None:
    """The HTTP status a provider SDK attached to its exception, if any."""
    # Groq and OpenAI-style SDKs use ``status_code``; google-genai uses ``code``.
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _error_code(error: Exception) -> str | None:
    """A provider error code such as ``rate_limit_exceeded``, if one is known.

    Only single identifiers are returned, never free text.
    """
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        detail = body.get("error", body)
        code = detail.get("code") if isinstance(detail, dict) else None
        if isinstance(code, str) and code.isidentifier():
            return code
    for attribute in ("code", "status"):  # google-genai: status="RESOURCE_EXHAUSTED"
        value = getattr(error, attribute, None)
        if isinstance(value, str) and value.isidentifier():
            return value
    match = _KNOWN_ERROR_CODE.search(str(error))
    return match.group(1) if match else None


def describe_model_error(error: Exception) -> str:
    """A one-line reason for a failed model call that is safe to log.

    Keeps what diagnoses an outage (the exception type, the HTTP status and the
    provider's error code), so a 429 or a timeout still shows in CloudWatch.
    Drops the free text of the message, which can quote the prompt or the
    model's output, and so the user's own words.
    """
    name = type(error).__name__
    if isinstance(error, ModelResponseError):
        detail = " ".join(str(error).split())
        return f"{name}: {detail}" if detail else name
    parts = [name]
    status = _error_status(error)
    if status is not None:
        parts.append(f"status={status}")
    code = _error_code(error)
    if code is not None:
        parts.append(f"code={code}")
    return " ".join(parts)


def _failure_reason(error: Exception) -> str:
    """Return a compact single-line reason suitable for a warning log."""
    return describe_model_error(error)


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
                "reason=duplicate_target_skipped",
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
                "MODEL_FAILOVER operation=%s provider=%s model=%s reason=%s",
                operation,
                target.provider,
                target.model,
                _failure_reason(error),
            )
            continue

        try:
            valid = bool(is_valid(result))
        except Exception as error:
            logger.warning(
                "MODEL_FAILOVER operation=%s provider=%s model=%s "
                "reason=result_validation_failed: %s",
                operation,
                target.provider,
                target.model,
                _failure_reason(error),
            )
            continue

        if valid:
            return result

        logger.warning(
            "MODEL_FAILOVER operation=%s provider=%s model=%s "
            "reason=invalid_or_empty_result",
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
