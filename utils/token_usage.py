"""One place that knows how to count tokens, for every LLM call we make.

Before this module each service counted (or did not count) tokens its own way:
classification hand-rolled an accumulator dict and inlined the same eight lines
at four call sites, and answer generation, subject generation and organization
search counted nothing at all. Issue #159 is the consolidation.

Three response shapes reach us, because we call models three different ways:

  * the raw Groq SDK           -> ``response.usage.prompt_tokens``
  * the raw Google GenAI SDK   -> ``response.usage_metadata.prompt_token_count``
  * a LangChain chat model     -> ``message.usage_metadata["input_tokens"]``

`extract_usage` sniffs which one it was handed, so callers never branch on the
provider. Note that the raw Gemini response and a LangChain ``AIMessage`` both
expose an attribute literally named ``usage_metadata`` with entirely different
shapes, which is why the sniffing keys off the fields rather than the name.

Nothing in here may raise. A request that would otherwise have succeeded must
not fail because we could not count it - the counting is telemetry, not the
product. Every extractor degrades to zeros.

Degrading is not the same as going quiet, though. Silent zeros are worse than
no counting at all, because a dashboard reading zero looks like a cheap service
rather than a broken counter. So every path that swallows an error logs it,
with enough context to find the caller: the provider, the model, and the type
of the object we were handed. `logger` writes to CloudWatch alongside the
TOKEN_USAGE lines themselves.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: The accumulator's fixed keys. `predict_category` already returns this exact
#: shape to the browser as `body.token_usage`, so it is a response contract and
#: not merely an internal structure.
TOTAL_KEYS = (
    "total_calls",
    "total_prompt_tokens",
    "total_completion_tokens",
    "total_tokens",
)

ZERO_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def new_accumulator() -> dict:
    """A fresh per-request accumulator.

    A plain dict rather than a class: it is JSON-serialisable as-is, it is what
    `predict_categories` already returns to the client, and the existing tests
    construct one literally.
    """
    return {
        "total_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "calls": [],
    }


def _as_int(value) -> int:
    """Coerce a provider's count to a non-negative int.

    Providers return None for a field they did not populate, and occasionally a
    string. A None that reaches `+=` is a TypeError in the middle of a served
    request, which is exactly the failure mode this module must not have.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _usage(prompt, completion, total=None) -> dict:
    """Assemble one usage record, deriving `total` when the provider omits it."""
    prompt_tokens = _as_int(prompt)
    completion_tokens = _as_int(completion)
    total_tokens = _as_int(total)
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _from_langchain(response) -> dict | None:
    """Usage off a LangChain `AIMessage`.

    `usage_metadata` is LangChain's provider-independent shape, populated by
    both ChatGroq and ChatGoogleGenerativeAI. `response_metadata["token_usage"]`
    is the older provider-shaped fallback, still what some versions populate.
    """
    metadata = getattr(response, "usage_metadata", None)
    if isinstance(metadata, dict) and "input_tokens" in metadata:
        usage = _usage(
            metadata.get("input_tokens"),
            metadata.get("output_tokens"),
            metadata.get("total_tokens"),
        )
        # Gemini 2.5 bills thinking tokens as output but reports them apart
        # from the visible answer, so they have to be added back or a reasoning
        # model looks far cheaper than the invoice says.
        details = metadata.get("output_token_details")
        if isinstance(details, dict):
            reasoning = _as_int(details.get("reasoning"))
            if reasoning and reasoning not in (usage["completion_tokens"],):
                usage["completion_tokens"] += reasoning
                usage["total_tokens"] += reasoning
        return usage

    fallback = getattr(response, "response_metadata", None)
    if isinstance(fallback, dict):
        token_usage = fallback.get("token_usage")
        if isinstance(token_usage, dict):
            return _usage(
                token_usage.get("prompt_tokens"),
                token_usage.get("completion_tokens"),
                token_usage.get("total_tokens"),
            )
    return None


def _from_gemini(response) -> dict | None:
    """Usage off a raw `google.genai` response."""
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None or not hasattr(metadata, "prompt_token_count"):
        return None
    completion = _as_int(getattr(metadata, "candidates_token_count", 0))
    # Thinking tokens are billed as output. See the note in _from_langchain.
    completion += _as_int(getattr(metadata, "thoughts_token_count", 0))
    return _usage(
        getattr(metadata, "prompt_token_count", 0),
        completion,
        getattr(metadata, "total_token_count", None),
    )


