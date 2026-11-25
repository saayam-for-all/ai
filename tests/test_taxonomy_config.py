import json

from utils import predict_category_list
from services import classification_service

from utils.predict_category_list import (
    load_taxonomy,
    help_categories,
    TAXONOMY,
    get_top_level_categories,
    build_taxonomy_mappings
)



def test_taxonomy_category_count():
    """Ensure the config contains all 80 existing categories."""
    taxonomy = load_taxonomy()

    assert len(taxonomy) == 80


def test_taxonomy_parent_ids():
    """Ensure every parent is null or references a valid category."""
    taxonomy = load_taxonomy()

    for category_id, details in taxonomy.items():
        parent = details["parent"]

        assert parent is None or parent in taxonomy, (
            f"Category {category_id} has invalid parent {parent}"
        )


def test_help_categories_matches_config():
    """Ensure category ID-to-name mapping matches the config."""
    taxonomy = load_taxonomy()

    expected = {
        category_id: details["name"]
        for category_id, details in taxonomy.items()
    }

    assert help_categories == expected


def test_taxonomy_descriptions_match_config():
    """Ensure category name-to-description mapping matches the config."""
    taxonomy = load_taxonomy()

    expected = {
        details["name"]: details["description"]
        for details in taxonomy.values()
    }

    assert TAXONOMY == expected


def test_top_level_categories_unchanged():
    """Ensure the seven existing top-level categories are preserved."""
    expected = {
        "0.0.0.0.0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    }

    actual = get_top_level_categories()

    assert len(actual) == 7
    assert set(actual) == expected


def test_new_category_from_config(tmp_path, monkeypatch):
    """Ensure a new config category is recognized by the classifier."""

    taxonomy = load_taxonomy()

    # Add a new category under FOOD_AND_ESSENTIALS
    new_id = "1.4"
    new_name = "FOOD_STORAGE_SUPPORT"
    new_description = "Help with safe food storage and preservation."

    assert new_id not in taxonomy

    taxonomy[new_id] = {
        "name": new_name,
        "parent": "1",
        "description": new_description,
    }

    # Create a temporary configuration file
    config_path = tmp_path / "category_with_desc.json"

    config_path.write_text(
        json.dumps(taxonomy),
        encoding="utf-8",
    )

    # Load the temporary configuration
    loaded_taxonomy = load_taxonomy(config_path)

    assert len(loaded_taxonomy) == 81
    assert new_id in loaded_taxonomy

    # Build mappings from the temporary configuration
    new_help_categories, new_taxonomy = build_taxonomy_mappings(loaded_taxonomy)

    assert new_help_categories[new_id] == new_name
    assert new_taxonomy[new_name] == new_description
    
    # Temporarily replace the module-level mappings
    monkeypatch.setattr(
        predict_category_list,
        "help_categories",
        new_help_categories,
    )

    monkeypatch.setattr(
        classification_service,
        "help_categories",
        new_help_categories,
    )

    monkeypatch.setattr(
        classification_service,
        "TAXONOMY",
        new_taxonomy,
    )

    # Verify hierarchy lookup
    candidates = predict_category_list.get_direct_children("1")

    assert new_id in candidates

    assert predict_category_list.get_category_hierarchy(new_id) == (
        "Food And Essentials > Food Storage Support"
    )

    # Verify classifier prompts
    service = classification_service.GroqClassificationService()

    expected = f"{new_id}: {new_name} - {new_description}"

    single_prompt = service._build_prompt_for_candidates(
        "I need help storing food",
        candidates,
    )

    ranked_prompt = service._build_ranked_prompt_for_candidates(
        "I need help storing food",
        candidates,
    )

    assert expected in single_prompt
    assert expected in ranked_prompt