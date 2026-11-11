"""One structured outcome line per category prediction (issue #197, stack 5).

`TOKEN_USAGE` (issue #159) says what a request *cost*. Nothing said what it
*decided*, which is how a long stretch of every request landing in General
went unnoticed: an empty result, a General result and an outage all looked the
same from the outside. This line records the decision.

It is printed in CloudWatch Embedded Metric Format (EMF). Lambda ships stdout
to CloudWatch Logs, and CloudWatch extracts the metrics named under `_aws`
from any line shaped like this, so we get real metrics - and alarms on them -
with no extra AWS call, client or dependency in the request path. The same
line stays queryable in Logs Insights by `event = "CLASSIFICATION_OUTCOME"`.

Two rules, the same as `utils/token_usage.py`:

  * nothing in here may raise into a request - telemetry is not the product;
  * the description itself is never logged, only its length. It is free text
    from a person asking for help and can carry anything about them.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

EVENT = "CLASSIFICATION_OUTCOME"
NAMESPACE = "Saayam/GenAI"
SERVICE = "predict_category"
GENERAL_ID = "0.0.0.0.0"

#: Metric name -> CloudWatch unit. The 0/1 metrics are flags, so the
#: average of one is a rate (for example the share of requests answered
#: General) and its sum is a count.
METRICS = {
    "Requests": "Count",
    "General": "Count",
    "Empty": "Count",
    "Error": "Count",
    "Fallback": "Count",
    "ElderlyRouted": "Count",
    "LatencyMs": "Milliseconds",
    "ModelCalls": "Count",
    "Tokens": "Count",
}


def _primary_model() -> str | None:
    """The first model in the configured chain; any other answering is a fallback."""
    try:
        from utils.model_fallback import _DEFAULT_MODEL_CHAIN

        first = _DEFAULT_MODEL_CHAIN[0]
        return f"{first.provider}/{first.model}"
    except Exception:  # noqa: BLE001 - a missing chain must not break telemetry
        return None


def build_outcome(
    results,
    usage,
    *,
    error: BaseException | None,
    elapsed_ms: float,
    elderly_routed: bool,
    description_chars: int,
) -> dict:
    """The outcome record for one prediction, as a plain JSON-ready dict.

    `results` is what `predict_categories` returned (possibly empty, or None
    when it raised), `usage` its token accumulator. Kept separate from
    `log_outcome` so the record can be checked without capturing stdout.
    """
    results = results or []
    usage = usage if isinstance(usage, dict) else {}
    calls = usage.get("calls", [])
    models = [f"{call.get('provider')}/{call.get('model')}" for call in calls]
    primary = _primary_model()
    top = results[0] if results else {}
    top_id = str(top.get("category_number") or "") or None

    if error is not None:
        outcome = "error"
    elif not results:
        outcome = "empty"
    elif top_id == GENERAL_ID:
        outcome = "general"
    else:
        outcome = "categorised"

    return {
        "event": EVENT,
        "Service": SERVICE,
        "outcome": outcome,
        "top_category": top_id,
        "top_confidence": top.get("confidence"),
        "depth": 0 if not top_id or top_id == GENERAL_ID else top_id.count(".") + 1,
        "models": models,
        "error_type": type(error).__name__ if error is not None else None,
        "description_chars": int(description_chars),
        # Metric values, named as in METRICS.
        "Requests": 1,
        "General": int(outcome == "general"),
        "Empty": int(outcome == "empty"),
        "Error": int(outcome == "error"),
        "Fallback": int(bool(primary) and any(model != primary for model in models)),
        "ElderlyRouted": int(bool(elderly_routed)),
        "LatencyMs": round(float(elapsed_ms), 1),
        "ModelCalls": len(calls),
        "Tokens": int(usage.get("total_tokens", 0) or 0),
    }


def to_emf(record: dict, *, timestamp_ms: int | None = None) -> dict:
    """Wrap `record` in the `_aws` metadata that makes CloudWatch extract metrics.

    One dimension set, `Service`, so every service that adopts this later
    lands in the same metrics, split by service.
    """
    return {
        "_aws": {
            "Timestamp": int(timestamp_ms if timestamp_ms is not None else time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["Service"]],
                    "Metrics": [{"Name": name, "Unit": unit} for name, unit in METRICS.items()],
                }
            ],
        },
        **record,
    }


def log_outcome(results, usage, **fields) -> None:
    """Print one EMF outcome line for this prediction. Never raises."""
    try:
        print(json.dumps(to_emf(build_outcome(results, usage, **fields)), ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 - the request already has its answer
        logger.exception("%s: could not build or print the outcome line", EVENT)
