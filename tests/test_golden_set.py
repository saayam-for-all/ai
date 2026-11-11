"""The shipped classification golden set is well formed and labelled honestly.

A golden set is only worth gating on if its labels can be trusted. These tests
check the file as data, independent of any model: every label is a real
category in the taxonomy the classifier walks, the coverage spans every
branch, and the tags that explain a case (routing, known gaps) are true.
"""

import pytest

from evaluation.classification_eval import top_level_of
from evaluation.golden_set import KNOWN_GAP_TAG, load_golden_set
from utils.predict_category_list import get_top_level_categories, help_categories
from utils.routing_for_categories import is_elderly_context

pytestmark = pytest.mark.dataset

CASES = load_golden_set()


def test_golden_set_loads_with_enough_scored_cases():
    """The file parses and has enough scored cases for a 90% mark to mean something.

    With fewer than about 30 cases, one flipped answer moves the score by more
    than three points and the gate becomes a coin toss.
    """
    assert sum(case.scored for case in CASES) >= 30


def test_every_top_level_branch_has_scored_cases():
    """No branch of the taxonomy is left out of the evaluation.

    A branch with no cases is a branch whose regressions the gate cannot see.
    """
    covered = {top_level_of(case.expected_id) for case in CASES if case.scored}
    every_branch = {top_level_of(category_id) for category_id in get_top_level_categories()}
    assert every_branch <= covered, f"no scored case for: {every_branch - covered}"


@pytest.mark.parametrize("case", [c for c in CASES if c.scored], ids=lambda c: c.id)
def test_scored_label_is_a_category_the_classifier_can_return(case):
    """Each label resolves to an id in utils/predict_category_list.py.

    The loader enforces this too; the per-case test names the offending case
    in the failure line, which is what a labeller needs.
    """
    assert case.expected_id in help_categories


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_elderly_router_tags_match_what_the_router_does(case):
    """Cases tagged elderly-router* are exactly the ones the router diverts.

    The router (utils/routing_for_categories.py) skips the top-level choice
    and offers only Elderly sub-categories. The report attributes misses to
    it, so the tags must not drift from its real behaviour.
    """
    tagged = any(tag.startswith("elderly-router") for tag in case.tags)
    assert tagged == is_elderly_context(case.description)


def test_router_false_positives_are_labelled_outside_elderly():
    """Cases tagged as router false positives really belong to another branch.

    These are the cases that show the router's cost: requests that mention
    "senior", "aging" or "fall" in a non-elderly sense.
    """
    false_positives = [c for c in CASES if "elderly-router-false-positive" in c.tags]
    assert false_positives
    assert all(top_level_of(c.expected_id) != "6" for c in false_positives)


def test_known_gaps_carry_no_label_and_say_why():
    """Known-gap cases have no expected category and a note explaining the gap.

    They are reported but never scored, so the note is the only place the
    reason is written down.
    """
    gaps = [c for c in CASES if KNOWN_GAP_TAG in c.tags]
    assert gaps
    assert all(c.expected is None and not c.scored and c.note for c in gaps)
