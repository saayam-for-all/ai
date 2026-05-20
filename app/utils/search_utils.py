import re
from typing import List, Optional


def normalize_query(query: str) -> str:
    """Lowercase and trim the input query."""
    return (query or "").strip().lower()


def tokenize_query(query: str) -> List[str]:
    """
    Split the query into simple lowercase tokens.
    Example: 'Dry Cleaning' -> ['dry', 'cleaning']
    """
    normalized = normalize_query(query)
    if not normalized:
        return []

    # split on spaces and common separators
    tokens = re.split(r"[\s\-_]+", normalized)
    return [token for token in tokens if token]


def build_contains_pattern(query: str) -> str:
    """Pattern used for SQL LIKE / ILIKE."""
    return f"%{normalize_query(query)}%"


def score_text_match(
    query: str,
    entity_id: Optional[str] = None,
    primary_text: Optional[str] = None,
    secondary_text: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> int:
    """
    Simple deterministic scoring for MVP.

    Priority:
    - exact id
    - exact title/name
    - startswith title/name
    - contains title/name
    - secondary text contains
    - tag match
    """
    q = normalize_query(query)
    if not q:
        return 0

    score = 0

    entity_id_value = (entity_id or "").strip().lower()
    primary = (primary_text or "").strip().lower()
    secondary = (secondary_text or "").strip().lower()
    tag_values = [str(tag).strip().lower() for tag in (tags or [])]

    if entity_id_value == q:
        score = max(score, 100)

    if primary == q:
        score = max(score, 90)
    elif primary.startswith(q):
        score = max(score, 80)
    elif q in primary:
        score = max(score, 65)

    if q in secondary:
        score = max(score, 40)

    if any(q in tag for tag in tag_values):
        score = max(score, 45)

    return score


def should_auto_navigate(results: List[dict]) -> bool:
    """
    Safe MVP rule:
    auto-navigate only if there is exactly one result
    and that result is a strong match.
    """
    if len(results) != 1:
        return False

    return results[0].get("score", 0) >= 95