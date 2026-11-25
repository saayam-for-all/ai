"""Daily health and entitlement probe for every model in the chain.

Issue #195, Part C. Automatic fallback (#193) keeps a request working while
one model is down, which is also why nobody notices that model is down. In
August 2026 every Groq model we called was retired and a person noticed weeks
later. On 1 June 2026 the Gemini model kept as the last resort was shut down
and nothing noticed, because nothing called it.

Once a day this probe calls **every** model in ``config/model_routing.json``
with one fixed trivial prompt, including fallbacks no request is using today,
and records for each: reachable or not, the error class if not (Part A's
``classify_provider_error``), and latency.

What it writes:

* one ``MODEL_PROBE`` log line per model, for Logs Insights;
* ``ModelReachable`` (1 or 0) and ``ModelLatencyMs`` per model, with
  ``provider`` and ``model`` dimensions, for the per-model history;
* ``ModelProbeFailures``, the count of models that did not answer, written on
  every run including when it is 0. The Part D alarm watches this one metric,
  so a missing datapoint means the probe itself did not run.

The Lambda entry point is ``lambda_function.model_health_probe_handler``.
It is deliberately not one of the router's services: anyone who can reach the
API could otherwise spend provider quota on demand.

Run it locally against the real providers (spends a few tokens, needs
``GROQ_API_KEY`` and ``GEMINI_API_KEY`` in the environment or ``.env``)::

    python -m utils.model_health_probe
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass
import logging
import time

from utils import model_fallback
from utils.model_fallback import (
    ModelTarget,
    classify_provider_error,
    describe_model_error,
)

logger = logging.getLogger(__name__)

PROBE_PROMPT = "Reply with the single word OK."
PROBE_TIMEOUT_SECONDS = 20

METRIC_NAMESPACE = "Saayam/GenAI"
METRIC_SERVICE = "model_health_probe"
FAILURES_METRIC = "ModelProbeFailures"
REACHABLE_METRIC = "ModelReachable"
LATENCY_METRIC = "ModelLatencyMs"

# The model answered, but with nothing. The account works; the model does not.
EMPTY_RESPONSE = "empty_response"


@dataclass(frozen=True)
class ProbeResult:
    """One model's health at one moment."""

    provider: str
    model: str
    position: int
    role: str  # "primary" or "fallback"
    reachable: bool
    error_class: str | None
    latency_ms: int
    reason: str | None = None  # log only, never returned

    def log_line(self) -> str:
        # Every key comes before reason=, the only free text, so a metric
        # filter or a Logs Insights parse never has to read past it (#241).
        return (
            f"MODEL_PROBE provider={self.provider} model={self.model} "
            f"position={self.position} role={self.role} "
            f"reachable={str(self.reachable).lower()} "
            f"error_class={self.error_class or 'none'} "
            f"latency_ms={self.latency_ms}"
        )


def configured_model_chain() -> tuple[ModelTarget, ...]:
    """Every target in config/model_routing.json, in order.

    The same validated tuple ``run_model_chain`` uses, read rather than
    reloaded, so the probe can never check a different chain from the one
    requests use.
    """
    return model_fallback._DEFAULT_MODEL_CHAIN


def _ask_model(target: ModelTarget) -> str:
    # Imported here so this module imports cleanly in tests and tools that
    # never call a provider.
    from utils.client import create_chat_model

    model = create_chat_model(target, temperature=0)
    message = model.invoke(PROBE_PROMPT)
    return getattr(message, "content", "") or ""


def _with_timeout(
    invoke: Callable[[ModelTarget], str], timeout: float
) -> Callable[[ModelTarget], str]:
    """Give up on one model after ``timeout`` seconds.

    A slow model must not use up the Lambda's time and leave the models after
    it unchecked. The waiting call is abandoned, not cancelled; the Lambda
    ends soon after anyway. ``TimeoutError`` is classified by Part A as
    ``timeout_or_unavailable``.
    """

    def call(target: ModelTarget) -> str:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            return pool.submit(invoke, target).result(timeout=timeout)
        except FutureTimeout as exc:
            raise TimeoutError(
                f"no answer within {timeout:g} seconds"
            ) from exc
        finally:
            pool.shutdown(wait=False)

    return call


