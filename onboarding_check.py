"""
GenAI onboarding self check.

Run this when you think you are done. It checks your setup, your safety habits,
and whether you actually explored the code. Nothing is uploaded anywhere and no
one sees the result unless you share it.

    python onboarding_check.py

First run creates onboarding_answers.py for you to fill in. Fill it, run again.

This file also carries Mission 2's harness:

    python onboarding_check.py -i

which classifies whatever you type against the real code on dev, using your own
Groq key. See interactive() for why that lives here rather than in a separate
local_dev_harness.py.

The checks that read the real service only run on dev. This script is tracked
on the NewJoineeTask lineage, so `git checkout dev` deletes it. Mission 2 tells
you to restore it afterwards - in that order, because a copy made beforehand is
removed by the checkout too:

    git checkout dev
    git show NewJoineeTask:onboarding_check.py > onboarding_check.py
"""
import ast
import contextlib
import importlib
import io
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


# --- Mission 2.5: the architecture ------------------------------------------

# lambda_function.py has a unified router, lambda_handler, which picks a service
# out of the request and calls that service's handler. How many services can it
# dispatch to? (an integer). ARCHITECTURE_MAP.md draws this.
ROUTER_SERVICE_COUNT = 0

# Name one CONTRACT test from tests/ that you read. The test function name is
# enough, e.g. "test_something"; a full "tests/test_file.py::test_something"
# also works. docs/testing/TEST_CATALOGUE.md says which files are contract
# tests.
CONTRACT_TEST = ""

# In your own words: what behaviour does that test protect, and what would
# break for the web client if it started failing?
CONTRACT_TEST_PROTECTS = ""


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


# ------------------------------------------------------------------ plumbing

@contextlib.contextmanager
def _quiet():
    """Swallow whatever an import prints on its way in.

    utils/client.py announces its Parameter Store bootstrap the moment it is
    imported: four INIT LOG lines, plus a boto3 error when there are no AWS
    credentials, which is the normal case for a joiner. That is useful in
    CloudWatch and pure noise in the middle of a checklist.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


ON_DEV_HINT = ("you are on the sandbox branch. Do Mission 2: git checkout dev, then "
               "restore this script from NewJoineeTask and run it again")
NO_ANSWERS_HINT = ("onboarding_answers.py is not filled in yet. Run this once to create "
                   "it, answer the questions, then run it again")


def _on_dev():
    """The later missions run against the real code on dev. The sandbox branch
    does not have these files, which is expected, not a broken setup."""
    return (ROOT / "services" / "classification_service.py").exists()


def _dev_guard():
    """The SKIP result every dev-only check shares, or None to carry on.

    Every check that reads the real service starts with this, so being on the
    sandbox branch always reports the same thing. Getting the order wrong is
    how a check ends up telling someone "PREDICT_HANDLER is empty" when their
    actual problem is that they have not switched branches yet.
    """
    if not _on_dev():
        return SKIP, ON_DEV_HINT
    return None


# --------------------------------------------------------------- environment

@check("Python 3.11 or newer", "Setup")
def _py():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return (PASS if ok else FAIL), f"found {v.major}.{v.minor}.{v.micro}"


@check("Required packages installed", "Setup")
def _pkgs():
    # langchain_groq is only needed against the real service: it is what
    # utils/client.py builds its chat model with, and what the harness below
    # rebuilds locally. The sandbox app never imports it and
    # NewJoineeTask/requirements.txt does not list it, so demanding it on the
    # sandbox branch is a dead end - the remedy the failure message suggests is
    # the command the joiner has just run.
    required = ["groq", "dotenv"] + (["langchain_groq"] if _on_dev() else [])
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        branch = "dev" if _on_dev() else "NewJoineeTask"
        return FAIL, (f"missing: {', '.join(missing)}. "
                      f"On {branch}, run: pip install -r requirements.txt")
    return PASS, ", ".join(required)


@check("GROQ_API_KEY is available", "Setup")
def _key():
    if os.getenv("GROQ_API_KEY"):
        return PASS, "found in environment"
    env = ROOT / ".env"
    if env.exists() and "GROQ_API_KEY" in env.read_text(encoding="utf-8", errors="ignore"):
        return PASS, "found in .env"
    return FAIL, "not found. Put GROQ_API_KEY in a .env file"


# -------------------------------------------------------------------- safety

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


# Directories holding somebody else's code rather than yours. site-packages is
# full of test fixtures carrying example keys, and walking it turns a two
# second check into a minute of false positives. Both venv spellings appear:
# the README creates .venv, and .gitignore permits venv too.
_SKIP_DIRS = {".venv", "venv", "env", "site-packages", "node_modules",
              "__pycache__", ".git", "package"}


@check("No API key hardcoded in your Python files", "Safety")
def _no_hardcoded():
    # Groq keys start gsk_, AWS access key ids start AKIA.
    pat = re.compile(r"(gsk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
    hits = []
    for p in ROOT.rglob("*.py"):
        if _SKIP_DIRS.intersection(p.parts) or p.name == Path(__file__).name:
            continue
        try:
            if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(ROOT)))
        except OSError:
            pass
    if hits:
        return FAIL, f"possible key in: {', '.join(hits[:3])}. Move it to .env"
    return PASS, "clean"


# ---------------------------------------------------------- it actually runs

def _local_key():
    """Your Groq key, from the environment or from .env."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    return os.getenv("GROQ_API_KEY") or dotenv_values(ROOT / ".env").get("GROQ_API_KEY")


