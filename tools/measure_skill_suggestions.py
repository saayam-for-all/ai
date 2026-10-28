#!/usr/bin/env python
"""Measure how well volunteer skill suggestions match a labelled set (issue #216).

The acceptance bar for `mode: "volunteer_skills"` is recall >= 80% and
precision >= 80% on a labelled set of volunteer descriptions, on two
consecutive runs. Unit tests cannot show that: they stub the model. This calls
the live model chain on every case in tools/data/volunteer_skills_eval.json and
scores what comes back.

    python tools/measure_skill_suggestions.py                # two runs, every case
    python tools/measure_skill_suggestions.py --runs 1 --limit 5
    python tools/measure_skill_suggestions.py --tag no-match

How a case is scored:

  * recall counts the `expected` IDs that were suggested;
  * precision counts suggestions that are `expected` or `acceptable`, so a
    second right answer ("nurse" -> 5.1.1 or 5.1.11) is not an error;
  * a case whose `expected` is empty is right only when nothing outside
    `acceptable` comes back, and is reported as its own rate, because recall
    and precision say nothing about an empty answer;
  * a case that raised counts as returning nothing. A rate-limited run looks
    worse, never better, and its errors are listed.

Credentials come from .env (GROQ_API_KEY / GEMINI_API_KEY), as in
tools/measure_token_baseline.py. Each call sends ~2,400 prompt tokens and the
development Groq key allows 8,000 tokens a minute, hence the default --delay.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
import os
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATASET_PATH = REPO_ROOT / "tools" / "data" / "volunteer_skills_eval.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "metrics" / "volunteer_skills_eval.json"

TARGET_RECALL = 0.8
TARGET_PRECISION = 0.8


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def load_cases(path=DATASET_PATH) -> list[dict]:
    return json.loads(pathlib.Path(path).read_text())["cases"]


# ---------------------------------------------------------------------------
# Scoring - pure functions, covered by tests/test_skill_suggestion_eval.py
# ---------------------------------------------------------------------------

def score_case(case: dict, returned: list[str]) -> dict:
    """Compare one answer with its labels."""
    expected = set(case["expected"])
    correct = expected | set(case.get("acceptable", []))
    returned_set = set(returned)
    return {
        "expected": len(expected),
        "found": sorted(expected & returned_set),
        "missed": sorted(expected - returned_set),
        "returned": len(returned_set),
        "returned_correct": len(returned_set & correct),
        "extra": sorted(returned_set - correct),
        "no_match_case": not expected,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def summarise(scores: list[dict]) -> dict:
    """Micro-averaged recall and precision over a list of case scores."""
    expected = sum(s["expected"] for s in scores)
    found = sum(len(s["found"]) for s in scores)
    returned = sum(s["returned"] for s in scores)
    returned_correct = sum(s["returned_correct"] for s in scores)
    no_match = [s for s in scores if s["no_match_case"]]
    return {
        "cases": len(scores),
        "recall": _ratio(found, expected),
        "precision": _ratio(returned_correct, returned),
        "expected": expected,
        "found": found,
        "returned": returned,
        "returned_correct": returned_correct,
        "no_match_cases": len(no_match),
        "no_match_correct": _ratio(sum(not s["extra"] for s in no_match), len(no_match)),
    }


def meets_target(summary: dict) -> bool:
    """True when both rates are measured and both reach the bar."""
    recall, precision = summary["recall"], summary["precision"]
    return (
        recall is not None
        and precision is not None
        and recall >= TARGET_RECALL
        and precision >= TARGET_PRECISION
    )


def summarise_by_tag(cases: list[dict], scores: list[dict]) -> dict:
    by_tag = collections.defaultdict(list)
    for case, score in zip(cases, scores):
        for tag in case.get("tags", []):
            by_tag[tag].append(score)
    return {tag: summarise(group) for tag, group in sorted(by_tag.items())}


# ---------------------------------------------------------------------------
# Live run
# ---------------------------------------------------------------------------

def load_env(path=REPO_ROOT / ".env") -> dict:
    """Read KEY=VALUE lines out of .env without importing dotenv."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def install_clients(groq_key: str, gemini_key: str) -> list[str]:
    """Build real clients and push them into the skill suggestion service.

    utils/client.py reads keys from SSM only. The service did
    `from utils.client import client, _use_groq, _gemini_client`, which binds
    the values at import time, so setting them on utils.client alone would
    leave the service holding None.
    """
    import services.skill_suggestion_service as S

    installed = []
    if groq_key:
        from groq import Groq

        S.client = Groq(api_key=groq_key)
        S._use_groq = True
        installed.append("groq")
    if gemini_key:
        from google import genai

        S._gemini_client = genai.Client(api_key=gemini_key)
        installed.append("gemini")
    return installed


