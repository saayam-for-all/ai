"""
The volunteer skills evaluation harness and its labelled set (issue #216).

tools/measure_skill_suggestions.py is the only thing that can show the
recall >= 80% / precision >= 80% acceptance bar, and it calls a live model, so
CI never runs it. What CI can check is everything that decides whether its
numbers mean anything:

* the scoring arithmetic, including the "acceptable" second answers and the
  cases where the right answer is no suggestion;
* the labelled set itself: every label is a category the Skills picker can
  select, so a mislabelled case cannot quietly cap recall below 100%.
"""

import importlib.util
from pathlib import Path

import pytest

from services.skill_suggestion_service import LEAF_CATEGORY_IDS

_TOOL = Path(__file__).resolve().parent.parent / "tools" / "measure_skill_suggestions.py"
_spec = importlib.util.spec_from_file_location("measure_skill_suggestions", _TOOL)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

CASES = harness.load_cases()


def _case(expected, acceptable=()):
    return {"id": "c", "description": "d", "expected": list(expected), "acceptable": list(acceptable)}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a_case_reports_what_was_found_missed_and_extra():
    score = harness.score_case(_case(["3.3.3", "3.3.1"]), ["3.3.3", "3.3.2"])

    assert score["found"] == ["3.3.3"]
    assert score["missed"] == ["3.3.1"]
    assert score["extra"] == ["3.3.2"]
    assert (score["returned"], score["returned_correct"]) == (2, 1)


@pytest.mark.unit
def test_an_acceptable_answer_is_not_an_error_but_does_not_count_as_found():
    score = harness.score_case(_case(["5.1.1"], ["5.1.11"]), ["5.1.11"])

    assert score["extra"] == []
    assert score["returned_correct"] == 1
    assert score["missed"] == ["5.1.1"]


@pytest.mark.unit
def test_rates_are_micro_averaged_over_every_label():
    scores = [
        harness.score_case(_case(["4.3.1", "4.3.5"]), ["4.3.1", "4.3.5"]),
        harness.score_case(_case(["5.1.3"]), ["5.1.3", "5.1.1"]),
        harness.score_case(_case(["6.2"]), []),
    ]

    summary = harness.summarise(scores)

    # 3 of 4 labels found; 3 of 4 suggestions correct.
    assert summary["recall"] == 0.75
    assert summary["precision"] == 0.75


@pytest.mark.unit
def test_no_match_cases_are_scored_separately():
    scores = [
        harness.score_case(_case([]), []),
        harness.score_case(_case([]), ["6.8"]),
    ]

    summary = harness.summarise(scores)

    assert summary["no_match_cases"] == 2
    assert summary["no_match_correct"] == 0.5
    assert summary["recall"] is None
    assert summary["precision"] == 0.0


@pytest.mark.unit
def test_an_unmeasured_rate_never_passes():
    # Nothing returned at all: precision is undefined, which is not a pass.
    summary = harness.summarise([harness.score_case(_case(["3.7"]), [])])

    assert summary["precision"] is None
    assert not harness.meets_target(summary)


@pytest.mark.unit
@pytest.mark.parametrize(
    "recall, precision, passes",
    [(0.8, 0.8, True), (0.79, 0.95, False), (0.95, 0.79, False), (1.0, 1.0, True)],
)
def test_the_target_needs_both_rates_at_eighty_percent(recall, precision, passes):
    assert harness.meets_target({"recall": recall, "precision": precision}) is passes


@pytest.mark.unit
def test_tags_get_their_own_rates():
    cases = [
        {**_case(["2.4"]), "tags": ["multi-area", "short"]},
        {**_case(["5.3"]), "tags": ["short"]},
    ]
    scores = [harness.score_case(cases[0], ["2.4"]), harness.score_case(cases[1], [])]

    by_tag = harness.summarise_by_tag(cases, scores)

    assert by_tag["multi-area"]["recall"] == 1.0
    assert by_tag["short"]["recall"] == 0.5


# ---------------------------------------------------------------------------
# The labelled set
# ---------------------------------------------------------------------------

@pytest.mark.dataset
def test_case_ids_are_unique():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.dataset
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_every_case_is_well_formed(case):
    assert isinstance(case["description"], str) and case["description"].strip()
    assert isinstance(case["expected"], list)
    assert isinstance(case.get("acceptable", []), list)
    assert case.get("tags"), "tag every case so the report can break results down"


@pytest.mark.dataset
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_every_label_is_a_selectable_leaf(case):
    labels = case["expected"] + case.get("acceptable", [])

    assert set(labels) <= set(LEAF_CATEGORY_IDS)
    assert len(labels) == len(set(labels)), "an ID is listed twice, or as both expected and acceptable"
