"""
How volunteer skill suggestions are scored (issue #216).

The acceptance bar for #216 is "recall >= 80% and precision >= 80%". That
number is only worth as much as the counting behind it, and the counting is
not obvious: skills carry sets of acceptable IDs, one prediction must not
satisfy two skills, and a provider outage must not be allowed to look like a
clean sheet. These tests pin the arithmetic that the committed metrics report
is built on.

Pure functions, no model, no network.
"""

import pytest

from tools.skill_eval_scoring import (
    ExpectedSkill,
    Prediction,
    aggregate,
    aggregate_by_trait,
    false_suggestion_rate,
    percentile,
    run_statistics,
    score_case,
    to_expected,
    to_predictions,
)

pytestmark = pytest.mark.unit


def _skill(name, *accept):
    return ExpectedSkill(skill=name, accept=frozenset(accept))


def _score(expected, predictions, traits=(), error=None, case_id="case"):
    return score_case(case_id, expected, predictions, traits=traits, error=error)


# ---------------------------------------------------------------------------
# Matching one case
# ---------------------------------------------------------------------------

def test_an_exact_single_match_is_one_true_positive():
    score = _score([_skill("plumbing", "3.3.1")], [Prediction("3.3.1", 0.9)])

    assert (score.true_positives, score.false_positives, score.false_negatives) == (1, 0, 0)
    assert score.matched == {"plumbing": "3.3.1"}


def test_an_acceptable_alternative_counts_as_found():
    """5.1.11 Other Medical Concern stands in for 5.1.1 General Consultation.

    Nesh's smoke test on #216: "nurse" lands on either, and the taxonomy -
    not the model - is what makes them interchangeable.
    """
    score = _score(
        [_skill("nursing", "5.1.1", "5.1.11")], [Prediction("5.1.11", 0.8)]
    )

    assert score.true_positives == 1
    assert score.matched == {"nursing": "5.1.11"}
    assert score.spurious == []


def test_one_prediction_cannot_satisfy_two_skills():
    """Otherwise a single 5.1.1 would score both labelled medical skills."""
    score = _score(
        [_skill("nursing", "5.1.1"), _skill("general practice", "5.1.1")],
        [Prediction("5.1.1", 0.9)],
    )

    assert score.true_positives == 1
    assert score.false_negatives == 1
    assert score.false_positives == 0


def test_pairing_does_not_depend_on_the_order_the_labels_were_written():
    """The case a greedy walk gets wrong.

    Skills [{X, Y}, {X}] with both X and Y predicted: taking X for the first
    skill strands the second and scores 1. Maximum matching gives X to the
    skill that can only take X, and scores the 2 that were really there.
    """
    expected = [_skill("first", "3.3.1", "3.3.2"), _skill("second", "3.3.1")]
    predictions = [Prediction("3.3.1", 0.9), Prediction("3.3.2", 0.5)]

    score = _score(expected, predictions)

    assert score.true_positives == 2
    assert score.false_positives == 0
    assert score.matched == {"first": "3.3.2", "second": "3.3.1"}


def test_an_ambiguous_pairing_credits_the_confident_prediction():
    """Totals do not depend on this, but the report should be deterministic."""
    score = _score(
        [_skill("transport", "6.5", "6.6")],
        [Prediction("6.6", 0.4), Prediction("6.5", 0.95)],
    )

    assert score.matched == {"transport": "6.5"}
    assert score.spurious == ["6.6"]


def test_leftover_predictions_are_false_positives():
    score = _score(
        [_skill("painting", "3.3.9")],
        [Prediction("3.3.9", 0.9), Prediction("4.3.1", 0.7)],
    )

    assert score.true_positives == 1
    assert score.false_positives == 1
    assert score.spurious == ["4.3.1"]


def test_unfound_skills_are_false_negatives():
    score = _score(
        [_skill("welding", "3.3.11"), _skill("maths", "4.3.1")],
        [Prediction("3.3.11", 0.9)],
    )

    assert score.true_positives == 1
    assert score.false_negatives == 1
    assert score.missed == ["maths"]


def test_predicting_nothing_on_a_labelled_case_is_all_misses():
    score = _score([_skill("welding", "3.3.11")], [])

    assert (score.true_positives, score.false_positives, score.false_negatives) == (0, 0, 1)


# ---------------------------------------------------------------------------
# Descriptions that state no skill at all
# ---------------------------------------------------------------------------

