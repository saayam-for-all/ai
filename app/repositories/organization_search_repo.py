from sqlalchemy import or_, func
from app.extensions import db
from app.models.organization import Organization
from app.utils.search_utils import normalize_query, build_contains_pattern, score_text_match


def search_organizations(query: str, current_user, per_entity_limit: int = 10) -> list[dict]:
    q = normalize_query(query)
    contains = build_contains_pattern(query)

    # If orgs are visible to all authenticated users, no special auth filter needed.
    matched_rows = (
        db.session.query(Organization)
        .filter(
            or_(
                func.lower(Organization.org_id) == q,
                func.lower(Organization.name).like(contains),
                func.lower(Organization.description).like(contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        score = score_text_match(
            query=query,
            entity_id=row.org_id,
            primary_text=row.name,
            secondary_text=row.description,
            tags=[],
        )

        results.append(
            {
                "entity_type": "organization",
                "entity_id": row.org_id,
                "title": row.name,
                "subtitle": "Organization",
                "score": score,
                "url": f"/organizations/{row.id}",
            }
        )

    return results