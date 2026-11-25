import pytest

from config.all_prompts import (
    CATEGORY_PROMPTS,
    CATEGORY_PROMPTS_NO_HALLUCINATIONS,
)

from utils import prompts
from utils import prompts_no_hallucination_reviewed


@pytest.fixture(params=[
    "standard",
    "no_hallucinations",
])
def category_prompts(request):
    """Run tests against both prompt dictionaries."""
    if request.param == "standard":
        return CATEGORY_PROMPTS

    return CATEGORY_PROMPTS_NO_HALLUCINATIONS


def test_category_prompt_count(category_prompts):
    """Ensure all 37 existing prompts are preserved."""
    assert len(category_prompts) == 37


def test_general_fallback_exists(category_prompts):
    """Ensure the default fallback prompt is available."""
    assert "General" in category_prompts


def test_category_prompt_keys_match():
    """Ensure both dictionaries support the same categories."""
    assert (
        CATEGORY_PROMPTS.keys()
        == CATEGORY_PROMPTS_NO_HALLUCINATIONS.keys()
    )


def test_category_prompt_formatting(category_prompts):
    """Ensure blank lines surround the base instruction."""
    for category, prompt in category_prompts.items():
        assert "\n\n{base_instruction}\n\n" in prompt, (
            f"Incorrect base instruction formatting: {category}"
        )


def test_category_prompt_indentation(category_prompts):
    """Ensure prompt strings contain no unintended indentation."""
    for category, prompt in category_prompts.items():
        for line in prompt.splitlines():
            assert not line.startswith((" ", "\t")), (
                f"Unexpected indentation in {category}: {line!r}"
            )


def test_standard_prompt_import_consistency():
    """Ensure the standard prompt module uses the config."""
    assert prompts.category_prompts is CATEGORY_PROMPTS


def test_no_hallucination_prompt_import_consistency():
    """Ensure the no-hallucination module uses the config."""
    assert (
        prompts_no_hallucination_reviewed.category_prompts
        is CATEGORY_PROMPTS_NO_HALLUCINATIONS
    )