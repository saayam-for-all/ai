from sqlalchemy import or_, func
from app.extensions import db
from app.models.user import User
from app.utils.search_utils import normalize_query, build_contains_pattern, score_text_match


def apply_user_authorization(base_query, current_user):
    """
    Replace these rules with exact business-approved rules.
    Conservative MVP:
    - admin and super_admin can search broadly
    - organization can search users in same org
    - others only themselves
    """
    role = current_user.role

    if role in {"admin", "super_admin"}:
        return base_query

    if role == "organization":
        return base_query.filter(User.organization_id == current_user.organization_id)

    return base_query.filter(User.id == current_user.id)


def search_users(query: str, current_user, per_entity_limit: int = 10) -> list[dict]:
    q = normalize_query(query)
    contains = build_contains_pattern(query)

    base_query = db.session.query(User)
    base_query = apply_user_authorization(base_query, current_user)

    matched_rows = (
        base_query.filter(
            or_(
                func.lower(User.user_id) == q,
                func.lower(User.full_name).like(contains),
                func.lower(User.username).like(contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        score = score_text_match(
            query=query,
            entity_id=row.user_id,
            primary_text=row.full_name,
            secondary_text=row.username,
            tags=[],
        )

        results.append(
            {
                "entity_type": "user",
                "entity_id": row.user_id,
                "title": row.full_name,
                "subtitle": f"Username: {row.username}",
                "score": score,
                "url": f"/users/{row.id}",
            }
        )

    return results