"""The classification quality gate, end to end (issue #197, stack 5).

Three kinds of check, from cheapest to most expensive:

1. **The real taxonomy walk with a perfect fake model.** The fake always picks
   the right answer from whatever choices it is offered, so any case it still
   gets wrong is lost by our code before a model is asked. This is how the
   elderly-router finding is proved offline.
2. **The committed live result.** It must have been measured on the code as
   it is now (fingerprint), and it must pass. This is the gate that catches a
   prompt edit in CI, without calling a model.
3. **A live smoke run**, marked `needs_network` and excluded by default.
"""

import contextlib
import io
import json
import os
import re
import sys
from types import SimpleNamespace

import pytest

import services.classification_service as cs
from evaluation import classification_eval as ev
from evaluation.golden_set import load_golden_set

pytestmark = pytest.mark.integration

CASES = load_golden_set()
EXPECTED_BY_DESCRIPTION = {case.description: case.expected_id for case in CASES}
ROUTER_FALSE_POSITIVES = sorted(c.id for c in CASES if "elderly-router-false-positive" in c.tags)


class _OracleGroq:
    """A fake Groq client that answers every prompt as well as it possibly can.

    It reads the candidate ids and the description out of the real prompt,
    looks up the golden label, and ranks first the candidate on the path to
    it. When no candidate is on the path, the right answer was never offered,
    and it falls back to the first candidate, as a model would have to.
    """

    def __init__(self):
        self.prompts = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                prompt = kwargs["messages"][0]["content"]
                outer.prompts.append(prompt)
                return outer._answer(prompt)

        self.chat = SimpleNamespace(completions=_Completions())

    @staticmethod
    def _answer(prompt):
        block = prompt.split("Categories:\n", 1)[1].split("\nDescription: ", 1)[0]
        candidates = re.findall(r"^([\d.]+):", block, re.M)
        description = prompt.split("\nDescription: ", 1)[1].split("\nReturn format", 1)[0]
        expected = EXPECTED_BY_DESCRIPTION.get(description) or ""
        on_path = [c for c in candidates if expected == c or expected.startswith(f"{c}.")]
        ranked = on_path + [c for c in candidates if c not in on_path]
        content = json.dumps({"categories": [{"category": c, "confidence": 0.9} for c in ranked[:3]]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def oracle(monkeypatch):
    """Install the perfect fake model as the classifier's only working provider."""
    fake = _OracleGroq()
    monkeypatch.setattr(cs, "client", fake)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", None)
    return fake


def _quiet_classify(description):
    """The production classifier, with its TOKEN_USAGE line kept out of the test output."""
    with contextlib.redirect_stdout(io.StringIO()):
        return cs.predict_categories(description)


# ---------------------------------------------------------------------------
# 1. The real walk, with a perfect model
# ---------------------------------------------------------------------------

def test_a_perfect_model_misses_only_the_router_false_positives(oracle):
    """Through our real prompts and taxonomy walk, perfect answers score 38/41.

    The three misses are exactly the cases the elderly router diverts: the
    right category is never offered, so no model could choose it. This is the
    ceiling our code puts on any model, measured without calling one.
    """
    report = ev.evaluate(CASES, _quiet_classify)
    misses = sorted(r.id for r in report.scored if not r.top_level_ok)
    assert misses == ROUTER_FALSE_POSITIVES
    assert len(report.scored) - len(misses) == 38 and not report.errors


def test_the_router_hides_the_right_branch_from_the_model(oracle):
    """"a senior in high school" is never offered College Application Help.

    The router skips the top-level choice and the only candidates sent are
    Elderly sub-categories (6.x). College Application Help is 4.1.
    """
    _quiet_classify("I am a senior in high school and need help with my college applications.")
    first_prompt = oracle.prompts[0]
    offered = re.findall(r"^([\d.]+):", first_prompt.split("Categories:\n", 1)[1], re.M)
    assert offered and all(c.startswith("6.") for c in offered)
    assert "4.1" not in offered


# ---------------------------------------------------------------------------
# 2. The committed live result
# ---------------------------------------------------------------------------

RECORDED = json.loads(ev.RESULTS_PATH.read_text(encoding="utf-8")) if ev.RESULTS_PATH.exists() else {}


def test_live_result_was_measured_on_the_current_classifier():
    """The committed score describes the prompts, models, router and labels in this tree.

    This is what fails when someone edits a prompt - for example drops
    "electrician" from the routing hint - and every other test still passes.
    Fix it by running: python tools/run_golden_set.py
    """
    assert RECORDED, "no committed live result; run: python tools/run_golden_set.py"
    assert RECORDED["fingerprint"] == ev.fingerprint(), ev.check_results()[0]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known failure, reported in #197 stack 5: the elderly router in "
        "utils/routing_for_categories.py diverts housing-10, housing-11 and "
        "education-07 to Elderly-only choices, three misses no model can "
        "avoid. Together with the model's own misses (clothing-02, food-03) "
        "they keep the score below the pass mark. Strict, so this marker "
        "must be removed once a live run passes."
    ),
)
def test_live_result_passes_the_pass_mark():
    """The last live run scored at or above the pass mark with no errors."""
    assert RECORDED.get("passed") is True


# ---------------------------------------------------------------------------
# 3. Live smoke run
# ---------------------------------------------------------------------------

@pytest.mark.needs_network
def test_live_model_classifies_routing_hint_cases():
    """The real models answer the routing-hint cases with no errors.

    A wiring check against the live provider, using the key in .env. It does
    not judge quality - five cases cannot - that is the full live run's job
    (tools/run_golden_set.py) and the committed result it writes.
    """
    sys.path.insert(0, str(ev.REPO_ROOT / "tools"))
    from measure_token_baseline import install_clients, load_env

    env = load_env()
    groq_key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
    gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    if not (groq_key or gemini_key):
        pytest.skip("no GROQ_API_KEY or GEMINI_API_KEY in .env or the environment")
    with contextlib.redirect_stdout(io.StringIO()):
        install_clients(groq_key, gemini_key)

    cases = [c for c in CASES if "routing-hint" in c.tags or "baseline" in c.tags][:5]
    report = ev.evaluate(cases, _quiet_classify)
    assert not report.errors, [r.error for r in report.errors]
    assert all(r.predicted for r in report.results)
