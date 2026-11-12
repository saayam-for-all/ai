#!/usr/bin/env python
"""Measure how well volunteer_skills mode finds a volunteer's skills (issue #216).

Issue #216 accepts the feature at **recall >= 80% and precision >= 80% on two
consecutive runs**.  Two runs, because the first prototype scored 84% and then
89% on the same inputs: one number from one pass would not have shown that
spread.

    python tools/measure_skill_suggestion_accuracy.py --limit 3   # smoke test
    python tools/measure_skill_suggestion_accuracy.py             # full, 2 runs

    # P0: the same set through today's help-request classifier (no `mode`)
    python tools/measure_skill_suggestion_accuracy.py --classifier help_request \\
        --sleep 40 --out docs/metrics/volunteer_skills_eval_p0_help_request.json

    # Tokens per call for a describe / add more / repeat session
    python tools/measure_skill_suggestion_accuracy.py --session-demo \\
        --out docs/metrics/volunteer_skills_session_cost.json

The labelled set is docs/metrics/volunteer_skills_eval_set.json and the
counting rules are in tools/skill_eval_scoring.py, which is unit tested.  This
file is the part that cannot be tested hermetically: it calls live models.

**This takes about half an hour by default, and that is deliberate.**  The
development Groq key is capped at 8,000 tokens per minute and one call costs
roughly 2,400, so about three cases a minute is the ceiling.  Issue #194
recorded a 429 on exactly this when two runs were made back to back.  So the
harness sleeps between cases and backs off on 429 rather than racing the
limiter and reporting failures that are really throttling.  The help-request
classifier makes a call per level of the taxonomy, so give it a longer sleep.

A 429 usually does not surface as the case's error: the model chain fails over
to the next model instead, and the case is then answered by a model this run
is not measuring.  So every failover the chain logs is recorded with the case,
a rate-limited failover is retried like a rate-limited error, and the summary
counts the cases a fallback model answered.

Credentials come from .env (GROQ_API_KEY / GEMINI_API_KEY), as in
tools/measure_token_baseline.py: utils/client.py reads SSM only, which is
right for Lambda and useless on a laptop.

Run it, commit the JSON it writes, and write up what it found in
docs/metrics/VOLUNTEER_SKILLS_EVAL.md.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import pathlib
import re
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.measure_token_baseline import install_clients, load_env  # noqa: E402
from tools.skill_eval_scoring import (  # noqa: E402
    aggregate,
    aggregate_by_trait,
    false_suggestion_rate,
    run_statistics,
    score_case,
    to_expected,
    to_predictions,
)

EVAL_SET_PATH = REPO_ROOT / "docs" / "metrics" / "volunteer_skills_eval_set.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "metrics" / "volunteer_skills_eval.json"

#: Which service a pass measures.  `volunteer` is the feature; `help_request`
#: is today's classifier, called the way a request without `mode` is served.
CLASSIFIERS = ("volunteer", "help_request")

#: Seconds between cases.  ~2,400 tokens a call against an 8,000/min key is
#: three calls a minute; 20s leaves a little headroom for a long description.
DEFAULT_SLEEP = 20.0

#: A 429 is the limiter, not the model.  Wait and retry rather than scoring a
#: case as a miss, which would make the accuracy number a function of how fast
#: the laptop happened to be going.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_BACKOFF = 30.0

_RATE_LIMITED = re.compile(r"\b429\b|rate.?limit", re.IGNORECASE)

#: Descriptions for --session-demo.  The third repeats the first, which the
#: session should answer with no model call.
SESSION_DEMO = (
    "I'm a licensed electrician and I fix wiring for my neighbours.",
    "I also tutor maths to secondary school students at weekends.",
    "I'm a licensed electrician and I fix wiring for my neighbours.",
)


def load_cases(path: pathlib.Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


class _FailoverRecorder(logging.Handler):
    """Collects the model chain's MODEL_FAILOVER warnings for one case."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.reasons: list[str] = []

    def emit(self, record):
        message = record.getMessage()
        if "MODEL_FAILOVER" in message:
            self.reasons.append(message)


class _MedicalDropCounter:
    """Counts medical suggestions the evidence rule refuses to make.

    The service drops a 5.1.* suggestion whose quote is not in the text without
    saying so, which is right for the response and useless for measuring what
    the rule costs.  Wrapping the one method that decides it counts the drops
    without changing the result.
    """

    def __init__(self):
        self.dropped = 0
        self._original = None

    def __enter__(self):
        import services.skill_suggestion_service as ss

        original = ss.SkillSuggestionService._suggestion
        counter = self

        def counting(service, category_id, confidence, item, text):
            suggestion = original(service, category_id, confidence, item, text)
            if suggestion is None and category_id.startswith(ss.MEDICAL_CONSULTATION_PREFIX):
                counter.dropped += 1
            return suggestion

        self._original = original
        ss.SkillSuggestionService._suggestion = counting
        return self

    def __exit__(self, *_exc):
        import services.skill_suggestion_service as ss

        ss.SkillSuggestionService._suggestion = self._original
        return False


