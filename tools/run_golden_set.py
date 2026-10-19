#!/usr/bin/env python
"""Run the classification golden set against the live model (issue #197, stack 5).

This is the evaluation half of the quality gate. It calls the real classifier,
with real models, over every case in evaluation/golden/classification.jsonl,
then writes the scored result next to the token baseline:

    docs/metrics/golden_set_classification.json   what the test suite checks
    docs/metrics/GOLDEN_SET_CLASSIFICATION.md     the same, for a person

Run it whenever a prompt, the model chain, the elderly routing or the golden
set changes, and commit both files. Until you do, the offline suite fails,
because the committed score no longer describes the code.

    python tools/run_golden_set.py            # live run, about 45 cases
    python tools/run_golden_set.py --limit 5  # a cheap smoke run, not written
    python tools/run_golden_set.py --check    # offline: is the committed result current?

Credentials come from .env (GROQ_API_KEY, GEMINI_API_KEY) exactly as for
tools/measure_token_baseline.py, whose client injection this reuses.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _print_result(result) -> None:
    """One progress line per case, so a slow live run is visibly alive."""
    if result.error:
        mark = "ERROR"
    elif not result.scored:
        mark = "gap  "
    else:
        mark = "ok   " if result.top_level_ok else "MISS "
    got = result.error or ", ".join(result.predicted_names[:3]) or "(empty)"
    print(f"  {mark} {result.id:<14} expected {result.expected or '-':<34} got {got[:80]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only the first N cases; the result is printed, not written")
    parser.add_argument("--check", action="store_true", help="check the committed result offline and exit")
    args = parser.parse_args()

    # Importing the service prints the client bootstrap lines; they are noise here.
    with contextlib.redirect_stdout(io.StringIO()):
        from evaluation import classification_eval as ev
        from evaluation.golden_set import load_golden_set
        from measure_token_baseline import install_clients, load_env

    if args.check:
        problems = ev.check_results()
        for problem in problems:
            print(f"FAIL: {problem}")
        if not problems:
            print(f"OK: {ev.RESULTS_PATH.name} is current (fingerprint {ev.fingerprint()}) and passed.")
        return 1 if problems else 0

    env = load_env()
    groq_key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
    gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    if not (groq_key or gemini_key):
        print("No GROQ_API_KEY or GEMINI_API_KEY found in .env or the environment.")
        return 1
    with contextlib.redirect_stdout(io.StringIO()):
        installed = install_clients(groq_key, gemini_key)
    print(f"Providers configured: {', '.join(installed)}")

    cases = load_golden_set()
    if args.limit:
        cases = cases[: args.limit]
    print(f"Golden set: {len(cases)} cases, pass mark {ev.PASS_MARK:.0%} top-level accuracy\n")

    def classify(description):
        """The production classifier, with its TOKEN_USAGE line kept off the console."""
        from services.classification_service import predict_categories

        with contextlib.redirect_stdout(io.StringIO()):
            return predict_categories(description)

    report = ev.evaluate(cases, classify, on_result=_print_result)

    scored = report.scored
    print(
        f"\nTop-level accuracy {sum(r.top_level_ok for r in scored)}/{len(scored)} "
        f"({report.top_level_accuracy:.0%}), path accuracy {report.path_accuracy:.0%}, "
        f"errors {len(report.errors)}: {'PASSED' if report.passed else 'FAILED'}"
    )
    if args.limit:
        print("Partial run (--limit): nothing written.")
        return 0 if report.passed else 1

    ev.RESULTS_PATH.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ev.REPORT_PATH.write_text(ev.render_markdown(report), encoding="utf-8")
    print(f"Wrote {ev.RESULTS_PATH.relative_to(REPO_ROOT)} and {ev.REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