def test_a_no_match_case_with_suggestions_is_all_false_positives():
    score = _score([], [Prediction("4.3.1", 0.6), Prediction("6.8", 0.55)])

    assert score.false_positives == 2
    assert score.false_negatives == 0
    assert score.true_positives == 0


def test_a_correctly_empty_no_match_case_counts_nowhere():
    score = _score([], [])

    assert (score.true_positives, score.false_positives, score.false_negatives) == (0, 0, 0)


def test_false_suggestion_rate_isolates_the_invented_skills():
    """Recall cannot see this, and precision dilutes it across every case."""
    scores = [
        _score([], [], case_id="quiet"),
        _score([], [Prediction("4.3.1", 0.6)], case_id="invented"),
        _score([_skill("maths", "4.3.1")], [Prediction("4.3.1", 0.9)], case_id="real"),
    ]

    rate = false_suggestion_rate(scores)

    assert rate["cases"] == 2
    assert rate["cases_with_suggestions"] == 1
    assert rate["suggestions"] == 1
    assert rate["rate"] == 0.5


# ---------------------------------------------------------------------------
# A failed case is a miss, not an absence
# ---------------------------------------------------------------------------

def test_a_provider_error_scores_every_labelled_skill_as_missed():
    """A run full of 429s must not read as perfect precision."""
    score = _score(
        [_skill("welding", "3.3.11"), _skill("maths", "4.3.1")],
        [],
        error="RateLimitError: 429",
    )

    assert score.false_negatives == 2
    assert score.true_positives == 0
    assert score.false_positives == 0
    assert score.missed == ["welding", "maths"]


def test_errors_are_counted_in_the_aggregate():
    scores = [
        _score([_skill("a", "1.1")], [Prediction("1.1", 0.9)]),
        _score([_skill("b", "1.2")], [], error="boom"),
    ]

    assert aggregate(scores)["errors"] == 1


# ---------------------------------------------------------------------------
# Micro aggregation
# ---------------------------------------------------------------------------

def test_totals_are_micro_averaged_across_cases():
    """Worked by hand: 3 TP, 1 FP, 2 FN.

    recall    = 3 / (3 + 2) = 0.6
    precision = 3 / (3 + 1) = 0.75
    """
    scores = [
        # 2 TP, 1 FN
        _score(
            [_skill("a", "1.1"), _skill("b", "1.2"), _skill("c", "1.3.1")],
            [Prediction("1.1", 0.9), Prediction("1.2", 0.8)],
        ),
        # 1 TP, 1 FP
        _score(
            [_skill("d", "2.1")],
            [Prediction("2.1", 0.9), Prediction("2.2", 0.7)],
        ),
        # 1 FN
        _score([_skill("e", "3.1")], []),
    ]

    totals = aggregate(scores)

    assert (totals["true_positives"], totals["false_positives"], totals["false_negatives"]) == (3, 1, 2)
    assert totals["recall"] == pytest.approx(0.6)
    assert totals["precision"] == pytest.approx(0.75)
    assert totals["f1"] == pytest.approx(2 * 0.6 * 0.75 / (0.6 + 0.75))


def test_a_run_that_answered_nothing_reports_undefined_not_zero():
    """0% reads as "always wrong"; the model was never asked a question it answered."""
    totals = aggregate([_score([], [])])

    assert totals["precision"] is None
    assert totals["recall"] is None
    assert totals["f1"] is None


def test_aggregating_no_cases_does_not_divide_by_zero():
    totals = aggregate([])

    assert totals["cases"] == 0
    assert totals["recall"] is None


def test_trait_buckets_are_scored_independently():
    scores = [
        _score([_skill("a", "1.1")], [Prediction("1.1", 0.9)], traits=("short",)),
        _score([_skill("b", "1.2")], [], traits=("short", "non_english")),
        _score([_skill("c", "1.3.1")], [Prediction("1.3.1", 0.9)], traits=("long",)),
    ]

    by_trait = aggregate_by_trait(scores)

    assert by_trait["short"]["recall"] == pytest.approx(0.5)
    assert by_trait["non_english"]["recall"] == pytest.approx(0.0)
    assert by_trait["long"]["recall"] == pytest.approx(1.0)
    # Overlapping buckets: a case with two traits is counted in both.
    assert by_trait["short"]["cases"] + by_trait["long"]["cases"] == 3


# ---------------------------------------------------------------------------
# Reading the two file formats
# ---------------------------------------------------------------------------

