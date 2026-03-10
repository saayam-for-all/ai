from sqlalchemy import or_, func
from app.extensions import db
from app.models.category import Category
from app.utils.search_utils import normalize_query, build_contains_pattern, score_text_match


def search_categories(query: str, current_user, per_entity_limit: int = 10) -> list[dict]:
    q = normalize_query(query)
    contains = build_contains_pattern(query)

    matched_rows = (
        db.session.query(Category)
        .filter(
            or_(
                func.lower(Category.category_id) == q,
                func.lower(Category.name).like(contains),
                func.lower(Category.label).like(contains),
                func.lower(Category.description).like(contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        primary_text = row.name or row.label

        score = score_text_match(
            query=query,
            entity_id=row.category_id,
            primary_text=primary_text,
            secondary_text=row.description,
            tags=[row.label] if row.label else [],
        )

        results.append(
            {
                "entity_type": "category",
                "entity_id": row.category_id,
                "title": primary_text,
                "subtitle": "Category / Tag",
                "score": score,
                "url": f"/categories/{row.id}",
            }
        )

    return results