from pathlib import Path


PROMPTS_FILE = Path(__file__).resolve().parents[1] / "utils" / "prompts.py"


def test_prompts_use_correct_organization_name():
    content = PROMPTS_FILE.read_text(encoding="utf-8")

    assert "SaayamForAll" not in content, (
        "Prompts must use 'Saayam For All' instead of 'SaayamForAll'."
    )

    assert "Saayam For All" in content, (
        "The correct organization name should appear in the prompts."
    )
