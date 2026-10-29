"""
The volunteer evaluation set itself (issue #216).

docs/metrics/volunteer_skills_eval_set.json is the ground truth the committed
recall and precision figures are measured against. If it drifts - a category
renumbered out from under it, a trait bucket quietly emptied, a label pointing
at a parent the Skills picker cannot select - the numbers keep being produced
and stop meaning anything. These tests fail instead.

No model and no network: the set is checked against the taxonomy the service
itself builds.
"""

import json
from pathlib import Path

import pytest

import services.skill_suggestion_service as ss

pytestmark = pytest.mark.dataset

EVAL_SET_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs" / "metrics" / "volunteer_skills_eval_set.json"
)

#: What issue #216 asks the set to cover, and the floor for each.
REQUIRED_TRAITS = {
    "short": 5,
    "multi_area": 8,
    "contains_retired": 5,
    "non_english": 5,
    "long": 3,
    "no_match": 4,
    "unmatched_skills": 4,
}

#: The ten cases in issue #216, abridged as the issue states them. They were
#: the inputs the prompt was designed against - commit f28d9ed removed the
#: dentist example from the prompt because of exactly this - so scoring
#: against them would measure the prompt against itself.
ISSUE_216_CASES = [
    "retired math teacher, algebra + SAT prep",
    "licensed electrician, also plumbing",
    "nurse; cooks for large events; drives people to appointments",
    "helps older people set up video calls",
    "sewing/alterations; resumes + interview practice",
    "teaches kids coding; reviews college essays",
    "pickup truck, helps people move",
    "licensed counsellor, emotional support",
    "i'm a dentist.",
    "gardening, painting, handyman",
]


@pytest.fixture(scope="module")
def eval_set():
    return json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases(eval_set):
    return eval_set["cases"]


def _accept_ids(case):
    return [i for skill in case["expected"] for i in skill["accept"]]


# ---------------------------------------------------------------------------
# Labels point at categories the Skills picker can actually select
# ---------------------------------------------------------------------------

def test_every_accepted_id_is_a_selectable_leaf(cases):
    """The same guarantee the service makes about its own output."""
    leaves = set(ss.LEAF_CATEGORY_IDS)
    offenders = {
        case["id"]: [i for i in _accept_ids(case) if i not in leaves]
        for case in cases
    }
    offenders = {k: v for k, v in offenders.items() if v}

    assert offenders == {}, f"labels outside the selectable leaf set: {offenders}"


def test_no_label_is_general_or_a_parent(cases):
    from utils.predict_category_list import get_direct_children

    for case in cases:
        for category_id in _accept_ids(case):
            assert category_id != ss.GENERAL_CATEGORY_ID, case["id"]
            assert not get_direct_children(category_id), (
                f"{case['id']} labels parent {category_id}"
            )


def test_accept_sets_are_non_empty_and_free_of_duplicates(cases):
    for case in cases:
        for skill in case["expected"]:
            assert skill["accept"], f"{case['id']}/{skill['skill']} accepts nothing"
            assert len(skill["accept"]) == len(set(skill["accept"])), case["id"]


def test_a_skill_name_is_not_reused_within_a_case(cases):
    """Two skills with the same name would be indistinguishable in the report."""
    for case in cases:
        names = [skill["skill"] for skill in case["expected"]]
        assert len(names) == len(set(names)), case["id"]


# ---------------------------------------------------------------------------
# The set is big enough and covers what the issue asked for
# ---------------------------------------------------------------------------

def test_the_set_meets_the_minimum_size(cases):
    assert len(cases) >= 40


def test_case_ids_are_unique(cases):
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("trait,minimum", sorted(REQUIRED_TRAITS.items()))
def test_each_required_trait_is_represented(cases, trait, minimum):
    count = sum(1 for case in cases if trait in case["traits"])
    assert count >= minimum, f"{trait}: {count} cases, need {minimum}"


def test_at_least_two_non_english_languages_appear(cases):
    languages = {
        case["language"] for case in cases if "non_english" in case["traits"]
    }
    assert len(languages) >= 2, languages
    assert "en" not in languages


def test_every_case_declares_a_language(cases):
    for case in cases:
        assert case.get("language"), case["id"]


# ---------------------------------------------------------------------------
# Declared traits match the text, so the per-trait breakdown means something
# ---------------------------------------------------------------------------

def test_short_cases_are_actually_short(cases):
    for case in cases:
        if "short" in case["traits"]:
            assert len(case["description"]) < 40, (case["id"], len(case["description"]))


def test_long_cases_are_actually_long(cases):
    for case in cases:
        if "long" in case["traits"]:
            assert len(case["description"]) > 1000, (case["id"], len(case["description"]))


def test_retired_cases_actually_say_retired_or_senior(cases):
    for case in cases:
        if "contains_retired" in case["traits"]:
            text = case["description"].lower()
            assert "retired" in text or "senior" in text, case["id"]


def test_multi_area_cases_span_at_least_two_top_level_branches(cases):
    """Three skills inside one branch is not the case volunteer mode exists for."""
    for case in cases:
        if "multi_area" not in case["traits"]:
            continue
        assert len(case["expected"]) >= 3, case["id"]
        branches = {skill["accept"][0].split(".")[0] for skill in case["expected"]}
        assert len(branches) >= 2, (case["id"], branches)


def test_no_match_cases_label_no_skills(cases):
    for case in cases:
        if "no_match" in case["traits"]:
            assert case["expected"] == [], case["id"]


def test_unmatched_skill_cases_say_what_should_land_there(cases):
    for case in cases:
        if "unmatched_skills" in case["traits"]:
            assert case.get("expected_unmatched"), case["id"]


# ---------------------------------------------------------------------------
# The set is independent of the prompt
# ---------------------------------------------------------------------------

def test_no_case_reuses_a_description_from_issue_216(cases):
    """Paraphrasing the situations is fine; reusing the text is not.

    Checked against the abridged forms the issue publishes, which is what is
    available to check against.
    """
    for case in cases:
        text = " ".join(case["description"].lower().split())
        for issue_case in ISSUE_216_CASES:
            assert text != issue_case, case["id"]


def test_descriptions_fit_within_the_services_own_cap(cases):
    """Over 2,000 characters the service truncates, and a label at the end of
    a longer description would be unreachable rather than missed."""
    for case in cases:
        assert len(case["description"]) <= ss.MAX_DESCRIPTION_CHARS, case["id"]


def test_descriptions_are_unique(cases):
    texts = [" ".join(case["description"].lower().split()) for case in cases]
    assert len(texts) == len(set(texts))