def run_case(case: dict) -> dict:
    """Suggest skills for one case; never raises."""
    from services.skill_suggestion_service import suggest_skills

    started = time.time()
    row = {"case": case["id"]}
    try:
        # The service prints TOKEN_USAGE lines; keep them out of the report.
        with contextlib.redirect_stdout(io.StringIO()):
            categories, unmatched, usage = suggest_skills(case["description"])
        row["returned"] = [c["category_number"] for c in categories]
        row["confidence"] = {c["category_number"]: c["confidence"] for c in categories}
        row["unmatched_skills"] = unmatched
        row["tokens"] = usage.get("total_tokens", 0)
    except Exception as e:  # noqa: BLE001 - one dead case must not end the run
        row["returned"] = []
        row["error"] = type(e).__name__
    row["seconds"] = round(time.time() - started, 2)
    return row


def run_once(cases: list[dict], delay: float) -> dict:
    rows, scores = [], []
    for index, case in enumerate(cases):
        if index and delay:
            time.sleep(delay)
        row = run_case(case)
        row["score"] = score_case(case, row["returned"])
        rows.append(row)
        scores.append(row["score"])

        s = row["score"]
        status = f"ERROR {row['error']}" if "error" in row else (
            f"found {len(s['found'])}/{s['expected']}"
            + (f" missed={','.join(s['missed'])}" if s["missed"] else "")
            + (f" extra={','.join(s['extra'])}" if s["extra"] else "")
        )
        print(f"  {case['id']:<30} {status}")

    return {
        "summary": summarise(scores),
        "by_tag": summarise_by_tag(cases, scores),
        "errors": sum("error" in r for r in rows),
        "cases": rows,
    }


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def print_run(number: int, run: dict) -> None:
    s = run["summary"]
    verdict = "PASS" if meets_target(s) else "FAIL"
    print(
        f"Run {number}: recall {_pct(s['recall'])} ({s['found']}/{s['expected']}), "
        f"precision {_pct(s['precision'])} ({s['returned_correct']}/{s['returned']}), "
        f"no-match {_pct(s['no_match_correct'])}, errors {run['errors']} -> {verdict}"
    )
    for tag, t in run["by_tag"].items():
        print(f"    {tag:<16} recall {_pct(t['recall']):>4}  precision {_pct(t['precision']):>4}  ({t['cases']} cases)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=2, help="consecutive runs (acceptance needs 2)")
    parser.add_argument("--limit", type=int, help="only the first N cases (a cheaper run)")
    parser.add_argument("--tag", help="only cases with this tag")
    parser.add_argument("--delay", type=float, default=20.0,
                        help="seconds between calls, to stay under the Groq rate limit")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="labelled cases")
    parser.add_argument("--out", default=str(OUTPUT_PATH), help="where to write JSON")
    args = parser.parse_args()

    env = load_env()
    groq_key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
    gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    if not (groq_key or gemini_key):
        print("No GROQ_API_KEY or GEMINI_API_KEY found in .env or the environment.")
        return 1
    installed = install_clients(groq_key, gemini_key)
    print(f"Providers configured: {', '.join(installed)}")

    cases = load_cases(args.dataset)
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    cases = cases[: args.limit]
    print(f"Cases: {len(cases)}, runs: {args.runs}")

    from utils.model_fallback import _DEFAULT_MODEL_CHAIN

    results = {
        "dataset": str(pathlib.Path(args.dataset).name),
        "case_count": len(cases),
        "model_chain": [f"{t.provider}:{t.model}" for t in _DEFAULT_MODEL_CHAIN],
        "targets": {"recall": TARGET_RECALL, "precision": TARGET_PRECISION},
        "runs": [],
    }
    for number in range(1, args.runs + 1):
        print(f"\n--- run {number} ---")
        results["runs"].append(run_once(cases, args.delay))

    print("\n" + "=" * 78)
    for number, run in enumerate(results["runs"], 1):
        print_run(number, run)
    results["passed"] = all(meets_target(r["summary"]) for r in results["runs"])
    print("=" * 78)
    print("ACCEPTANCE:", "PASS" if results["passed"] else "FAIL",
          f"(recall and precision >= {TARGET_RECALL:.0%} on every run)")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {out}")
    return 0 if results["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
