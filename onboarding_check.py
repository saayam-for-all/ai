"""
GenAI onboarding self check.

Run this when you think you are done. It checks your setup, your safety habits,
and whether you actually explored the code. Nothing is uploaded anywhere and no
one sees the result unless you share it.

    python onboarding_check.py

First run creates onboarding_answers.py for you to fill in. Fill it, run again.
"""
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANSWERS = ROOT / "onboarding_answers.py"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results = []


def check(name, section):
    """Register a check. The wrapped function returns (status, detail)."""
    def wrap(fn):
        results.append((section, name, fn))
        return fn
    return wrap


ANSWERS_TEMPLATE = '''"""
Fill in each answer, then run:  python onboarding_check.py

Short answers are fine. The point is that you looked, not that you memorised.
"""

# --- Mission 2: reading the code -------------------------------------------

# Which file defines the category taxonomy the classifier chooses from?
# Give the path relative to the repo root, e.g. "utils/example.py"
TAXONOMY_FILE = ""

# How many TOP LEVEL categories are there? (an integer)
# Hint: utils/predict_category_list.py has a helper that returns them.
TOP_LEVEL_COUNT = 0

# What is the name of the function in lambda_function.py that handles
# category prediction requests?
PREDICT_HANDLER = ""


# --- Mission 3: the incident ------------------------------------------------

# In one sentence: why did a single upstream change break several services
# at once?
INCIDENT_ROOT_CAUSE = ""

# Name ONE change that would have reduced the impact.
INCIDENT_PREVENTION = ""


# --- Mission 4: your own observations ---------------------------------------

# Run a few descriptions through the harness. Write 3+ sentences on something
# that surprised you, confused you, or looked wrong.
OBSERVATIONS = ""

# Something in this onboarding that was unclear, broken, or could be better.
# Genuinely useful to us. "Nothing" is a valid answer only if you mean it.
FEEDBACK = ""
'''


# ---------------------------------------------------------------- environment

@check("Python 3.11 or newer", "Setup")
def _py():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return (PASS if ok else FAIL), f"found {v.major}.{v.minor}.{v.micro}"


@check("Required packages installed", "Setup")
def _pkgs():
    missing = []
    for mod in ("groq", "dotenv", "langchain_groq"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return FAIL, f"missing: {', '.join(missing)}. Run: pip install -r requirements.txt"
    return PASS, "groq, dotenv, langchain_groq"


@check("GROQ_API_KEY is available", "Setup")
def _key():
    if os.getenv("GROQ_API_KEY"):
        return PASS, "found in environment"
    env = ROOT / ".env"
    if env.exists() and "GROQ_API_KEY" in env.read_text(encoding="utf-8", errors="ignore"):
        return PASS, "found in .env"
    return FAIL, "not found. Put GROQ_API_KEY in a .env file"


# --------------------------------------------------------------------- safety

@check("Your .env is NOT tracked by git", "Safety")
def _env_ignored():
    env = ROOT / ".env"
    if not env.exists():
        return SKIP, "no .env file"
    try:
        out = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"],
                             cwd=ROOT, capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return FAIL, "your .env is tracked by git. Remove it: git rm --cached .env"
    except Exception:
        return SKIP, "git unavailable"
    return PASS, "not tracked"


@check("No API key hardcoded in your Python files", "Safety")
def _no_hardcoded():
    # Groq keys start gsk_, AWS access key ids start AKIA.
    pat = re.compile(r"(gsk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
    hits = []
    for p in ROOT.rglob("*.py"):
        if ".venv" in p.parts or p.name == Path(__file__).name:
            continue
        try:
            if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(ROOT)))
        except OSError:
            pass
    if hits:
        return FAIL, f"possible key in: {', '.join(hits[:3])}. Move it to .env"
    return PASS, "clean"


# ----------------------------------------------------------- it actually runs

