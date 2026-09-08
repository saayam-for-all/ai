#!/usr/bin/env python
"""Measure what one interaction actually costs, per service (issue #159).

This is the only thing in the repository that calls a live model on purpose.
It exists because the interesting half of a token baseline cannot be derived
statically:

  * completion tokens are whatever the model decided to write, and
  * classification's cost is driven by *how many* calls it makes, which is one
    per taxonomy level and depends on which category the model picks.

Run it, commit the JSON it writes, and nobody has to run it again until the
prompts or the models change.

    python tools/measure_token_baseline.py                  # every service
    python tools/measure_token_baseline.py --service classify subject
    python tools/measure_token_baseline.py --limit 3        # a cheaper pass

Credentials come from .env (GROQ_API_KEY / GEMINI_API_KEY). utils/client.py
reads keys from SSM only, which is right for Lambda and useless on a laptop,
so this script builds its own clients and injects them. It deliberately does
not change how the deployed function loads credentials.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pathlib
import statistics
import sys
import time
import traceback

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_PATH = REPO_ROOT / "docs" / "metrics" / "token_baseline.json"

# A fixed corpus, so two runs are comparable and a regression is visible.
# Spread across the taxonomy and across description lengths, because both
# drive cost: the category decides how deep classification walks, and the
# description is the only part of most prompts that varies.
CORPUS = [
    {
        "id": "housing-short",
        "category": "HOUSING_ASSISTANCE",
        "description": "My kitchen sink has been leaking for a week.",
        "location": "Austin, TX",
    },
    {
        "id": "food-short",
        "category": "FOOD_AND_ESSENTIALS",
        "description": "I need groceries for my family this week.",
        "location": "Chicago, IL",
    },
    {
        "id": "healthcare-medium",
        "category": "HEALTHCARE_AND_WELLNESS",
        "description": (
            "I have been feeling tired and short of breath when I climb stairs, "
            "and I am not sure if it is my heart. I do not have insurance right "
            "now and I am not sure where to go for an affordable checkup."
        ),
        "location": "Phoenix, AZ",
    },
    {
        "id": "education-medium",
        "category": "EDUCATION_CAREER_SUPPORT",
        "description": (
            "My daughter is in ninth grade and is falling behind in algebra. "
            "We cannot afford a private tutor and her school does not offer "
            "after-school help. I would like to find free tutoring nearby."
        ),
        "location": "Newark, NJ",
    },
    {
        "id": "elderly-medium",
        "category": "ELDERLY_COMMUNITY_ASSISTANCE",
        "description": (
            "My mother is 82 and lives alone. She is having trouble getting to "
            "her medical appointments and with groceries. I live out of state "
            "and I am looking for someone who can check on her regularly."
        ),
        "location": "Tampa, FL",
    },
    {
        "id": "clothing-short",
        "category": "CLOTHING_ASSISTANCE",
        "description": "I need a winter coat for my son.",
        "location": "Detroit, MI",
    },
    {
        "id": "housing-long",
        "category": "HOUSING_ASSISTANCE",
        "description": (
            "I received an eviction notice two days ago after falling behind on "
            "rent for three months. I lost my job in the spring and have been "
            "doing gig work since, but it has not been enough to cover rent and "
            "utilities. I have two children in elementary school and I do not "
            "want to move them out of their district. I have applied for rental "
            "assistance through the county but have not heard back. I need to "
            "know what my options are and whether anyone can help me negotiate "
            "with my landlord before the court date at the end of the month."
        ),
        "location": "Cleveland, OH",
    },
    {
        "id": "general-ambiguous",
        "category": "GENERAL_CATEGORY",
        "description": "I am going through a hard time and do not know where to start.",
        "location": "Denver, CO",
    },
]


# ---------------------------------------------------------------------------
# Credentials and client injection
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
    """Build real clients and push them into every module that holds one.

    `utils/__init__.py` and `utils/subject_generator.py` do
    `from utils.client import groq_llm`, which binds the value at import time.
    Setting it back on `utils.client` alone would leave both of them holding
    the None they imported, and the harness would silently measure nothing.
    """
    from groq import Groq
    from google import genai
    from langchain_groq import ChatGroq
    from langchain_google_genai import ChatGoogleGenerativeAI

    import utils.client as C

    installed = []

    if groq_key:
        C.GROQ_API_KEY = groq_key
        C.client = Groq(api_key=groq_key)
        C.groq_llm = ChatGroq(
            api_key=groq_key, model=C.GROQ_MODEL, temperature=C.GROQ_TEMPERATURE
        )
        C._use_groq = True
        installed.append("groq")

    if gemini_key:
        C.GEMINI_API_KEY = gemini_key
        C._gemini_client = genai.Client(api_key=gemini_key)
        C.gemini_llm = ChatGoogleGenerativeAI(
            model=C.GEMINI_MODEL,
            temperature=C.GEMINI_TEMPERATURE,
            google_api_key=gemini_key,
        )
        C._use_gemini = True
        installed.append("gemini")

    # Re-point the modules that copied these names at import time.
    import utils
    import utils.subject_generator as SG
    import services.classification_service as CS

    for module in (utils, SG):
        module.groq_llm = C.groq_llm
        module.gemini_llm = C.gemini_llm
    for module in (SG,):
        module._use_groq = C._use_groq
        module._use_gemini = C._use_gemini

    CS.client = C.client
    CS._use_groq = C._use_groq
    CS._gemini_client = C._gemini_client

    return installed


# ---------------------------------------------------------------------------
# Running one service and capturing what it reported
# ---------------------------------------------------------------------------

def _captured_usage(fn, *args, **kwargs):
    """Run `fn`, returning (result, usage_records, seconds, error).

    Services report usage by printing a TOKEN_USAGE line, so the harness reads
    the same telemetry an operator would read in CloudWatch. That makes this a
    check on the logging path as well as a measurement.
    """
    buffer = io.StringIO()
    started = time.time()
    error = None
    result = None
    try:
        with contextlib.redirect_stdout(buffer):
            result = fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - see below
        # Deliberately broad, and deliberately not re-raised. A provider can
        # fail any of ~45 calls in a run (rate limit, retired model, malformed
        # JSON), and one dead case must not throw away the other seven. The
        # error is not swallowed: it is returned, printed against its case in
        # the run output, and stored in the committed JSON, so a baseline built
        # from partial data says so on its face.
        error = f"{type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)
    elapsed = round(time.time() - started, 2)

    records = []
    for line in buffer.getvalue().splitlines():
        if not line.startswith("TOKEN_USAGE "):
            continue
        raw = line[len("TOKEN_USAGE "):]
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as e:
            # A malformed telemetry line means log_usage emitted something it
            # should not have. Silently skipping it would make the service look
            # free; say so loudly and keep going.
            print(f"  WARNING: unparseable TOKEN_USAGE line ({e}): {raw[:120]}",
                  file=sys.stderr)
    return result, records, elapsed, error


def measure_classify(case):
    from services.classification_service import predict_categories

    (result, _records, elapsed, error) = _captured_usage(
        predict_categories, case["description"]
    )
    if error:
        return {"error": error, "seconds": elapsed}
    _categories, usage = result
    return {**_summarise(usage), "seconds": elapsed}


def measure_subject(case):
    from utils.subject_generator import generate_subject_from_description

    (_subject, records, elapsed, error) = _captured_usage(
        generate_subject_from_description, case["description"]
    )
    if error:
        return {"error": error, "seconds": elapsed}
    return {**_summarise(records[0] if records else None), "seconds": elapsed}


def measure_answer(case):
    from utils.generate_answer_service import generate_ai_answer

    (_answer, records, elapsed, error) = _captured_usage(
        generate_ai_answer,
        category=case["category"],
        subject=case["description"][:70],
        description=case["description"],
        location=case["location"],
    )
    if error:
        return {"error": error, "seconds": elapsed}
    return {**_summarise(records[0] if records else None), "seconds": elapsed}


def measure_orgs(case):
    from utils.search_orgs import find_organizations

    (_orgs, records, elapsed, error) = _captured_usage(
        find_organizations,
        subject=case["description"][:70],
        description=case["description"],
        location=case["location"],
        category=case["category"],
    )
    if error:
        return {"error": error, "seconds": elapsed}
    return {**_summarise(records[0] if records else None), "seconds": elapsed}


MEASURERS = {
    "classify": ("predict_category", measure_classify),
    "subject": ("generate_subject", measure_subject),
    "answer": ("generate_answer", measure_answer),
    "orgs": ("search_orgs", measure_orgs),
}


def _summarise(usage) -> dict:
    if not usage:
        return {"calls": 0, "prompt": 0, "completion": 0, "total": 0, "providers": []}
    return {
        "calls": usage.get("total_calls", 0),
        "prompt": usage.get("total_prompt_tokens", 0),
        "completion": usage.get("total_completion_tokens", 0),
        "total": usage.get("total_tokens", 0),
        "providers": [c.get("provider") for c in usage.get("calls", [])],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def aggregate(rows: list[dict]) -> dict:
    good = [r for r in rows if "error" not in r and r.get("total")]
    if not good:
        return {"samples": 0, "errors": len(rows)}
    totals = [r["total"] for r in good]
    return {
        "samples": len(good),
        "errors": len(rows) - len(good),
        "calls_per_request": round(statistics.mean(r["calls"] for r in good), 2),
        "prompt_mean": round(statistics.mean(r["prompt"] for r in good)),
        "completion_mean": round(statistics.mean(r["completion"] for r in good)),
        "total_mean": round(statistics.mean(totals)),
        "total_median": round(statistics.median(totals)),
        "total_min": min(totals),
        "total_max": max(totals),
        "seconds_mean": round(statistics.mean(r["seconds"] for r in good), 2),
    }


def print_report(results: dict) -> None:
    print("\n" + "=" * 78)
    print("TOKEN BASELINE - mean tokens per interaction, per service")
    print("=" * 78)
    header = f"{'service':<18}{'calls':>7}{'prompt':>9}{'compl':>8}{'total':>8}{'median':>8}{'range':>15}"
    print(header)
    print("-" * 78)
    ranked = sorted(
        results["services"].items(),
        key=lambda kv: kv[1]["summary"].get("total_mean", 0),
        reverse=True,
    )
    for name, data in ranked:
        s = data["summary"]
        if not s.get("samples"):
            print(f"{name:<18}{'  (no successful samples)':>60}")
            continue
        span = f"{s['total_min']}-{s['total_max']}"
        print(f"{name:<18}{s['calls_per_request']:>7}{s['prompt_mean']:>9}"
              f"{s['completion_mean']:>8}{s['total_mean']:>8}{s['total_median']:>8}{span:>15}")
    print("-" * 78)
    grand = sum(d["summary"].get("total_mean", 0) for d in results["services"].values())
    print(f"{'ALL SERVICES':<18}{'':>7}{'':>9}{'':>8}{grand:>8}   tokens per full request")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", nargs="+", choices=sorted(MEASURERS),
                        default=sorted(MEASURERS), help="services to measure")
    parser.add_argument("--limit", type=int, default=len(CORPUS),
                        help="only the first N corpus entries (a cheaper run)")
    parser.add_argument("--out", default=str(OUTPUT_PATH), help="where to write JSON")
    args = parser.parse_args()

    env = load_env()
    groq_key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
    gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    if not (groq_key or gemini_key):
        print("No GROQ_API_KEY or GEMINI_API_KEY found in .env or the environment.")
        return 1

    installed = install_clients(groq_key, gemini_key)
    print(f"Providers configured: {', '.join(installed) or 'none'}")

    cases = CORPUS[: args.limit]
    print(f"Corpus: {len(cases)} requests x {len(args.service)} services")

    results = {
        "corpus_size": len(cases),
        "models": {},
        "services": {},
    }
    import utils.client as C
    results["models"] = {"groq": C.GROQ_MODEL, "gemini": C.GEMINI_MODEL}

    for key in args.service:
        service_name, measurer = MEASURERS[key]
        rows = []
        print(f"\n--- {service_name} ---")
        for case in cases:
            row = measurer(case)
            row["case"] = case["id"]
            rows.append(row)
            if "error" in row:
                print(f"  {case['id']:<22} ERROR {row['error'][:60]}")
            else:
                print(f"  {case['id']:<22} calls={row['calls']} "
                      f"prompt={row['prompt']:<6} completion={row['completion']:<6} "
                      f"total={row['total']:<6} ({row['seconds']}s)")
        results["services"][service_name] = {"runs": rows, "summary": aggregate(rows)}

    print_report(results)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    try:
        shown = out.relative_to(REPO_ROOT)
    except ValueError:
        shown = out  # --out pointed outside the repo
    print(f"\nWrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