@check("A real call to the model succeeds", "It runs")
def _live_call():
    try:
        from groq import Groq
    except ImportError:
        return SKIP, "packages missing"
    key = _local_key()
    if not key:
        return SKIP, "no key"
    model = "openai/gpt-oss-20b"
    if _on_dev():
        try:
            with _quiet():
                from utils.client import GROQ_MODEL
            model = GROQ_MODEL
        except Exception:
            pass
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


def _wire_local_client():
    """Inject the .env key the way AWS Parameter Store would in the real service.
    Without this the client has no key locally and falls through to Gemini."""
    from groq import Groq
    from langchain_groq import ChatGroq
    with _quiet():
        import utils.client as C

    if C._use_groq and C.client:
        return True
    key = _local_key()
    if not key:
        return False
    C.GROQ_API_KEY = key
    C.client = Groq(api_key=key)
    C._use_groq = True
    kw = dict(api_key=key, model=C.GROQ_MODEL, temperature=C.GROQ_TEMPERATURE)
    if "gpt-oss" in C.GROQ_MODEL:
        kw["reasoning_effort"] = "low"
    C.groq_llm = ChatGroq(**kw)
    # Disabling Gemini here is deliberate. Mission 3 is about a silent fallback
    # hiding a failure; a harness that quietly answers from the other provider
    # would hide the exact thing you are here to see.
    C._gemini_client = None
    C.gemini_llm = None
    C._use_gemini = False
    return True


@check("Classification returns a real category", "It runs")
def _classify():
    guard = _dev_guard()
    if guard:
        return guard
    try:
        if not _wire_local_client():
            return SKIP, "no key to run with"
        with _quiet():
            from services.classification_service import predict_categories
    except Exception as e:
        return FAIL, f"cannot import classifier: {type(e).__name__}"
    try:
        # The service logs a line per level of the taxonomy descent. Worth
        # seeing in -i, where watching the descent is the point; noise in the
        # middle of a checklist.
        with _quiet():
            res, _usage = predict_categories("I need help with math")
    except Exception as e:
        return FAIL, f"{type(e).__name__}: {str(e)[:70]}"
    if not res:
        return FAIL, "returned nothing. This is exactly the Mission 3 failure"
    top = res[0]
    if str(top.get("category_name", "")).upper().startswith("GENERAL"):
        return FAIL, "got GENERAL for a clear maths request, something is wrong"
    return PASS, f"{top.get('category_name')} at {top.get('confidence')}"