@check("A real call to the model succeeds", "It runs")
def _live_call():
    try:
        from dotenv import dotenv_values
        from groq import Groq
    except ImportError:
        return SKIP, "packages missing"
    key = os.getenv("GROQ_API_KEY") or dotenv_values(ROOT / ".env").get("GROQ_API_KEY")
    if not key:
        return SKIP, "no key"
    try:
        from utils.client import GROQ_MODEL
        model = GROQ_MODEL
    except Exception:
        model = "openai/gpt-oss-20b"
    try:
        kw = dict(model=model, messages=[{"role": "user", "content": "reply with OK"}],
                  max_tokens=5)
        if "gpt-oss" in model:
            kw["reasoning_effort"] = "low"
        Groq(api_key=key).chat.completions.create(**kw)
        return PASS, f"model responded ({model})"
    except Exception as e:
        name = type(e).__name__
        if "NotFound" in name:
            return FAIL, f"{model} is gone. That is Mission 3, go read it"
        if "PermissionDenied" in name:
            return FAIL, "blocked by network. VPN or region issue, not your key"
        return FAIL, f"{name}: {str(e)[:70]}"


ON_DEV_HINT = "you are on the sandbox branch. Do Mission 2: git checkout dev, then run this again"


def _on_dev():
    """The later missions run against the real code on dev. The sandbox branch
    does not have these files, which is expected, not a broken setup."""
    return (ROOT / "services" / "classification_service.py").exists()


def _wire_local_client():
    """Inject the .env key the way AWS Parameter Store would in the real service.
    Without this the client has no key locally and falls through to Gemini."""
    from dotenv import dotenv_values
    from groq import Groq
    from langchain_groq import ChatGroq
    import utils.client as C

    if C._use_groq and C.client:
        return True
    key = os.getenv("GROQ_API_KEY") or dotenv_values(ROOT / ".env").get("GROQ_API_KEY")
    if not key:
        return False
    C.GROQ_API_KEY = key
    C.client = Groq(api_key=key)
    C._use_groq = True
    kw = dict(api_key=key, model=C.GROQ_MODEL, temperature=C.GROQ_TEMPERATURE)
    if "gpt-oss" in C.GROQ_MODEL:
        kw["reasoning_effort"] = "low"
    C.groq_llm = ChatGroq(**kw)
    C._gemini_client = None
    C.gemini_llm = None
    C._use_gemini = False
    return True


@check("Classification returns a real category", "It runs")
def _classify():
    if not _on_dev():
        return SKIP, ON_DEV_HINT
    try:
        if not _wire_local_client():
            return SKIP, "no key to run with"
        from services.classification_service import predict_categories
    except Exception as e:
        return FAIL, f"cannot import classifier: {type(e).__name__}"
    try:
        res, _usage = predict_categories("I need help with math")
    except Exception as e:
        return FAIL, f"{type(e).__name__}: {str(e)[:70]}"
    if not res:
        return FAIL, "returned nothing. This is exactly the Mission 3 failure"
    top = res[0]
    if str(top.get("category_name", "")).upper().startswith("GENERAL"):
        return FAIL, "got GENERAL for a clear maths request, something is wrong"
    return PASS, f"{top.get('category_name')} at {top.get('confidence')}"


# -------------------------------------------------------------- comprehension

def _answers():
    if not ANSWERS.exists():
        return None
    sys.path.insert(0, str(ROOT))
    try:
        mod = importlib.import_module("onboarding_answers")
        importlib.reload(mod)
        return mod
    except Exception:
        return None


@check("You found the taxonomy file", "Reading the code")
def _q_taxonomy():
    if not _on_dev():
        return SKIP, ON_DEV_HINT
    a = _answers()
    if a is None:
        return SKIP, "answers file not filled in"
    got = str(getattr(a, "TAXONOMY_FILE", "")).strip().replace("\\", "/").lower()
    if not got:
        return FAIL, "TAXONOMY_FILE is empty"
    if "categor" in got and got.endswith(".py"):
        return PASS, got
    return FAIL, f"'{got}' does not look right. Look in utils/ for category definitions"


