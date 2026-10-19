"""Load the classification golden set and refuse a malformed one.

A golden set is a fixed list of requests, each with the category a person has
agreed is right. It is only useful if it is trusted, so every problem that
would make a score quietly wrong is an error at load time rather than a
surprise in a report: a label that is not in the classifier's taxonomy, a
duplicated id, a blank description.

Labels are category *names* from `utils/predict_category_list.py` (the
80-entry taxonomy the classifier walks), not from `utils/categories.py`. Names
are used rather than ids because a reviewer can check "PLUMBING" by reading it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from utils.predict_category_list import category_name_to_number

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden" / "classification.jsonl"

#: Cases the taxonomy has no right answer for. They are run and reported, so a
#: reader can see where requests land today, but never scored: no answer could
#: pass them, and counting them would hide real regressions behind a gap.
KNOWN_GAP_TAG = "known-gap"


class GoldenSetError(ValueError):
    """The golden set file is malformed; no score built on it can be trusted."""


@dataclass(frozen=True)
class GoldenCase:
    """One labelled request.

    `expected` is a category name at any depth. A case labelled with a parent
    (for example MEDICAL_CONSULTATION) passes for any of its children, which
    lets a labeller be exactly as specific as the request allows.
    """

    id: str
    description: str
    expected: str | None
    tags: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    @property
    def expected_id(self) -> str | None:
        """The taxonomy id of the expected category, for example "3.3.1"."""
        return category_name_to_number.get(self.expected) if self.expected else None

    @property
    def scored(self) -> bool:
        """Whether this case counts towards the score and the gate."""
        return KNOWN_GAP_TAG not in self.tags


def _parse_line(line_number: int, raw: str) -> GoldenCase:
    """Build one case from one JSONL line, or say exactly what is wrong with it."""
    where = f"line {line_number}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GoldenSetError(f"{where}: not valid JSON ({error})") from error
    if not isinstance(data, dict):
        raise GoldenSetError(f"{where}: each line must be a JSON object")

    case_id = data.get("id")
    description = data.get("description")
    expected = data.get("expected")
    tags = data.get("tags", [])

    if not isinstance(case_id, str) or not case_id.strip():
        raise GoldenSetError(f"{where}: 'id' must be a non-empty string")
    where = f"{where} ({case_id})"
    if not isinstance(description, str) or not description.strip():
        raise GoldenSetError(f"{where}: 'description' must be a non-empty string")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise GoldenSetError(f"{where}: 'tags' must be a list of strings")

    is_gap = KNOWN_GAP_TAG in tags
    if is_gap and expected is not None:
        raise GoldenSetError(f"{where}: a known-gap case has no expected category; use null")
    if not is_gap:
        if not isinstance(expected, str) or expected not in category_name_to_number:
            raise GoldenSetError(
                f"{where}: 'expected' {expected!r} is not a category name in "
                "utils/predict_category_list.py"
            )

    return GoldenCase(
        id=case_id,
        description=description,
        expected=expected,
        tags=tuple(tags),
        note=str(data.get("note", "")),
    )


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[GoldenCase]:
    """Read every case from `path`, in file order.

    Blank lines are allowed so the file can be grouped by hand. Raises
    `GoldenSetError` on the first problem, naming the line.
    """
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        case = _parse_line(line_number, raw)
        if case.id in seen:
            raise GoldenSetError(f"line {line_number}: duplicate id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    if not any(case.scored for case in cases):
        raise GoldenSetError(f"{path.name}: no scored cases")
    return cases
