"""Unit tests for the request-detail prompt variants (issue #158).

Hermetic: no network, no model, no AWS. Importing utils.prompts triggers the
SSM bootstrap in utils.client, which fails gracefully without credentials and
leaves the provider handles as None. Nothing here calls one.

These cover the defect the A/B was built to measure - a category dictionary
keyed on names the taxonomy does not use - because that defect was invisible
to every existing test: the service returned a perfectly well-formed answer
built from the wrong prompt.
"""

import pytest

pytestmark = pytest.mark.unit

import utils.prompts as prompts
from utils.predict_category_list import help_categories

ALL_CATEGORY_NAMES = sorted(set(help_categories.values()))
NON_BASELINE_VARIANTS = [v for v in prompts.VARIANTS if v != "A"]


# ---------------------------------------------------------------------------
# resolve_prompt_key
# ---------------------------------------------------------------------------

def test_exact_taxonomy_name_wins():
    assert prompts.resolve_prompt_key("TUTORING", prompts.category_prompts) == "TUTORING"


@pytest.mark.parametrize(
    "category,expected",
    [
        ("HOUSING_ASSISTANCE", "HOUSING_SUPPORT"),
        ("FOOD_AND_ESSENTIALS", "FOOD_AND_ESSENTIALS_SUPPORT"),
        ("CLOTHING_ASSISTANCE", "CLOTHING_SUPPORT"),
        ("HEALTHCARE_AND_WELLNESS", "HEALTHCARE_WELLNESS_SUPPORT"),
        ("ELDERLY_COMMUNITY_ASSISTANCE", "ELDERLY_SUPPORT"),
        ("GENERAL_CATEGORY", "General"),
        ("FIND_ROOMATE", "FIND_A_ROOMMATE"),
    ],
)
def test_alias_maps_taxonomy_name_to_prompt_key(category, expected):
    assert prompts.resolve_prompt_key(category, prompts.category_prompts) == expected


@pytest.mark.parametrize(
    "leaf,expected",
    [
        ("PLUMBING", "HOME_REPAIR_SUPPORT"),          # 3.3.1 -> 3.3 -> alias
        ("ELECTRICIAN", "HOME_REPAIR_SUPPORT"),        # 3.3.3 -> 3.3 -> alias
        ("MATH", "TUTORING"),                          # 4.3.1 -> 4.3, an exact key
        ("TEST_PREP", "TUTORING"),                     # 4.3.5 -> 4.3
        ("CARDIAC_OR_BLOOD_PRESSURE", "MEDICAL_NAVIGATION"),  # 5.1.5 -> 5.1 -> alias
        ("MEAL_PREP_BASIC", "COOKING_HELP"),           # 1.3.1 -> 1.3
    ],
)
def test_leaf_categories_inherit_the_nearest_ancestor_prompt(leaf, expected):
    assert prompts.resolve_prompt_key(leaf, prompts.category_prompts) == expected


def test_nearest_ancestor_wins_over_a_distant_one():
    """MATH must reach TUTORING, not skip up to EDUCATION_CAREER_SUPPORT."""
    assert prompts.resolve_prompt_key("MATH", prompts.category_prompts) == "TUTORING"


def test_unknown_and_empty_categories_fall_back_to_general():
    for value in ("", None, "NOT_A_CATEGORY", "   "):
        assert prompts.resolve_prompt_key(value, prompts.category_prompts) == "General"


def test_category_with_brackets_in_its_name_resolves():
    """ENT(EAR_NOSE_AND_THROAT) contains characters that break naive parsing."""
    assert prompts.resolve_prompt_key(
        "ENT(EAR_NOSE_AND_THROAT)", prompts.category_prompts
    ) == "MEDICAL_NAVIGATION"


# ---------------------------------------------------------------------------
# The defect itself: coverage of the real taxonomy
# ---------------------------------------------------------------------------

def test_baseline_leaves_most_of_the_taxonomy_without_a_prompt():
    """Pins the defect so a future edit cannot quietly reintroduce it.

    The baseline looks its category up in category_prompts directly. Most
    taxonomy names are not keys there, so most requests were answered with the
    General prompt no matter what the person asked about.
    """
    unmatched = [n for n in ALL_CATEGORY_NAMES if n not in prompts.category_prompts]
    assert len(unmatched) == 62
    for name in ("HOUSING_ASSISTANCE", "FOOD_AND_ESSENTIALS", "HEALTHCARE_AND_WELLNESS",
                 "ELDERLY_COMMUNITY_ASSISTANCE", "CLOTHING_ASSISTANCE", "PLUMBING"):
        assert name in unmatched


@pytest.mark.parametrize("variant", NON_BASELINE_VARIANTS)
def test_every_taxonomy_category_resolves_to_a_domain_prompt(variant):
    """GENERAL_CATEGORY is the only one that should land on General."""
    bodies = (prompts.category_prompts if variant == "B" else prompts.CATEGORY_PROMPTS_C)
    on_general = [
        name for name in ALL_CATEGORY_NAMES
        if prompts.resolve_prompt_key(name, bodies) == "General"
    ]
    assert on_general == ["GENERAL_CATEGORY"]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variant", prompts.VARIANTS)
def test_every_category_builds_a_prompt_without_a_format_error(variant):
    """A stray brace or an unfilled placeholder raises here, not in production."""
    for name in ALL_CATEGORY_NAMES:
        text = prompts.get_conversational_prompt(
            category=name, subject="A subject", location="Leeds, UK",
            gender="female", age="42", variant=variant,
        )
        assert text.strip()
        assert "{base_instruction}" not in text
        assert "{location}" not in text and "{subject}" not in text