def _usage_from_log(text: str) -> dict:
    """Sum the TOKEN_USAGE lines a call printed, and list the models used.

    Read from the log rather than the return value so that a case which fails
    part-way still reports what it spent.
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "models": []}
    for line in text.splitlines():
        if not line.startswith("TOKEN_USAGE "):
            continue
        try:
            record = json.loads(line[len("TOKEN_USAGE "):])
        except json.JSONDecodeError:
            continue
        usage["prompt_tokens"] += record.get("total_prompt_tokens", 0) or 0
        usage["completion_tokens"] += record.get("total_completion_tokens", 0) or 0
        usage["tokens"] += record.get("total_tokens", 0) or 0
        for call in record.get("calls") or []:
            model = call.get("model") if isinstance(call, dict) else None
            if model:
                usage["models"].append(model)
    return usage


def _explanations(categories: list[dict]) -> dict:
    """How many suggestions carry a verified quote, and how many a reason."""
    explained = [c.get("explanation") or {} for c in categories]
    return {
        "suggestions": len(categories),
        "with_user_said": sum(1 for e in explained if e.get("user_said")),
        "with_why": sum(1 for e in explained if e.get("why")),
    }


def run_one_case(case: dict, classifier: str = "volunteer") -> dict:
    """Call the service once and return what it said, plus what it cost.

    Errors are returned, never raised.  One rate-limited or malformed case out
    of 67 must not throw away the other 66, and a run built from partial data
    has to say so on its face - the same argument as the token baseline.
    """
    buffer = io.StringIO()
    recorder = _FailoverRecorder()
    chain_logger = logging.getLogger("utils.model_fallback")
    chain_logger.addHandler(recorder)
    started = time.time()
    categories: list[dict] = []
    unmatched: list[str] = []
    error = None
    medical_dropped = 0

    try:
        with contextlib.redirect_stdout(buffer):
            if classifier == "help_request":
                from services.classification_service import predict_categories

                categories, _usage = predict_categories(case["description"])
            else:
                from services.skill_suggestion_service import suggest_skills

                with _MedicalDropCounter() as drops:
                    categories, unmatched, _usage = suggest_skills(case["description"])
                medical_dropped = drops.dropped
    except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring
        error = f"{type(e).__name__}: {e}"
    finally:
        chain_logger.removeHandler(recorder)

    outcome = {
        "categories": categories,
        "unmatched_skills": unmatched,
        **_usage_from_log(buffer.getvalue()),
        "seconds": round(time.time() - started, 2),
        "failovers": recorder.reasons,
        "medical_dropped": medical_dropped,
        "error": error,
    }
    if classifier == "volunteer":
        outcome["explanations"] = _explanations(categories)
    return outcome


def _was_rate_limited(outcome: dict) -> bool:
    if outcome["error"] and _RATE_LIMITED.search(outcome["error"]):
        return True
    return any(_RATE_LIMITED.search(reason) for reason in outcome["failovers"])


def run_case_with_backoff(case: dict, classifier: str = "volunteer",
                          verbose: bool = True) -> dict:
    """run_one_case, retrying while the provider says we are going too fast."""
    for attempt in range(RATE_LIMIT_RETRIES):
        outcome = run_one_case(case, classifier)
        if not _was_rate_limited(outcome):
            outcome["rate_limit_retries"] = attempt
            return outcome
        wait = RATE_LIMIT_BACKOFF * (2**attempt)
        if verbose:
            print(f"    rate limited, waiting {wait:.0f}s "
                  f"(attempt {attempt + 1}/{RATE_LIMIT_RETRIES})", flush=True)
        time.sleep(wait)
    outcome["rate_limit_retries"] = RATE_LIMIT_RETRIES
    return outcome


def run_pass(cases: list[dict], sleep: float, label: str,
             classifier: str = "volunteer", primary_model: str | None = None) -> dict:
    """One complete pass over the evaluation set."""
    print(f"\n=== {label}: {len(cases)} cases ===", flush=True)
    rows = []
    scores = []

    for index, case in enumerate(cases):
        outcome = run_case_with_backoff(case, classifier)
        predictions = to_predictions(outcome["categories"])
        score = score_case(
            case_id=case["id"],
            expected=to_expected(case["expected"]),
            predictions=predictions,
            traits=tuple(case.get("traits", ())),
            error=outcome["error"],
        )
        scores.append(score)

        row = {
            "case": case["id"],
            "traits": case.get("traits", []),
            "predicted": [
                {"id": p.category_id, "confidence": p.confidence} for p in predictions
            ],
            "unmatched_skills": outcome["unmatched_skills"],
            "expected_unmatched": case.get("expected_unmatched", []),
            "matched": score.matched,
            "missed": score.missed,
            "spurious": score.spurious,
            "true_positives": score.true_positives,
            "false_positives": score.false_positives,
            "false_negatives": score.false_negatives,
            "tokens": outcome["tokens"],
            "prompt_tokens": outcome["prompt_tokens"],
            "completion_tokens": outcome["completion_tokens"],
            "models": sorted(set(outcome["models"])),
            "seconds": outcome["seconds"],
            "rate_limit_retries": outcome.get("rate_limit_retries", 0),
            "failovers": outcome["failovers"],
            "medical_dropped": outcome["medical_dropped"],
            "error": outcome["error"],
        }
        if "explanations" in outcome:
            row["explanations"] = outcome["explanations"]
        rows.append(row)

        # flush: a pass takes twenty minutes or more, and redirecting it to a
        # file block-buffers stdout. Without this there is nothing to watch.
        if outcome["error"]:
            print(f"  {case['id']:<36} ERROR {outcome['error'][:50]}", flush=True)
        else:
            note = "  FAILOVER" if outcome["failovers"] else ""
            print(f"  {case['id']:<36} "
                  f"hit {score.true_positives}/{score.true_positives + score.false_negatives}"
                  f"  extra {score.false_positives}"
                  f"  {outcome['tokens']} tok  ({outcome['seconds']}s){note}", flush=True)

        if sleep and index < len(cases) - 1:
            time.sleep(sleep)

    return {
        "label": label,
        "runs": rows,
        "summary": aggregate(scores),
        "by_trait": aggregate_by_trait(scores),
        "false_suggestions": false_suggestion_rate(scores),
        "tokens_total": sum(r["tokens"] for r in rows),
        "statistics": run_statistics(rows, primary_model),
    }


def run_session_demo() -> dict:
    """Describe, add more, repeat the first: tokens and the list after each call."""
    from services.skill_suggestion_service import suggest_skills_for_session

    session = None
    calls = []
    print("\n=== session demo ===", flush=True)
    for number, description in enumerate(SESSION_DEMO, start=1):
        buffer = io.StringIO()
        started = time.time()
        with contextlib.redirect_stdout(buffer):
            body = suggest_skills_for_session(description, session)
        session = body["session"]
        usage = body.get("token_usage") or {}
        call = {
            "call": number,
            "description": description,
            "cached": body.get("cached"),
            "prompt_tokens": usage.get("total_prompt_tokens", 0),
            "completion_tokens": usage.get("total_completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "categories": [c["category_number"] for c in body.get("categories", [])],
            "seconds": round(time.time() - started, 2),
        }
        calls.append(call)
        print(f"  call {number}: cached={call['cached']}  {call['total_tokens']} tok  "
              f"-> {', '.join(call['categories']) or '(none)'}", flush=True)
        if number < len(SESSION_DEMO):
            time.sleep(DEFAULT_SLEEP)
    return {"issue": "#216", "session_demo": calls}


def _pct(value) -> str:
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def print_report(result: dict, threshold: float) -> None:
    print("\n" + "=" * 78)
    print(f"VOLUNTEER SKILL SUGGESTIONS ({result['classifier']}) - recall and precision per run")
    print("=" * 78)
    print(f"{'run':<10}{'cases':>7}{'TP':>6}{'FP':>6}{'FN':>6}"
          f"{'recall':>9}{'precision':>11}{'tok/case':>10}{'p95 s':>8}")
    print("-" * 78)
    for pass_result in result["passes"]:
        s = pass_result["summary"]
        stats = pass_result["statistics"]
        mean_tokens = stats["tokens"]["total_mean"] or 0
        p95 = stats["seconds"]["p95"] or 0
        print(f"{pass_result['label']:<10}{s['cases']:>7}{s['true_positives']:>6}"
              f"{s['false_positives']:>6}{s['false_negatives']:>6}"
              f"{_pct(s['recall']):>9}{_pct(s['precision']):>11}"
              f"{mean_tokens:>10.0f}{p95:>8.1f}")
    print("-" * 78)

    verdict = result["verdict"]
    bar = f"{threshold * 100:.0f}%"
    print(f"\nEvery run at or above {bar} recall and precision: "
          f"{'YES' if verdict['passes_threshold'] else 'NO'}")

    for pass_result in result["passes"]:
        stats = pass_result["statistics"]
        print(f"{pass_result['label']}: errors {stats['errors']}, "
              f"429 retries {stats['rate_limit_retries']}, "
              f"failovers {stats['cases_with_failover']}, "
              f"answered by a fallback model {stats['cases_answered_by_fallback_model']}, "
              f"medical dropped {stats['medical_suggestions_dropped']}")

    print("\nBy trait (last run; buckets overlap and do not sum):")
    print(f"  {'trait':<20}{'cases':>7}{'recall':>9}{'precision':>11}")
    for trait, stats in result["passes"][-1]["by_trait"].items():
        print(f"  {trait:<20}{stats['cases']:>7}"
              f"{_pct(stats['recall']):>9}{_pct(stats['precision']):>11}")

    invented = result["passes"][-1]["false_suggestions"]
    print(f"\nNo-skill descriptions that still got a suggestion: "
          f"{invented['cases_with_suggestions']}/{invented['cases']}"
          f" ({_pct(invented['rate']).strip()})")
    print("=" * 78)


def _write(result: dict, path: str) -> None:
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        shown = out.relative_to(REPO_ROOT)
    except ValueError:
        shown = out
    print(f"\nWrote {shown}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--classifier", choices=CLASSIFIERS, default="volunteer",
                        help="volunteer_skills mode (default), or the help-request "
                             "classifier a request without `mode` gets")
    parser.add_argument("--runs", type=int, default=2,
                        help="consecutive passes (issue #216 asks for 2)")
    parser.add_argument("--limit", type=int, default=0,
                        help="only the first N cases (a cheap smoke pass)")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                        help=f"seconds between cases (default {DEFAULT_SLEEP:.0f}, "
                             "sized for an 8,000 token/min key)")
    parser.add_argument("--threshold", type=float, default=0.80,
                        help="the bar recall and precision must clear")
    parser.add_argument("--set", default=str(EVAL_SET_PATH), help="evaluation set JSON")
    parser.add_argument("--out", default=str(OUTPUT_PATH), help="where to write JSON")
    parser.add_argument("--session-demo", action="store_true",
                        help="run the three-call session instead of the set")
    args = parser.parse_args()

    env = load_env()
    groq_key = env.get("GROQ_API_KEY", "")
    gemini_key = env.get("GEMINI_API_KEY", "")
    if not (groq_key or gemini_key):
        print("No GROQ_API_KEY or GEMINI_API_KEY found in .env or the environment.")
        return 1

    installed = install_clients(groq_key, gemini_key)
    print(f"Providers configured: {', '.join(installed) or 'none'}")

    import utils.client as C
    from utils.model_fallback import _DEFAULT_MODEL_CHAIN

    chain = [{"provider": t.provider, "model": t.model} for t in _DEFAULT_MODEL_CHAIN]
    primary_model = chain[0]["model"] if chain else C.GROQ_MODEL

    if args.session_demo:
        result = run_session_demo()
        result["model_chain"] = chain
        _write(result, args.out)
        return 0

    cases = load_cases(pathlib.Path(args.set))
    if args.limit:
        cases = cases[: args.limit]

    estimate = args.runs * len(cases) * args.sleep / 60
    print(f"{len(cases)} cases x {args.runs} runs, {args.sleep:.0f}s apart "
          f"- about {estimate:.0f} minutes")

    passes = [
        run_pass(cases, args.sleep, f"run {n + 1}", args.classifier, primary_model)
        for n in range(args.runs)
    ]

    def clears(summary):
        return (
            summary["recall"] is not None
            and summary["precision"] is not None
            and summary["recall"] >= args.threshold
            and summary["precision"] >= args.threshold
        )

    result = {
        "issue": "#216",
        "classifier": args.classifier,
        "eval_set": pathlib.Path(args.set).name,
        "cases": len(cases),
        "threshold": args.threshold,
        "model_chain": chain,
        "providers_configured": installed,
        "passes": passes,
        "verdict": {
            "passes_threshold": all(clears(p["summary"]) for p in passes),
            "per_run": [
                {
                    "label": p["label"],
                    "recall": p["summary"]["recall"],
                    "precision": p["summary"]["precision"],
                    "clears": clears(p["summary"]),
                }
                for p in passes
            ],
        },
    }

    print_report(result, args.threshold)
    _write(result, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
