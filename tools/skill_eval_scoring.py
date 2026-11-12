"""Score volunteer skill suggestions against a labelled set (issue #216).

Issue #216 asks for "recall >= 80% and precision >= 80%" without saying how
either is counted.  Two people scoring the same run by eye would not agree, so
the definition lives here, in code, with tests.

The unit being counted is a **skill**, not a category ID.  A case labels the
skills a volunteer stated, and each skill carries a set of acceptable IDs,
because parts of the taxonomy say the same thing twice: 5.1.1 General
Consultation against 5.1.11 Other Medical Concern, 6.5 Errands Events
Transportation against 6.6 Transportation Appointments Events.  A model that
picks either is right, and scoring it wrong would measure the taxonomy rather
than the model.

    true positive   a labelled skill matched by a predicted ID
    false negative  a labelled skill no prediction matched
    false positive  a predicted ID left over once skills are matched

Pairing is a **maximum bipartite matching**, not a greedy walk.  Greedy is
order-dependent and can undercount: with skills [{X, Y}, {X}] and predictions
X, Y, taking X for the first skill strands the second, scoring 1 where 2 was
available.  The model should not lose a point to the order the labels happen
to be written in.  Ties are broken towards the higher-confidence prediction so
that *which* prediction is credited is deterministic, though the totals do not
depend on it.

Totals are aggregated **micro** - sum the counts, then divide - because macro
averaging would give a one-skill case the same weight as a five-skill one, and
would let the no-match cases, which have no skills at all, dominate.

This module is pure.  No I/O, no network, no model.  The harness that does
call models is tools/measure_skill_suggestion_accuracy.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Prediction:
    """One suggested category, as the service returns it."""

    category_id: str
    confidence: float = 0.0


@dataclass(frozen=True)
class ExpectedSkill:
    """One labelled skill and the category IDs that may stand for it."""

    skill: str
    accept: frozenset[str]


@dataclass
class CaseScore:
    """What happened on one case, in enough detail to put in a report."""

    case_id: str
    traits: tuple[str, ...] = ()
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    #: skill name -> the category ID that matched it
    matched: dict[str, str] = field(default_factory=dict)
    #: labelled skills nothing matched
    missed: list[str] = field(default_factory=list)
    #: predicted IDs left over
    spurious: list[str] = field(default_factory=list)
    error: str | None = None


def to_expected(raw_expected) -> list[ExpectedSkill]:
    """Read the `expected` list of an evaluation case."""
    skills = []
    for entry in raw_expected or []:
        skills.append(
            ExpectedSkill(
                skill=str(entry["skill"]),
                accept=frozenset(str(i) for i in entry["accept"]),
            )
        )
    return skills


def to_predictions(raw_categories) -> list[Prediction]:
    """Read the `categories` list of a volunteer_skills response."""
    predictions = []
    for entry in raw_categories or []:
        predictions.append(
            Prediction(
                category_id=str(entry.get("category_number", "")),
                confidence=float(entry.get("confidence", 0.0) or 0.0),
            )
        )
    return predictions


def _maximum_matching(
    expected: list[ExpectedSkill], predictions: list[Prediction]
) -> dict[int, int]:
    """Pair skills to predictions, maximising how many skills are covered.

    Kuhn's augmenting-path algorithm.  The sets here are tiny - at most six
    predictions against a handful of skills - so the simple O(V*E) form is
    both fast enough and easy to check by hand.

    Returns {skill index: prediction index}.
    """
    # Highest confidence first, so an arbitrary choice between two equally
    # valid pairings always lands on the prediction the model was surest of.
    order = sorted(
        range(len(predictions)),
        key=lambda i: (-predictions[i].confidence, predictions[i].category_id),
    )

    skill_of_prediction: dict[int, int] = {}

    def augment(skill_index: int, visited: set[int]) -> bool:
        for prediction_index in order:
            if predictions[prediction_index].category_id not in expected[skill_index].accept:
                continue
            if prediction_index in visited:
                continue
            visited.add(prediction_index)
            holder = skill_of_prediction.get(prediction_index)
            if holder is None or augment(holder, visited):
                skill_of_prediction[prediction_index] = skill_index
                return True
        return False

    for skill_index in range(len(expected)):
        augment(skill_index, set())

    return {skill: prediction for prediction, skill in skill_of_prediction.items()}


def score_case(
    case_id: str,
    expected: list[ExpectedSkill],
    predictions: list[Prediction],
    traits: tuple[str, ...] = (),
    error: str | None = None,
) -> CaseScore:
    """Score one case.

    A case that errored scores every labelled skill as missed.  Treating a
    provider outage as "no false positives, nothing to see" would quietly
    flatter the run.
    """
    score = CaseScore(case_id=case_id, traits=tuple(traits), error=error)

    if error:
        score.false_negatives = len(expected)
        score.missed = [s.skill for s in expected]
        return score

    matching = _maximum_matching(expected, predictions)
    used = set(matching.values())

    for skill_index, skill in enumerate(expected):
        prediction_index = matching.get(skill_index)
        if prediction_index is None:
            score.missed.append(skill.skill)
        else:
            score.matched[skill.skill] = predictions[prediction_index].category_id

    score.spurious = [
        p.category_id for i, p in enumerate(predictions) if i not in used
    ]
    score.true_positives = len(score.matched)
    score.false_negatives = len(score.missed)
    score.false_positives = len(score.spurious)
    return score


def _ratio(numerator: int, denominator: int) -> float | None:
    """A rate, or None when nothing was counted.

    None rather than 0.0 on purpose: a run that predicted nothing at all has
    undefined precision, and reporting that as 0% would read as "the model was
    always wrong" rather than "the model never answered".
    """
    if denominator == 0:
        return None
    return numerator / denominator


def aggregate(scores: list[CaseScore]) -> dict:
    """Micro-average a list of case scores."""
    tp = sum(s.true_positives for s in scores)
    fp = sum(s.false_positives for s in scores)
    fn = sum(s.false_negatives for s in scores)
    recall = _ratio(tp, tp + fn)
    precision = _ratio(tp, tp + fp)

    f1 = None
    if recall is not None and precision is not None and (recall + precision) > 0:
        f1 = 2 * recall * precision / (recall + precision)

    return {
        "cases": len(scores),
        "errors": sum(1 for s in scores if s.error),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def aggregate_by_trait(scores: list[CaseScore]) -> dict[str, dict]:
    """Micro-average per trait.

    A 59-case total that clears 80% while non_english sits at 30% is the
    failure this breakdown exists to expose.  Cases carry several traits, so
    these buckets overlap and do not sum to the overall figure.
    """
    traits = sorted({trait for score in scores for trait in score.traits})
    return {
        trait: aggregate([s for s in scores if trait in s.traits]) for trait in traits
    }


def false_suggestion_rate(scores: list[CaseScore]) -> dict:
    """How often the model invents a skill for a description that states none.

    Recall and precision both hide this.  A no-match case has no labelled
    skills, so it cannot lower recall, and its false positives are diluted by
    every other case.  "I am free on weekends" coming back with three
    confident suggestions is the behaviour the web app would show a volunteer,
    so it gets its own number.
    """
    no_match = [s for s in scores if not s.error and not s.matched and not s.missed]
    invented = [s for s in no_match if s.false_positives]
    return {
        "cases": len(no_match),
        "cases_with_suggestions": len(invented),
        "suggestions": sum(s.false_positives for s in no_match),
        "rate": _ratio(len(invented), len(no_match)),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile: the smallest value with `fraction` at or below it.

    Nearest-rank rather than interpolated so that the reported p95 is a latency
    some case really had.
    """
    if not values:
        return None
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    ordered = sorted(values)
    rank = math.ceil(fraction * len(ordered))
    return ordered[rank - 1]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_statistics(rows: list[dict], primary_model: str | None = None) -> dict:
    """Cost, latency and reliability of one pass, from the harness's case rows.

    Accuracy says whether the answers were right. This says what they cost and
    how they were produced, which is what shows whether a smaller prompt saved
    tokens and whether the numbers describe the primary model at all: a case
    that failed over was answered by a different model.

    Rows written by an older harness lack the newer fields; those count as
    zero or are left out, never guessed.
    """
    explanation_rows = [r["explanations"] for r in rows if r.get("explanations")]
    suggestions = sum(e["suggestions"] for e in explanation_rows)
    user_said = sum(e["with_user_said"] for e in explanation_rows)
    why = sum(e["with_why"] for e in explanation_rows)

    answered_by_fallback = 0
    if primary_model:
        answered_by_fallback = sum(
            1 for r in rows
            if any(model != primary_model for model in r.get("models", []))
        )

    return {
        "cases": len(rows),
        "errors": sum(1 for r in rows if r.get("error")),
        "tokens": {
            "prompt_mean": _mean([r.get("prompt_tokens", 0) for r in rows]),
            "completion_mean": _mean([r.get("completion_tokens", 0) for r in rows]),
            "total_mean": _mean([r.get("tokens", 0) for r in rows]),
            "total": sum(r.get("tokens", 0) for r in rows),
        },
        "seconds": {
            "mean": _mean([r["seconds"] for r in rows if "seconds" in r]),
            "p95": percentile([r["seconds"] for r in rows if "seconds" in r], 0.95),
        },
        "rate_limit_retries": sum(r.get("rate_limit_retries", 0) for r in rows),
        "cases_with_failover": sum(1 for r in rows if r.get("failovers")),
        "cases_answered_by_fallback_model": answered_by_fallback,
        "medical_suggestions_dropped": sum(r.get("medical_dropped", 0) for r in rows),
        "explanations": {
            "suggestions": suggestions,
            "with_user_said": user_said,
            "with_why": why,
            "user_said_share": _ratio(user_said, suggestions),
            "why_share": _ratio(why, suggestions),
        },
    }