@pytest.mark.parametrize("variant", prompts.VARIANTS)
def test_missing_context_fields_do_not_leak_empty_placeholders(variant):
    text = prompts.get_conversational_prompt(
        category="HOUSING_ASSISTANCE", subject="Subject", variant=variant
    )
    assert prompts.NOT_SPECIFIED in text
    assert "()" not in text


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError, match="Unknown prompt variant"):
        prompts.get_conversational_prompt("TUTORING", "s", variant="Z")


def test_variant_defaults_to_the_active_one(monkeypatch):
    monkeypatch.setattr(prompts, "ACTIVE_VARIANT", "D")
    text = prompts.get_conversational_prompt("TUTORING", "s")
    assert "WHAT YOU MAY NOT INVENT" in text


def test_variant_argument_overrides_the_active_one(monkeypatch):
    monkeypatch.setattr(prompts, "ACTIVE_VARIANT", "D")
    text = prompts.get_conversational_prompt("TUTORING", "s", variant="A")
    assert "WHAT YOU MAY NOT INVENT" not in text


# ---------------------------------------------------------------------------
# The contradictions variant C exists to remove
# ---------------------------------------------------------------------------

_CONTACT_TOKENS = ("911", "988", "112", "741741", "SNAP/WIC")


def test_baseline_prompt_contradicts_itself_on_contact_details():
    """The base rules forbid contact details; the category body demands them."""
    text = prompts.get_conversational_prompt(
        "MENTAL_WELLBEING_SUPPORT", "s", location="Austin, TX", variant="A"
    )
    assert "Do NOT provide emergency numbers or contact information." in text
    assert "988" in text and "741741" in text


@pytest.mark.parametrize("category", ALL_CATEGORY_NAMES)
def test_variant_c_never_hard_codes_a_contact_number(category):
    text = prompts.get_conversational_prompt(
        category, "s", location="Austin, TX", variant="C"
    )
    for token in _CONTACT_TOKENS:
        assert token not in text, f"{category} still hard-codes {token}"


@pytest.mark.parametrize("category", ALL_CATEGORY_NAMES)
def test_variant_c_never_demands_an_enumerated_answer(category):
    """(1)(2)(3) bodies fight the 'under 60 words, no lists' rule."""
    text = prompts.get_conversational_prompt(category, "s", variant="C")
    assert "(1)" not in text and "(2)" not in text


def test_variant_c_still_permits_emergency_escalation_without_a_number():
    text = prompts.get_conversational_prompt("MENTAL_WELLBEING_SUPPORT", "s", variant="C")
    assert "local emergency services" in text
    assert "Do not quote a specific number." in text


def test_variant_d_is_variant_c_plus_the_limitation_block():
    c = prompts.get_conversational_prompt("TUTORING", "s", variant="C")
    d = prompts.get_conversational_prompt("TUTORING", "s", variant="D")
    assert d.startswith(c)
    assert d[len(c):] == prompts.CONTEXT_LIMITATION


# ---------------------------------------------------------------------------
# Variant A must stay byte-identical, or the baseline is not a baseline
# ---------------------------------------------------------------------------

def test_variant_a_matches_the_legacy_builder_exactly():
    for category in ("MENTAL_WELLBEING_SUPPORT", "PLUMBING", "TUTORING", "NOT_A_CATEGORY"):
        assert prompts.get_conversational_prompt(
            category, "Subject", "Leeds", "female", "42", variant="A"
        ) == prompts._conversational_prompt_legacy(
            category, "Subject", "Leeds", "female", "42"
        )


def test_every_variant_keeps_the_conversation_context_block():
    for variant in prompts.VARIANTS:
        text = prompts.get_conversational_prompt("TUTORING", "s", variant=variant)
        assert "CONVERSATION CONTEXT:" in text


# ---------------------------------------------------------------------------
# What production actually serves
# ---------------------------------------------------------------------------

def test_active_variant_is_a_known_variant():
    assert prompts.ACTIVE_VARIANT in prompts.VARIANTS


def test_production_serves_the_variant_the_ab_selected():
    """F is deployed, on the evidence in docs/metrics/REQUEST_DETAIL_ACCURACY.md.

    Measured on all 55 corpus cases, paired against the previously deployed
    prompt: composite +0.081 (95% CI [+0.036, +0.126]), groundedness +0.164,
    intent fidelity a statistical tie, and crisis escalation 5 of 5 against the
    old prompt's 1 of 5. It was chosen over E - whose composite was nearly as
    good - because E answered suicidal ideation, and a person fleeing violence,
    by suggesting they ask Saayam for a volunteer.

    Change this test and ACTIVE_VARIANT in the same commit, so the shipped
    prompt and the evidence for it never drift apart.
    """
    assert prompts.ACTIVE_VARIANT == "F"


def test_the_shipped_prompt_carries_the_crisis_override():
    """The single behaviour F was shipped for."""
    text = prompts.get_conversational_prompt("MENTAL_WELLBEING_SUPPORT", "s",
                                             location="Portland, OR")
    assert "CRISIS OVERRIDE" in text
    assert "NEVER offer a Saayam volunteer as the response to a life-threatening" in text
    assert "988" in text


def test_the_shipped_prompt_routes_every_category_to_a_domain_prompt():
    on_general = [n for n in ALL_CATEGORY_NAMES
                  if prompts.resolve_prompt_key(n, prompts.CATEGORY_PROMPTS_C) == "General"]
    assert on_general == ["GENERAL_CATEGORY"]