# ------------------------------------------------------------- comprehension

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


def _answered(attr):
    """(answers module, stripped value), or (None, result) to return as is."""
    a = _answers()
    if a is None:
        return None, (SKIP, NO_ANSWERS_HINT)
    return a, str(getattr(a, attr, "")).strip()


@check("You found the taxonomy file", "Reading the code")
def _q_taxonomy():
    guard = _dev_guard()
    if guard:
        return guard
    a, got = _answered("TAXONOMY_FILE")
    if a is None:
        return got
    got = got.replace("\\", "/")
    if not got:
        return FAIL, "TAXONOMY_FILE is empty"
    path = ROOT / got
    if not path.is_file():
        return FAIL, f"'{got}' is not a file in this checkout. Look in utils/"
    if path.suffix != ".py":
        return FAIL, f"'{got}' is not a Python module"
    # Verified against the code rather than a stored answer key: a taxonomy
    # module is one that actually declares the mapping - help_categories, the
    # id-to-name tree the classifier walks, or TAXONOMY, the name-to-description
    # text the prompt is built from. A module that merely imports one of them,
    # like services/classification_service.py, does not count.
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not re.search(r"^(help_categories|TAXONOMY)\s*=", text, re.MULTILINE):
        return FAIL, (f"'{got}' exists but declares neither help_categories nor "
                      "TAXONOMY. The taxonomy file is the one that defines the "
                      "categories, not one that imports them")
    return PASS, got