def probe_target(
    target: ModelTarget,
    position: int,
    *,
    invoke: Callable[[ModelTarget], str],
    clock: Callable[[], float] = time.perf_counter,
) -> ProbeResult:
    """Call one model once and record the outcome. Never raises."""
    role = "primary" if position == 0 else "fallback"
    error_class: str | None = None
    reason: str | None = None

    started = clock()
    try:
        content = invoke(target)
    except Exception as error:  # every failure is a result, not a crash
        error_class = classify_provider_error(error)
        reason = describe_model_error(error)
    else:
        if not str(content or "").strip():
            error_class = EMPTY_RESPONSE
            reason = "empty response"
    latency_ms = max(0, round((clock() - started) * 1000))

    result = ProbeResult(
        provider=target.provider,
        model=target.model,
        position=position,
        role=role,
        reachable=error_class is None,
        error_class=error_class,
        latency_ms=latency_ms,
        reason=reason,
    )
    if result.reachable:
        logger.info(result.log_line())
    else:
        logger.warning("%s reason=%s", result.log_line(), reason)
    return result


def run_probe(
    targets: Sequence[ModelTarget] | None = None,
    *,
    invoke: Callable[[ModelTarget], str] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> list[ProbeResult]:
    """Probe every target in order.

    Unlike ``run_model_chain``, this does not stop at the first model that
    answers: the point is to find the ones that don't.
    """
    chain = configured_model_chain() if targets is None else tuple(targets)
    call = _with_timeout(invoke or _ask_model, timeout)
    return [
        probe_target(target, position, invoke=call, clock=clock)
        for position, target in enumerate(chain)
    ]


def publish_metrics(results: Sequence[ProbeResult]) -> None:
    """Write the probe's CloudWatch metrics as Embedded Metric Format lines."""
    from aws_lambda_powertools.metrics import MetricUnit, single_metric

    for result in results:
        for name, unit, value in (
            (REACHABLE_METRIC, MetricUnit.Count, 1 if result.reachable else 0),
            (LATENCY_METRIC, MetricUnit.Milliseconds, result.latency_ms),
        ):
            with single_metric(
                name=name, unit=unit, value=value, namespace=METRIC_NAMESPACE
            ) as metric:
                metric.add_dimension(name="provider", value=result.provider)
                metric.add_dimension(name="model", value=result.model)

    # The one metric the alarm watches. Always written, even when it is 0,
    # so "no datapoint" can only mean the probe did not run.
    failures = sum(1 for result in results if not result.reachable)
    with single_metric(
        name=FAILURES_METRIC,
        unit=MetricUnit.Count,
        value=failures,
        namespace=METRIC_NAMESPACE,
    ) as metric:
        metric.add_dimension(name="service", value=METRIC_SERVICE)


def summarize(results: Sequence[ProbeResult]) -> dict:
    """What the Lambda returns: readable in the console's test tab."""
    failed = [result for result in results if not result.reachable]
    return {
        "checked": len(results),
        "failed": len(failed),
        "healthy": not failed,
        "results": [
            {key: value for key, value in asdict(result).items() if key != "reason"}
            for result in results
        ],
    }


def handle(event=None, context=None) -> dict:
    """Run one probe, publish its metrics, return the summary."""
    results = run_probe()
    publish_metrics(results)
    return summarize(results)


def _load_local_keys() -> None:
    """For a laptop run: take the keys from the environment or ``.env`` when
    Parameter Store was not reachable."""
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - python-dotenv is a dependency
        pass

    import utils.client as client

    if not client.GROQ_API_KEY and os.environ.get("GROQ_API_KEY"):
        client.GROQ_API_KEY = os.environ["GROQ_API_KEY"]
    if not client.GEMINI_API_KEY and os.environ.get("GEMINI_API_KEY"):
        client.GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    _load_local_keys()
    results = run_probe()
    width = max(len(result.model) for result in results)
    print(f"\n{'model'.ljust(width)}  role      status                  latency")
    for result in results:
        status = "ok" if result.reachable else result.error_class
        print(
            f"{result.model.ljust(width)}  {result.role:<8}  "
            f"{status:<22}  {result.latency_ms} ms"
        )
    failed = sum(1 for result in results if not result.reachable)
    print(f"\n{len(results) - failed} of {len(results)} models answering.")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
