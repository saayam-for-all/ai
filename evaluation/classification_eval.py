"""Score the category classifier against the golden set, and gate on the score.

Three questions, answered in that order:

1. **Is it right?** `evaluate` runs every golden case through the real
   `predict_categories` - prompts, taxonomy walk, elderly routing and model
   fallback included - and scores the answers.
2. **Is it good enough?** `EvalReport.passed` applies the pass mark. Errors
   fail the gate on their own: a case that could not be classified is not a
   case that was classified correctly.
3. **Is the last answer still current?** `fingerprint` hashes everything that
   decides what the classifier answers. The committed result of the last live
   run records the fingerprint it was measured at, and `check_results` fails
   when the code has moved on since. That is what lets an offline test suite
   catch a prompt edit: it cannot judge the new prompt, but it can refuse to
   accept a score that was measured on the old one.

Scoring uses two measures, because they fail for different reasons:

  * **top-level accuracy** (the gate): the first ranked answer is in the right
    branch of the taxonomy, for example Housing. A wrong branch sends the
    request to the wrong volunteers, which is the failure that matters.
  * **path accuracy** (reported): the expected category, or one of its
    children, appears anywhere in the top three. This measures how precise the
    classifier is inside the right branch.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from evaluation.golden_set import GOLDEN_SET_PATH, GoldenCase
from utils.predict_category_list import (
    category_name_to_number,
    get_direct_children,
    get_top_level_categories,
    help_categories,
)
from utils import routing_for_categories

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "docs" / "metrics" / "golden_set_classification.json"
REPORT_PATH = REPO_ROOT / "docs" / "metrics" / "GOLDEN_SET_CLASSIFICATION.md"
MODEL_ROUTING_PATH = REPO_ROOT / "config" / "model_routing.json"

#: Share of scored cases whose first answer must be in the right branch. A
#: model is not deterministic at temperature 0.8, so the mark leaves room for
#: the odd borderline case to flip between runs without failing the gate.
PASS_MARK = 0.90

#: The id the general category uses. It is the only top-level id with dots.
GENERAL_ID = "0.0.0.0.0"

Classifier = Callable[[str], tuple]


def top_level_of(category_id: str | None) -> str | None:
    """The top-level branch of a taxonomy id: "3.3.1" -> "3", general -> "0"."""
    if not category_id:
        return None
    if category_id == GENERAL_ID:
        return "0"
    return category_id.split(".")[0]


def _within(category_id: str, expected_id: str) -> bool:
    """Whether `category_id` is `expected_id` or one of its descendants."""
    return category_id == expected_id or category_id.startswith(f"{expected_id}.")


@dataclass
class CaseResult:
    """What happened to one golden case.

    `predicted` holds the ranked category ids exactly as the service returned
    them. `models` lists the provider/model of every model call that answered,
    so a reader can tell a Groq answer from a Gemini fallback.
    """

    id: str
    description: str
    expected: str | None
    scored: bool
    predicted: list[str] = field(default_factory=list)
    top_level_ok: bool = False
    path_ok: bool = False
    elderly_routed: bool = False
    error: str | None = None
    models: list[str] = field(default_factory=list)
    total_tokens: int = 0

    @property
    def predicted_names(self) -> list[str]:
        """The predicted ids as category names, for reports."""
        return [help_categories.get(cid, cid) for cid in self.predicted]


@dataclass
class EvalReport:
    """The scored outcome of one run over the golden set."""

    results: list[CaseResult]
    fingerprint: str
    pass_mark: float = PASS_MARK
    measured_at: str = ""

    @property
    def scored(self) -> list[CaseResult]:
        """Results that count towards the score (known gaps excluded)."""
        return [r for r in self.results if r.scored]

    @property
    def errors(self) -> list[CaseResult]:
        """Scored cases the classifier could not answer at all."""
        return [r for r in self.scored if r.error]

    @property
    def top_level_accuracy(self) -> float:
        """Share of scored cases whose first answer is in the right branch."""
        scored = self.scored
        return sum(r.top_level_ok for r in scored) / len(scored) if scored else 0.0

    @property
    def path_accuracy(self) -> float:
        """Share of scored cases with the expected category in the top three."""
        scored = self.scored
        return sum(r.path_ok for r in scored) / len(scored) if scored else 0.0

    @property
    def passed(self) -> bool:
        """The gate: no errors, and top-level accuracy at or above the mark."""
        return not self.errors and self.top_level_accuracy >= self.pass_mark

    def by_branch(self) -> dict[str, tuple[int, int]]:
        """(correct, total) per expected top-level branch, keyed by its name."""
        totals: Counter = Counter()
        correct: Counter = Counter()
        for result in self.scored:
            branch = help_categories.get(_branch_id(result.expected), "?")
            totals[branch] += 1
            correct[branch] += result.top_level_ok
        return {branch: (correct[branch], totals[branch]) for branch in totals}

    def to_dict(self) -> dict:
        """A JSON-ready record of the run, as committed to docs/metrics/."""
        models = Counter(model for r in self.results for model in r.models)
        return {
            "measured_at": self.measured_at,
            "fingerprint": self.fingerprint,
            "pass_mark": self.pass_mark,
            "passed": self.passed,
            "scored_cases": len(self.scored),
            "top_level_accuracy": round(self.top_level_accuracy, 4),
            "path_accuracy": round(self.path_accuracy, 4),
            "errors": len(self.errors),
            "total_tokens": sum(r.total_tokens for r in self.results),
            "models": dict(models.most_common()),
            "results": [asdict(r) for r in self.results],
        }


def _branch_id(category_name: str | None) -> str | None:
    """Top-level id for a category name, or None for a known gap."""
    return top_level_of(category_name_to_number.get(category_name or ""))


def _default_classifier() -> Classifier:
    """The production classifier, imported late so tests can stub the clients."""
    from services.classification_service import predict_categories

    return predict_categories


def run_case(case: GoldenCase, classify: Classifier) -> CaseResult:
    """Classify one case and score it.

    Any exception is recorded on the result rather than raised. One dead case,
    a rate limit or an exhausted model chain, must not throw away the rest of
    a paid run; the gate still fails on it.
    """
    result = CaseResult(
        id=case.id,
        description=case.description,
        expected=case.expected,
        scored=case.scored,
        elderly_routed=routing_for_categories.is_elderly_context(case.description),
    )
    try:
        ranked, usage = classify(case.description)
    except Exception as error:  # noqa: BLE001 - recorded, and fails the gate
        result.error = f"{type(error).__name__}: {error}"
        return result

    result.predicted = [str(item.get("category_number")) for item in ranked or []]
    calls = (usage or {}).get("calls", [])
    result.models = [f"{call.get('provider')}/{call.get('model')}" for call in calls]
    result.total_tokens = int((usage or {}).get("total_tokens", 0) or 0)

    expected_id = case.expected_id
    if expected_id and result.predicted:
        result.top_level_ok = top_level_of(result.predicted[0]) == top_level_of(expected_id)
        result.path_ok = any(_within(cid, expected_id) for cid in result.predicted[:3])
    return result


def evaluate(
    cases: Iterable[GoldenCase],
    classify: Classifier | None = None,
    *,
    pass_mark: float = PASS_MARK,
    on_result: Callable[[CaseResult], None] | None = None,
) -> EvalReport:
    """Run every case through `classify` and return the scored report.

    `classify` defaults to the production `predict_categories`. Tests pass a
    stub; the live runner passes nothing. `on_result` is called after each
    case, so a long live run can show progress.
    """
    classify = classify or _default_classifier()
    results = []
    for case in cases:
        result = run_case(case, classify)
        results.append(result)
        if on_result:
            on_result(result)
    return EvalReport(
        results=results,
        fingerprint=fingerprint(),
        pass_mark=pass_mark,
        measured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# Fingerprint: everything that decides what the classifier answers
# ---------------------------------------------------------------------------

def _classifier_inputs() -> dict:
    """Collect every input that can change a classification, as plain data.

    * every prompt the taxonomy walk can send - one per category that has
      children, plus the top level - built with a placeholder description, so
      a change to any template, routing hint or category description shows;
    * the sampling settings the service is constructed with;
    * the model chain, which decides which model answers;
    * the elderly routing word lists, which decide where the walk starts;
    * the golden set itself, so a relabelled case also needs a fresh run.
    """
    from services.classification_service import GroqClassificationService

    service = GroqClassificationService()
    placeholder = "<DESCRIPTION>"
    prompts = {
        "<top-level>": service._build_ranked_prompt_for_candidates(
            placeholder, get_top_level_categories()
        )
    }
    for category_id in help_categories:
        children = get_direct_children(category_id)
        if children:
            prompts[category_id] = service._build_ranked_prompt_for_candidates(
                placeholder, children
            )

    return {
        "prompts": prompts,
        "sampling": {"temperature": service.temperature, "top_p": service.top_p},
        "model_chain": json.loads(MODEL_ROUTING_PATH.read_text(encoding="utf-8")),
        "elderly_routing": {
            name: list(getattr(routing_for_categories, name))
            for name in ("STRONG_ELDERLY_TRIGGERS", "WEAK_ELDERLY_TRIGGERS", "ELDERLY_CONTEXT_CUES")
        },
        "golden_set": GOLDEN_SET_PATH.read_text(encoding="utf-8").replace("\r\n", "\n"),
    }


def fingerprint() -> str:
    """A short, stable hash of `_classifier_inputs()`.

    Twelve hex characters is plenty to tell two versions apart and short
    enough to quote in a review comment.
    """
    canonical = json.dumps(_classifier_inputs(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def check_results(path: Path = RESULTS_PATH) -> list[str]:
    """Problems with the committed live result, or an empty list if it holds.

    This is the offline quality gate. It fails when there is no result, when
    the result was measured on different prompts, models or labels than the
    code now has, or when the result itself did not pass.
    """
    rerun = "Rerun: python tools/run_golden_set.py"
    if not path.exists():
        return [f"No live evaluation result at {path.name}. {rerun}"]
    recorded = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    current = fingerprint()
    if recorded.get("fingerprint") != current:
        problems.append(
            f"The classifier changed since the last live evaluation "
            f"(measured at {recorded.get('fingerprint')}, now {current}): a "
            f"prompt, the model chain, the elderly routing or the golden set. {rerun}"
        )
    if not recorded.get("passed"):
        problems.append(
            f"The last live evaluation did not pass: top-level accuracy "
            f"{recorded.get('top_level_accuracy')} against a pass mark of "
            f"{recorded.get('pass_mark')}, with {recorded.get('errors')} error(s)."
        )
    return problems


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_markdown(report: EvalReport) -> str:
    """A short human-readable summary of `report`, for docs/metrics/."""
    verdict = "PASSED" if report.passed else "FAILED"
    scored = report.scored
    lines = [
        "# Classification golden set: latest live result",
        "",
        "Generated by `tools/run_golden_set.py`. Do not edit by hand; the JSON",
        "next to this file is what `tests/test_classification_eval.py` checks.",
        "",
        f"- **Result:** {verdict} (pass mark {report.pass_mark:.0%} top-level accuracy, no errors)",
        f"- **Measured:** {report.measured_at}, fingerprint `{report.fingerprint}`",
        f"- **Top-level accuracy:** {sum(r.top_level_ok for r in scored)}/{len(scored)}"
        f" ({report.top_level_accuracy:.0%})",
        f"- **Path accuracy (expected category in top 3):** "
        f"{sum(r.path_ok for r in scored)}/{len(scored)} ({report.path_accuracy:.0%})",
        f"- **Errors:** {len(report.errors)}",
        f"- **Tokens:** {sum(r.total_tokens for r in report.results):,}",
        "",
        "## By branch",
        "",
        "| Expected branch | Correct |",
        "| --- | ---: |",
    ]
    for branch, (correct, total) in sorted(report.by_branch().items()):
        lines.append(f"| {branch} | {correct}/{total} |")

    misses = [r for r in scored if r.error or not (r.top_level_ok and r.path_ok)]
    lines += ["", "## Misses", ""]
    if misses:
        lines += ["| Case | Expected | Got (top 3) | Wrong | Elderly routed |", "| --- | --- | --- | --- | --- |"]
        for r in misses:
            got = r.error or ", ".join(r.predicted_names[:3]) or "(empty)"
            wrong = "error" if r.error else ("branch" if not r.top_level_ok else "detail")
            routed = "yes" if r.elderly_routed else ""
            lines.append(f"| `{r.id}` | {r.expected} | {got} | {wrong} | {routed} |")
    else:
        lines.append("None.")

    gaps = [r for r in report.results if not r.scored]
    if gaps:
        lines += [
            "",
            "## Known gaps (not scored)",
            "",
            "Requests the taxonomy has no category for. Shown so the gap stays visible.",
            "",
            "| Case | Landed in |",
            "| --- | --- |",
        ]
        for r in gaps:
            lines.append(f"| `{r.id}` | {r.error or ', '.join(r.predicted_names[:1]) or '(empty)'} |")
    return "\n".join(lines) + "\n"
