"""
Guard the predict_category response contract the web form depends on.

The form calls this endpoint and does:

    (response || []).map((category) => ({ id: category.toLowerCase(), name: category }))

so the body must be a JSON ARRAY of plain STRINGS, and each string must match a
name in the form's own category dropdown. The classifier works in taxonomy IDs
and returns ranked leaf categories, so lambda_function translates between them.

No network or keys required.
"""
import json
from unittest import mock

import lambda_function as LF
from utils.predict_category_list import help_categories, get_top_level_categories

# The form's static list, from webapp src/redux/features/help_request/requestActions.js
FORM_CATEGORY_NAMES = {
    "General",
    "Food & Essentials",
    "Clothing Support",
    "Housing Assistance",
    "Education & Career Support",
    "Healthcare & Well-being",
    "Elderly & Community Support",
}


def test_every_top_level_category_maps_to_a_selectable_name():
    for cid in get_top_level_categories():
        got = LF._to_display_names([{"category_number": cid}])
        if help_categories.get(cid) == "GENERAL_CATEGORY":
            # Deliberately omitted: the form supplies its own General option.
            assert got == [], "General must not be returned, the form adds it"
            continue
        assert got, f"{cid} ({help_categories.get(cid)}) mapped to nothing"
        assert got[0] in FORM_CATEGORY_NAMES, f"{got[0]} is not selectable in the form"


def test_leaf_category_resolves_to_its_top_level_parent():
    # The form only offers top level categories, so a leaf must roll up.
    assert LF._to_display_names([{"category_number": "4.3.1"}]) == ["Education & Career Support"]
    assert LF._to_display_names([{"category_number": "3.2.1"}]) == ["Housing Assistance"]
    assert LF._to_display_names([{"category_number": "0.0.0.0.0"}]) == []


def test_ranked_order_is_preserved_and_duplicates_dropped():
    ranked = [
        {"category_number": "4.3.1"},  # Education
        {"category_number": "4.3.6"},  # Education again
        {"category_number": "5.1"},    # Healthcare
    ]
    assert LF._to_display_names(ranked) == [
        "Education & Career Support",
        "Healthcare & Well-being",
    ]


def test_general_is_never_returned_because_the_form_adds_it():
    # Returning General would render it twice in the popup.
    assert LF._to_display_names([{"category_number": "0.0.0.0.0"}]) == []
    mixed = [{"category_number": "0.0.0.0.0"}, {"category_number": "4.3.1"}]
    assert LF._to_display_names(mixed) == ["Education & Career Support"]


def test_missing_or_malformed_input_yields_empty_list():
    assert LF._to_display_names([]) == []
    assert LF._to_display_names(None) == []
    assert LF._to_display_names([{"category_number": ""}, {"unexpected": 1}]) == []


def test_handler_body_is_a_json_array_of_strings():
    with mock.patch.object(LF, "predict_categories",
                           return_value=([{"category_number": "4.3.1"}], {})):
        res = LF.predict_category_handler({"body": json.dumps({"description": "x"})}, None)

    assert res["statusCode"] == 200
    body = json.loads(res["body"])          # must be a serialized string, not a raw list
    assert isinstance(body, list)
    assert all(isinstance(item, str) for item in body)
    assert body == ["Education & Career Support"]


def test_response_helper_serializes_lists():
    # Regression: _response only serialized dicts, so a list body was passed
    # through unserialized and would not survive API Gateway.
    res = LF._response(200, ["a", "b"])
    assert isinstance(res["body"], str)
    assert json.loads(res["body"]) == ["a", "b"]