@check("You counted the top level categories", "Reading the code")
def _q_count():
    a = _answers()
    if a is None:
        return SKIP, "answers file not filled in"
    if not _on_dev():
        return SKIP, ON_DEV_HINT
    try:
        from utils.predict_category_list import get_top_level_categories
        expected = len(get_top_level_categories())
    except Exception:
        return SKIP, "cannot import the taxonomy helper"
    got = getattr(a, "TOP_LEVEL_COUNT", 0)
    if got == expected:
        return PASS, f"{got}"
    return FAIL, f"you said {got}. Try get_top_level_categories()"


@check("You found the predict handler", "Reading the code")
def _q_handler():
    a = _answers()
    if a is None:
        return SKIP, "answers file not filled in"
    got = str(getattr(a, "PREDICT_HANDLER", "")).strip().lower().replace("()", "")
    if not got:
        return FAIL, "PREDICT_HANDLER is empty"
    if not _on_dev():
        return SKIP, ON_DEV_HINT
    try:
        src = (ROOT / "lambda_function.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return SKIP, "lambda_function.py not found"
    if re.search(rf"def\s+{re.escape(got)}\s*\(", src):
        return PASS, got
    return FAIL, f"no function named '{got}' in lambda_function.py"


# ------------------------------------------------------------------- written

def _written(attr, min_words, label):
    a = _answers()
    if a is None:
        return SKIP, "answers file not filled in"
    text = str(getattr(a, attr, "")).strip()
    words = len(text.split())
    if words < min_words:
        return FAIL, f"{words} words, expected at least {min_words}"
    return PASS, f"{words} words"


@check("You explained the incident root cause", "Understanding")
def _q_root():
    return _written("INCIDENT_ROOT_CAUSE", 8, "root cause")


@check("You named a prevention", "Understanding")
def _q_prev():
    return _written("INCIDENT_PREVENTION", 5, "prevention")


@check("You wrote up your observations", "Understanding")
def _q_obs():
    return _written("OBSERVATIONS", 30, "observations")


@check("You gave us feedback", "Understanding")
def _q_fb():
    return _written("FEEDBACK", 3, "feedback")


# ---------------------------------------------------------------------- main

def main():
    if not ANSWERS.exists():
        ANSWERS.write_text(ANSWERS_TEMPLATE, encoding="utf-8")
        print(f"\nCreated {ANSWERS.name}. Fill it in, then run this again.\n")

    print("\n" + "=" * 62)
    print("  GenAI onboarding self check")
    print("=" * 62)

    counts = {PASS: 0, FAIL: 0, SKIP: 0}
    section = None
    todo = []

    for sec, name, fn in results:
        if sec != section:
            print(f"\n{sec}")
            section = sec
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = FAIL, f"check errored: {type(e).__name__}"
        counts[status] += 1
        mark = {PASS: "[x]", FAIL: "[ ]", SKIP: "[-]"}[status]
        print(f"  {mark} {name}")
        if status != PASS:
            print(f"        {detail}")
            todo.append(name)
        elif detail:
            print(f"        {detail}")

    total = counts[PASS] + counts[FAIL] + counts[SKIP]
    print("\n" + "-" * 62)
    print(f"  {counts[PASS]} of {total} complete"
          f"   ({counts[FAIL]} outstanding, {counts[SKIP]} not attempted)")
    print("-" * 62)

    if not todo:
        print("\n  All done. Tell your onboarding buddy you are through,")
        print("  and bring your FEEDBACK answer to your first standup.\n")
    else:
        print("\n  Still to do:")
        for t in todo:
            print(f"    - {t}")
        print("\n  Stuck for more than 30 minutes? Ask. That is the correct move.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
