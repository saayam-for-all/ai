from sqlalchemy import or_, and_, func
from app.extensions import db
from app.models.help_request import HelpRequest
from app.models.category import Category
from app.models.organization import Organization
from app.utils.search_utils import normalize_query, build_contains_pattern, score_text_match


def apply_help_request_authorization(base_query, current_user):
    """
    Restrict help requests BEFORE search conditions.
    This is the critical security requirement.
    """
    role = current_user.role

    if role == "beneficiary":
        return base_query.filter(HelpRequest.created_by == current_user.id)

    if role == "volunteer":
        return base_query.filter(
            or_(
                HelpRequest.assigned_volunteer_id == current_user.id,
                HelpRequest.is_public.is_(True),
            )
        )

    if role == "organization":
        return base_query.filter(HelpRequest.organization_id == current_user.organization_id)

    if role == "admin":
        return base_query.filter(HelpRequest.admin_scope_id == current_user.admin_scope_id)

    if role == "super_admin":
        return base_query

    # Donor or any unsupported role:
    # decide business policy. For now no help request access.
    return base_query.filter(False)


def search_help_requests(query: str, current_user, per_entity_limit: int = 10) -> list[dict]:
    q = normalize_query(query)
    contains = build_contains_pattern(query)

    base_query = (
        db.session.query(HelpRequest)
        .outerjoin(Category, HelpRequest.category_id == Category.id)
        .outerjoin(Organization, HelpRequest.organization_id == Organization.id)
    )

    # Authorization first
    base_query = apply_help_request_authorization(base_query, current_user)

    # Search match second
    matched_rows = (
        base_query.filter(
            or_(
                func.lower(HelpRequest.request_id) == q,
                func.lower(HelpRequest.title).like(contains),
                func.lower(HelpRequest.description).like(contains),
                func.lower(Category.name).like(contains),
                func.lower(Organization.name).like(contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        score = score_text_match(
            query=query,
            entity_id=row.request_id,
            primary_text=row.title,
            secondary_text=row.description,
            tags=[],
        )

        results.append(
            {
                "entity_type": "help_request",
                "entity_id": row.request_id,
                "title": row.title,
                "subtitle": "Help Request",
                "score": score,
                "url": f"/help-requests/{row.id}",
            }
        )

    return results