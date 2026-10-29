"""
Guards issue #217: "Need help gardening" must reach 3.3.5 GARDEN, not General.

Covers the Garden routing hint, General as a fallback only, and the leaf
results contract (no duplicates, no top-level parents). No network calls:
the ranked model step is stubbed.
"""
import pytest

import services.classification_service as cs
from utils.categories_with_description import TAXONOMY
from utils.predict_category_list import (
    category_name_to_number,
    get_direct_children,
    get_top_level_categories,
)

GARDEN_ID = category_name_to_number["GARDEN"]
GENERAL_ID = category_name_to_number["GENERAL_CATEGORY"]

pytestmark = pytest.mark.unit


def test_garden_description_matches_category_name():
    assert GARDEN_ID == "3.3.5"
    assert "GARDEN" in TAXONOMY


@pytest.mark.parametrize(
    "candidates",
    [
        get_top_level_categories(),
        get_direct_children("3"),
        get_direct_children("3.3"),
    ],
)
def test_gardening_hint_routes_to_the_most_specific_available_category(
    candidates,
):
    service = cs.GroqClassificationService()

    prompt = service._build_prompt_for_candidates(
        "Need help gardening", candidates
    )

    assert "Gardening routing rule" in prompt
    assert GARDEN_ID in prompt


def test_ranked_prompt_includes_gardening_hint():
    service = cs.GroqClassificationService()
    candidates = get_direct_children("3.3")

    prompt = service._build_ranked_prompt_for_candidates(
        "Need help gardening", candidates
    )

    assert "Gardening routing rule" in prompt
    assert GARDEN_ID in prompt


def test_leaf_results_deduplicate_and_exclude_parent_categories():
    results = cs.GroqClassificationService._format_leaf_results(
        [
            {"category": "3", "confidence": 0.99},
            {"category": GARDEN_ID, "confidence": 0.95},
            {"category": GARDEN_ID, "confidence": 0.90},
            {"category": GENERAL_ID, "confidence": 0.50},
        ]
    )

    assert [item["category_number"] for item in results] == [GARDEN_ID]


def test_general_is_returned_once_only_when_no_specific_result_exists():
    results = cs.GroqClassificationService._format_leaf_results(
        [
            {"category": GENERAL_ID, "confidence": 0.80},
            {"category": "3", "confidence": 0.70},
            {"category": GENERAL_ID, "confidence": 0.60},
        ]
    )

    assert len(results) == 1
    assert results[0]["category_number"] == GENERAL_ID


def test_general_is_omitted_when_a_specific_category_exists():
    results = cs.GroqClassificationService._format_leaf_results(
        [
            {"category": GENERAL_ID, "confidence": 0.99},
            {"category": GARDEN_ID, "confidence": 0.80},
        ]
    )

    assert [item["category_number"] for item in results] == [GARDEN_ID]


@pytest.mark.parametrize(
    "candidates",
    [get_direct_children("1"), get_direct_children("4.3")],
)
def test_gardening_hint_is_absent_when_garden_path_is_not_a_candidate(
    candidates,
):
    service = cs.GroqClassificationService()

    prompt = service._build_ranked_prompt_for_candidates(
        "Need groceries", candidates
    )

    assert "Gardening routing rule" not in prompt


def _walk_with(responses):
    service = cs.GroqClassificationService()
    replies = iter(responses)
    service._predict_ranked_level = lambda *args, **kwargs: next(replies)
    results, _ = service.predict_categories("Need help gardening")
    return [item["category_number"] for item in results]


def test_walk_descends_past_general_when_a_specific_path_is_offered():
    # Issue #217: General ranked first at the top level, Housing second.
    assert _walk_with(
        [
            [
                {"category": GENERAL_ID, "confidence": 0.95},
                {"category": "3", "confidence": 0.95},
                {"category": "1", "confidence": 0.2},
            ],
            [{"category": "3.3", "confidence": 0.9}],
            [{"category": GARDEN_ID, "confidence": 0.95}],
        ]
    ) == [GARDEN_ID]


def test_walk_keeps_general_when_specific_alternative_is_below_threshold():
    assert _walk_with(
        [
            [
                {"category": GENERAL_ID, "confidence": 0.95},
                {"category": "3", "confidence": 0.75},
            ]
        ]
    ) == [GENERAL_ID]


def test_walk_accepts_specific_top_choice_regardless_of_confidence():
    assert _walk_with(
        [
            [
                {"category": "3", "confidence": 0.75},
                {"category": GENERAL_ID, "confidence": 0.95},
            ],
            [{"category": "3.3", "confidence": 0.9}],
            [{"category": GARDEN_ID, "confidence": 0.95}],
        ]
    ) == [GARDEN_ID]

def test_walk_keeps_general_when_alternatives_are_below_threshold():
    assert _walk_with(
        [
            [
                {"category": GENERAL_ID, "confidence": 0.95},
                {"category": "3", "confidence": 0.1},
            ]
        ]
    ) == [GENERAL_ID]


def test_walk_keeps_general_when_it_is_the_only_option():
    assert _walk_with(
        [
            [
                {"category": GENERAL_ID, "confidence": 0.95},
                {"category": GENERAL_ID, "confidence": 0.8},
                {"category": GENERAL_ID, "confidence": 0.65},
            ]
        ]
    ) == [GENERAL_ID]