def test_expected_skills_are_read_from_the_eval_set_shape():
    expected = to_expected([{"skill": "nursing", "accept": ["5.1.1", "5.1.11"]}])

    assert expected[0].skill == "nursing"
    assert expected[0].accept == frozenset({"5.1.1", "5.1.11"})


def test_predictions_are_read_from_the_service_response_shape():
    predictions = to_predictions([
        {"category_number": "3.3.3", "category_name": "ELECTRICIAN", "confidence": 0.95},
    ])

    assert predictions == [Prediction("3.3.3", 0.95)]


@pytest.mark.parametrize("raw", [None, []])
def test_empty_inputs_read_as_empty_lists(raw):
    assert to_expected(raw) == []
    assert to_predictions(raw) == []


def test_a_missing_confidence_does_not_break_reading_a_prediction():
    assert to_predictions([{"category_number": "3.3.3"}]) == [Prediction("3.3.3", 0.0)]


# ---------------------------------------------------------------------------
# Cost, latency and reliability of a pass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "values, fraction, expected",
    [
        ([3.0], 0.95, 3.0),
        ([1.0, 2.0, 3.0, 4.0], 0.5, 2.0),
        (list(range(1, 21)), 0.95, 19),     # 0.95 * 20 = 19th value
        (list(range(1, 68)), 0.95, 64),     # ceil(63.65) = 64th of 67
        ([5.0, 1.0, 3.0], 1.0, 5.0),        # order of input does not matter
    ],
)
def test_percentile_is_nearest_rank(values, fraction, expected):
    assert percentile(values, fraction) == expected


def test_percentile_of_nothing_is_none_not_zero():
    assert percentile([], 0.95) is None


@pytest.mark.parametrize("fraction", [0, -0.1, 1.5])
def test_percentile_rejects_a_fraction_outside_zero_to_one(fraction):
    with pytest.raises(ValueError):
        percentile([1.0], fraction)


def _row(**fields):
    base = {"tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 1.0}
    base.update(fields)
    return base


def test_run_statistics_reports_mean_tokens_split_and_total():
    rows = [
        _row(tokens=1000, prompt_tokens=900, completion_tokens=100),
        _row(tokens=3000, prompt_tokens=2500, completion_tokens=500),
    ]

    tokens = run_statistics(rows)["tokens"]

    assert tokens == {
        "prompt_mean": 1700, "completion_mean": 300, "total_mean": 2000, "total": 4000,
    }


def test_run_statistics_counts_reliability_separately_from_accuracy():
    rows = [
        _row(error="ModelChainExhausted: predict_category failed"),
        _row(rate_limit_retries=2, failovers=["MODEL_FAILOVER ... status=429"],
             models=["openai/gpt-oss-120b"]),
        _row(models=["openai/gpt-oss-20b"]),
    ]

    stats = run_statistics(rows, primary_model="openai/gpt-oss-20b")

    assert stats["errors"] == 1
    assert stats["rate_limit_retries"] == 2
    assert stats["cases_with_failover"] == 1
    assert stats["cases_answered_by_fallback_model"] == 1


def test_without_a_primary_model_no_case_is_called_a_fallback():
    stats = run_statistics([_row(models=["anything"])])
    assert stats["cases_answered_by_fallback_model"] == 0


def test_run_statistics_reports_explanation_shares_and_medical_drops():
    rows = [
        _row(explanations={"suggestions": 3, "with_user_said": 3, "with_why": 2},
             medical_dropped=1),
        _row(explanations={"suggestions": 1, "with_user_said": 0, "with_why": 1}),
        _row(),  # an older or help-request row with no explanations
    ]

    stats = run_statistics(rows)

    assert stats["medical_suggestions_dropped"] == 1
    assert stats["explanations"] == {
        "suggestions": 4, "with_user_said": 3, "with_why": 3,
        "user_said_share": 0.75, "why_share": 0.75,
    }


def test_run_statistics_of_rows_from_the_older_harness_does_not_guess():
    """Rows from before the token split have only `tokens` and `seconds`."""
    stats = run_statistics([{"tokens": 2400, "seconds": 2.0}])

    assert stats["tokens"]["prompt_mean"] == 0
    assert stats["tokens"]["total_mean"] == 2400
    assert stats["explanations"]["user_said_share"] is None
    assert stats["seconds"] == {"mean": 2.0, "p95": 2.0}
