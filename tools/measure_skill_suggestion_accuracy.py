#!/usr/bin/env python
"""Measure how well volunteer_skills mode finds a volunteer's skills (issue #216).

Issue #216 accepts the feature at **recall >= 80% and precision >= 80% on two
consecutive runs**.  Two runs, because the first prototype scored 84% and then
89% on the same inputs: one number from one pass would not have shown that
spread.

    python tools/measure_skill_suggestion_accuracy.py --limit 3   # smoke test
    python tools/measure_skill_suggestion_accuracy.py             # full, 2 runs

The labelled set is docs/metrics/volunteer_skills_eval_set.json and the
counting rules are in tools/skill_eval_scoring.py, which is unit tested.  This
file is the part that cannot be tested hermetically: it calls live models.

**This takes about half an hour by default, and that is deliberate.**  The
development Groq key is capped at 8,000 tokens per minute and one call costs
roughly 2,400, so about three cases a minute is the ceiling.  Issue #194
recorded a 429 on exactly this when two runs were made back to back.  So the
harness sleeps between cases and backs off on 429 rather than racing the
limiter and reporting failures that are really throttling.

Credentials come from .env (GROQ_API_KEY / GEMINI_API_KEY), as in
tools/measure_token_baseline.py: utils/client.py reads SSM only, which is
right for Lambda and useless on a laptop.

Run it, commit docs/metrics/volunteer_skills_eval.json, and write up what it
found in docs/metrics/VOLUNTEER_SKILLS_EVAL.md.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
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
    score_case,
    to_expected,
    to_predictions,
)

EVAL_SET_PATH = REPO_ROOT / "docs" / "metrics" / "volunteer_skills_eval_set.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "metrics" / "volunteer_skills_eval.json"

#: Seconds between cases.  ~2,400 tokens a call against an 8,000/min key is
#: three calls a minute; 20s leaves a little headroom for a long description.
DEFAULT_SLEEP = 20.0

#: A 429 is the limiter, not the model.  Wait and retry rather than scoring a
#: case as a miss, which would make the accuracy number a function of how fast
#: the laptop happened to be going.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_BACKOFF = 30.0

_RATE_LIMITED = re.compile(r"\b429\b|rate.?limit", re.IGNORECASE)


def load_cases(path: pathlib.Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


def run_one_case(case: dict) -> dict:
    """Call the service once and return what it said, plus what it cost.

    Errors are returned, never raised.  One rate-limited or malformed case out
    of 59 must not throw away the other 58, and a run built from partial data
    has to say so on its face - the same argument as the token baseline.
    """
    from services.skill_suggestion_service import suggest_skills

    buffer = io.StringIO()
    started = time.time()
    categories: list[dict] = []
    unmatched: list[str] = []
    error = None

    try:
        with contextlib.redirect_stdout(buffer):
            categories, unmatched, _usage = suggest_skills(case["description"])
    except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring
        error = f"{type(e).__name__}: {e}"

    elapsed = round(time.time() - started, 2)

    tokens = 0
    for line in buffer.getvalue().splitlines():
        if not line.startswith("TOKEN_USAGE "):
            continue
        try:
            tokens += json.loads(line[len("TOKEN_USAGE "):]).get("total_tokens", 0)
        except json.JSONDecodeError:
            pass

    return {
        "categories": categories,
        "unmatched_skills": unmatched,
        "tokens": tokens,
        "seconds": elapsed,
        "error": error,
    }


def run_case_with_backoff(case: dict, verbose: bool = True) -> dict:
    """run_one_case, retrying while the provider says we are going too fast."""
    for attempt in range(RATE_LIMIT_RETRIES):
        outcome = run_one_case(case)
        if not outcome["error"] or not _RATE_LIMITED.search(outcome["error"]):
            outcome["rate_limit_retries"] = attempt
            return outcome
        wait = RATE_LIMIT_BACKOFF * (2**attempt)
        if verbose:
            print(f"    rate limited, waiting {wait:.0f}s "
                  f"(attempt {attempt + 1}/{RATE_LIMIT_RETRIES})")
        time.sleep(wait)
    outcome["rate_limit_retries"] = RATE_LIMIT_RETRIES
    return outcome


def run_pass(cases: list[dict], sleep: float, label: str) -> dict:
    """One complete pass over the evaluation set."""
    print(f"\n=== {label}: {len(cases)} cases ===")
    rows = []
    scores = []

    for index, case in enumerate(cases):
        outcome = run_case_with_backoff(case)
        predictions = to_predictions(outcome["categories"])
        score = score_case(
            case_id=case["id"],
            expected=to_expected(case["expected"]),
            predictions=predictions,
            traits=tuple(case.get("traits", ())),
            error=outcome["error"],
        )
        scores.append(score)

        rows.append({
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
            "seconds": outcome["seconds"],
            "rate_limit_retries": outcome.get("rate_limit_retries", 0),
            "error": outcome["error"],
        })

        # flush: this run takes about forty minutes, and redirecting it to a
        # file block-buffers stdout. Without this there is nothing to watch.
        if outcome["error"]:
            print(f"  {case['id']:<36} ERROR {outcome['error'][:50]}", flush=True)
        else:
            print(f"  {case['id']:<36} "
                  f"hit {score.true_positives}/{score.true_positives + score.false_negatives}"
                  f"  extra {score.false_positives}"
                  f"  {outcome['tokens']} tok  ({outcome['seconds']}s)", flush=True)

        if sleep and index < len(cases) - 1:
            time.sleep(sleep)

    totals = aggregate(scores)
    return {
        "label": label,
        "runs": rows,
        "summary": totals,
        "by_trait": aggregate_by_trait(scores),
        "false_suggestions": false_suggestion_rate(scores),
        "tokens_total": sum(r["tokens"] for r in rows),
    }


def _pct(value) -> str:
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def print_report(result: dict, threshold: float) -> None:
    print("\n" + "=" * 72)
    print("VOLUNTEER SKILL SUGGESTIONS - recall and precision per run")
    print("=" * 72)
    print(f"{'run':<10}{'cases':>7}{'TP':>6}{'FP':>6}{'FN':>6}"
          f"{'recall':>9}{'precision':>11}{'tokens':>9}")
    print("-" * 72)
    for pass_result in result["passes"]:
        s = pass_result["summary"]
        print(f"{pass_result['label']:<10}{s['cases']:>7}{s['true_positives']:>6}"
              f"{s['false_positives']:>6}{s['false_negatives']:>6}"
              f"{_pct(s['recall']):>9}{_pct(s['precision']):>11}"
              f"{pass_result['tokens_total']:>9}")
    print("-" * 72)

    verdict = result["verdict"]
    bar = f"{threshold * 100:.0f}%"
    print(f"\nEvery run at or above {bar} recall and precision: "
          f"{'YES' if verdict['passes_threshold'] else 'NO'}")

    print("\nBy trait (last run; buckets overlap and do not sum):")
    print(f"  {'trait':<20}{'cases':>7}{'recall':>9}{'precision':>11}")
    for trait, stats in result["passes"][-1]["by_trait"].items():
        print(f"  {trait:<20}{stats['cases']:>7}"
              f"{_pct(stats['recall']):>9}{_pct(stats['precision']):>11}")

    invented = result["passes"][-1]["false_suggestions"]
    print(f"\nNo-skill descriptions that still got a suggestion: "
          f"{invented['cases_with_suggestions']}/{invented['cases']}"
          f" ({_pct(invented['rate']).strip()})")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
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
    args = parser.parse_args()

    env = load_env()
    groq_key = env.get("GROQ_API_KEY", "")
    gemini_key = env.get("GEMINI_API_KEY", "")
    if not (groq_key or gemini_key):
        print("No GROQ_API_KEY or GEMINI_API_KEY found in .env or the environment.")
        return 1

    installed = install_clients(groq_key, gemini_key)
    print(f"Providers configured: {', '.join(installed) or 'none'}")

    cases = load_cases(pathlib.Path(args.set))
    if args.limit:
        cases = cases[: args.limit]

    estimate = args.runs * len(cases) * args.sleep / 60
    print(f"{len(cases)} cases x {args.runs} runs, {args.sleep:.0f}s apart "
          f"- about {estimate:.0f} minutes")

    passes = [
        run_pass(cases, args.sleep, f"run {n + 1}") for n in range(args.runs)
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
        "eval_set": pathlib.Path(args.set).name,
        "cases": len(cases),
        "threshold": args.threshold,
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

    import utils.client as C
    result["models"] = {"groq": C.GROQ_MODEL, "gemini": C.GEMINI_MODEL}

    print_report(result, args.threshold)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    try:
        shown = out.relative_to(REPO_ROOT)
    except ValueError:
        shown = out
    print(f"\nWrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