def _from_groq(response) -> dict | None:
    """Usage off a raw Groq `ChatCompletion`."""
    usage = getattr(response, "usage", None)
    if usage is None or not hasattr(usage, "prompt_tokens"):
        return None
    return _usage(
        getattr(usage, "prompt_tokens", 0),
        getattr(usage, "completion_tokens", 0),
        getattr(usage, "total_tokens", None),
    )


def extract_usage(response) -> dict:
    """Token counts for any response we get back from any provider.

    Returns zeros rather than raising when the response carries no usage at
    all - a stubbed client in a test, a provider that stopped reporting.
    """
    if response is None:
        return dict(ZERO_USAGE)

    for extractor in (_from_langchain, _from_gemini, _from_groq):
        try:
            usage = extractor(response)
        except Exception:
            # One extractor tripping must not stop the others from trying, and
            # must not reach the caller. Logged with the shape we were handed,
            # because the usual cause is a provider changing its response type.
            logger.exception(
                "TOKEN_USAGE: %s failed on a %s response",
                extractor.__name__,
                type(response).__name__,
            )
            continue
        if usage is not None:
            return usage

    # No extractor recognised it. Expected for a stub in a test, and a real
    # signal in production - a provider that stopped reporting usage bills us
    # exactly the same.
    logger.warning(
        "TOKEN_USAGE: no usage on a %s response; counting it as zero",
        type(response).__name__,
    )
    return dict(ZERO_USAGE)


def record(accumulator, response, *, provider: str, model: str, **labels) -> dict:
    """Extract usage from `response` and add it to `accumulator`.

    `labels` are free-form and land on the per-call record: classification
    passes `depth`, subject generation passes `branch`. Returns the usage for
    this one call so a caller can log or assert on it.

    `accumulator` may be None, which makes counting opt-in for callers that do
    not want it without forcing them to build a throwaway dict.
    """
    usage = extract_usage(response)
    if accumulator is None:
        return usage
    try:
        accumulator["total_calls"] += 1
        accumulator["total_prompt_tokens"] += usage["prompt_tokens"]
        accumulator["total_completion_tokens"] += usage["completion_tokens"]
        accumulator["total_tokens"] += usage["total_tokens"]
        accumulator["calls"].append(
            {"provider": provider, "model": model, **labels, **usage}
        )
    except (KeyError, TypeError, AttributeError):
        # A caller passed something that is not an accumulator - a bug on our
        # side, not a provider problem. Their request still succeeded, so this
        # must not raise, but it is a defect and is logged as one: the totals
        # for this request are now wrong rather than merely missing.
        logger.exception(
            "TOKEN_USAGE: cannot record %s/%s into a %s; this request's totals "
            "will under-report by %d tokens",
            provider, model, type(accumulator).__name__, usage["total_tokens"],
        )
    return usage


def log_usage(service: str, accumulator, **context) -> None:
    """Emit one structured line per request for CloudWatch Logs Insights.

    Issue #159 deliberately keeps this to logs: `search_orgs` returns a body
    the org-aggregator team parses as a contract (see utils/search_orgs.py),
    so usage is reported out-of-band rather than added to response shapes.

    The `TOKEN_USAGE` prefix is the grep handle; the rest is JSON so Insights
    can aggregate it without a custom parser.
    """
    if not accumulator:
        return
    try:
        payload = {
            "service": service,
            **{key: accumulator.get(key, 0) for key in TOTAL_KEYS},
            "calls": accumulator.get("calls", []),
            **context,
        }
        print(f"TOKEN_USAGE {json.dumps(payload, ensure_ascii=False, default=str)}")
    except Exception:
        # Building or serialising the line failed - almost always a context
        # value that `default=str` could not handle either. Emit the totals on
        # their own rather than losing the request entirely: a record without
        # its labels is still countable, and the exception says what broke.
        logger.exception("TOKEN_USAGE: could not serialise the record for %s", service)
        try:
            fallback = {"service": service, "degraded": True}
            for key in TOTAL_KEYS:
                value = accumulator.get(key, 0)
                fallback[key] = value if isinstance(value, int) else 0
            print(f"TOKEN_USAGE {json.dumps(fallback)}")
        except Exception:
            # The accumulator itself is unusable. Nothing further to try, and
            # the exception above already carries the detail.
            logger.exception("TOKEN_USAGE: dropped the record for %s entirely", service)