@check("You counted the top level categories", "Reading the code")
def _q_count():
    guard = _dev_guard()
    if guard:
        return guard
    a, fallback = _answered("TOP_LEVEL_COUNT")
    if a is None:
        return fallback
    try:
        with _quiet():
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
    guard = _dev_guard()
    if guard:
        return guard
    a, got = _answered("PREDICT_HANDLER")
    if a is None:
        return got
    got = got.lower().replace("()", "")
    if not got:
        return FAIL, "PREDICT_HANDLER is empty"
    try:
        src = (ROOT / "lambda_function.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return SKIP, "lambda_function.py not found"
    if re.search(rf"def\s+{re.escape(got)}\s*\(", src):
        return PASS, got
    return FAIL, f"no function named '{got}' in lambda_function.py"


def _router_services():
    """The handlers lambda_handler can dispatch to, read out of the source
    rather than stored here, so this cannot go stale when a service is added
    or removed."""
    try:
        tree = ast.parse((ROOT / "lambda_function.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    router = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler"), None)
    if router is None:
        return None
    return {c.func.id for c in ast.walk(router)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id.endswith("_handler")}


@check("You mapped the router", "Reading the code")
def _q_router():
    guard = _dev_guard()
    if guard:
        return guard
    a, fallback = _answered("ROUTER_SERVICE_COUNT")
    if a is None:
        return fallback
    services = _router_services()
    if not services:
        return SKIP, "cannot read lambda_handler out of lambda_function.py"
    got = getattr(a, "ROUTER_SERVICE_COUNT", 0)
    if got == len(services):
        return PASS, f"{got}: {', '.join(sorted(services))}"
    return FAIL, (f"you said {got}. Read lambda_handler in lambda_function.py and count "
                  "the handlers it can call. ARCHITECTURE_MAP.md draws it")


@check("You read a contract test", "Reading the code")
def _q_contract():
    guard = _dev_guard()
    if guard:
        return guard
    a, got = _answered("CONTRACT_TEST")
    if a is None:
        return got
    if not got:
        return FAIL, "CONTRACT_TEST is empty. See docs/testing/TEST_CATALOGUE.md"
    name = got.split("::")[-1].strip().replace("()", "")
    tests = ROOT / "tests"
    if not tests.is_dir():
        return SKIP, "no tests/ directory in this checkout"
    found = None
    for p in sorted(tests.glob("test_*.py")):
        body = p.read_text(encoding="utf-8", errors="ignore")
        if re.search(rf"def\s+{re.escape(name)}\s*\(", body):
            found = p.name
            break
    if not found:
        return FAIL, (f"no test named '{name}' under tests/. "
                      "Run: python -m pytest -q --collect-only")
    words = len(str(getattr(a, "CONTRACT_TEST_PROTECTS", "")).split())
    if words < 12:
        return FAIL, (f"found {name} in tests/{found}, but CONTRACT_TEST_PROTECTS is "
                      f"{words} words, expected at least 12")
    return PASS, f"{name} in tests/{found}, explained in {words} words"


# ------------------------------------------------------------------- written

def _written(attr, min_words, label):
    a, text = _answered(attr)
    if a is None:
        return text
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


# --------------------------------------------------------------- the harness

def interactive():
    """Mission 2's harness: classify what you type, against the real code.

    utils/client.py reads its Groq key from AWS Systems Manager Parameter Store
    in us-east-1, which you do not have access to. _wire_local_client() puts
    your own key into the same module attributes Parameter Store would have
    filled, so everything past that point - the prompt, the hierarchical
    descent, the parsing - is the deployed code path unchanged.

    This is why Mission 2 does not need a separate local_dev_harness.py. dev
    deliberately gitignores that file ("injects a local key; never deploy or
    commit"), and the wiring it performed already had to exist here for the
    classification check. One file, one mechanism, and no contradiction with a
    decision already taken on dev.
    """
    if not _on_dev():
        print("\n  This runs the real service, which only exists on dev.")
        print("  " + ON_DEV_HINT + "\n")
        return 1
    try:
        if not _wire_local_client():
            print("\n  No GROQ_API_KEY found. Put one in .env, then try again.\n")
            return 1
        with _quiet():
            from services.classification_service import predict_categories
    except Exception as e:
        print(f"\n  Could not load the classifier: {type(e).__name__}: {e}\n")
        return 1

    print("\n  Local harness. Your key, the real classifier, Gemini fallback off.")
    print("  Type a description and press Enter. An empty line or Ctrl+C quits.\n")
    while True:
        try:
            text = input("  description> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            return 0
        try:
            res, usage = predict_categories(text)
        except Exception as e:
            print(f"    failed: {type(e).__name__}: {str(e)[:100]}\n")
            continue
        if not res:
            print("    nothing returned. The web client shows General when this happens,"
                  " which is the Mission 3 failure.\n")
            continue
        for r in res:
            print(f"    {r.get('confidence')}  {r.get('category_name')}"
                  f"  [{r.get('category_number')}]")
            print(f"        {r.get('hierarchy')}")
        print(f"    {usage.get('total_calls')} model calls,"
              f" {usage.get('total_tokens')} tokens\n")


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
    todo, not_attempted = [], []

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
        if detail:
            print(f"        {detail}")
        if status == FAIL:
            todo.append(name)
        elif status == SKIP:
            not_attempted.append(name)

    total = counts[PASS] + counts[FAIL] + counts[SKIP]
    print("\n" + "-" * 62)
    print(f"  {counts[PASS]} of {total} complete"
          f"   ({counts[FAIL]} outstanding, {counts[SKIP]} not attempted)")
    print("-" * 62)

    if not todo and not not_attempted:
        print("\n  All done. Tell your onboarding buddy you are through,")
        print("  and bring your FEEDBACK answer to your first standup.\n")
        return 0

    # Two lists, not one. A failed check is something you got wrong; a skipped
    # one is something you have not reached yet, usually because you are still
    # on the sandbox branch. Pooling them made the count above disagree with
    # the list below.
    if todo:
        print("\n  Still to do:")
        for t in todo:
            print(f"    - {t}")
    if not_attempted:
        print("\n  Not attempted yet (finish the mission that unlocks these):")
        for t in not_attempted:
            print(f"    - {t}")
    print("\n  Stuck for more than 30 minutes? Ask. That is the correct move.\n")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if argv and argv[0] in ("-i", "--interactive"):
        sys.exit(interactive())
    sys.exit(main())
