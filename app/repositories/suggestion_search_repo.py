"""
app/repositories/suggestion_search_repo.py
"""

from typing import List
from sqlalchemy import or_, func
from sqlalchemy.exc import ProgrammingError
from app.extensions import db
from app.models.user import User
from app.models.help_request import HelpRequest
from app.models.organization import Organization
from app.models.category import Category
from app.models.company import Company
from app.repositories.confident_search_repo import _user_is_authorized, _help_request_is_authorized
from app.utils.search_utils import normalize_query


def _build_prefix(value: str) -> str:
    return f"{value}%"


def _build_contains(value: str) -> str:
    return f"%{value}%"


def _suggestion_result(entity_type: str, entity_id: str, title: str, subtitle: str, url: str, score: int, match_type: str) -> dict:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": title,
        "subtitle": subtitle,
        "url": url,
        "score": score,
        "match_type": match_type,
    }


def _search_users(query: str, current_user, per_entity_limit: int) -> List[dict]:
    q_prefix = _build_prefix(query)
    q_contains = _build_contains(query)

    matched_rows = (
        db.session.query(User)
        .filter(
            or_(
                func.lower(User.user_id).like(q_prefix),
                func.lower(User.primary_email_address).like(q_prefix),
                func.lower(User.full_name).like(q_contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        if not _user_is_authorized(row, current_user):
            continue

        if row.user_id.lower().startswith(query):
            match_type = "id_prefix"
            score = 100
        elif query in (row.primary_email_address or "").lower():
            match_type = "email"
            score = 80
        else:
            match_type = "name"
            score = 70

        results.append(
            _suggestion_result(
                "user",
                row.user_id,
                row.full_name,
                f"Email: {row.primary_email_address or 'N/A'}",
                f"/users/{row.user_id}",
                score,
                match_type,
            )
        )

    return results


def _search_help_requests(query: str, current_user, per_entity_limit: int) -> List[dict]:
    q_prefix = _build_prefix(query)
    q_contains = _build_contains(query)

    matched_rows = (
        db.session.query(HelpRequest)
        .filter(
            or_(
                func.lower(HelpRequest.req_id).like(q_prefix),
                func.lower(HelpRequest.req_subj).like(q_contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        if not _help_request_is_authorized(row, current_user):
            continue

        if row.req_id.lower().startswith(query):
            match_type = "id_prefix"
            score = 95
        else:
            match_type = "subject"
            score = 60

        results.append(
            _suggestion_result(
                "help_request",
                row.req_id,
                row.req_subj,
                "Help Request",
                f"/help-requests/{row.req_id}",
                score,
                match_type,
            )
        )

    return results


def _search_organizations(query: str, current_user, per_entity_limit: int) -> List[dict]:
    q_prefix = _build_prefix(query)
    q_contains = _build_contains(query)

    matched_rows = (
        db.session.query(Organization)
        .filter(
            or_(
                func.lower(Organization.org_id).like(q_prefix),
                func.lower(Organization.org_name).like(q_contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        if row.org_id.lower().startswith(query):
            match_type = "id_prefix"
            score = 90
        else:
            match_type = "name"
            score = 65

        results.append(
            _suggestion_result(
                "organization",
                row.org_id,
                row.org_name,
                f"Organization — {row.email or 'no email'}",
                f"/organizations/{row.org_id}",
                score,
                match_type,
            )
        )

    return results


def _search_categories(query: str, current_user, per_entity_limit: int) -> List[dict]:
    q_prefix = _build_prefix(query)
    q_contains = _build_contains(query)

    matched_rows = (
        db.session.query(Category)
        .filter(
            or_(
                func.lower(Category.cat_id).like(q_prefix),
                func.lower(Category.cat_name).like(q_contains),
            )
        )
        .limit(per_entity_limit)
        .all()
    )

    results = []
    for row in matched_rows:
        if row.cat_id.lower().startswith(query):
            match_type = "id_prefix"
            score = 85
        else:
            match_type = "name"
            score = 55

        results.append(
            _suggestion_result(
                "category",
                row.cat_id,
                row.cat_name,
                "Category",
                f"/categories/{row.cat_id}",
                score,
                match_type,
            )
        )

    return results


def _search_companies(query: str, current_user, per_entity_limit: int) -> List[dict]:
    q_prefix = _build_prefix(query)
    q_contains = _build_contains(query)

    try:
        matched_rows = (
            db.session.query(Company)
            .filter(
                or_(
                    func.lower(Company.company_id).like(q_prefix),
                    func.lower(Company.name).like(q_contains),
                )
            )
            .limit(per_entity_limit)
            .all()
        )
    except ProgrammingError:
        return []

    results = []
    for row in matched_rows:
        if row.company_id.lower().startswith(query):
            match_type = "id_prefix"
            score = 88
        else:
            match_type = "name"
            score = 58

        results.append(
            _suggestion_result(
                "company",
                row.company_id,
                row.name,
                "Company",
                f"/companies/{row.company_id}",
                score,
                match_type,
            )
        )

    return results


def search_suggestions(query: str, current_user, limit: int) -> List[dict]:
    query = normalize_query(query)
    per_entity_limit = max(1, limit)

    suggestions = []
    suggestions.extend(_search_users(query, current_user, per_entity_limit))
    suggestions.extend(_search_help_requests(query, current_user, per_entity_limit))
    suggestions.extend(_search_organizations(query, current_user, per_entity_limit))
    suggestions.extend(_search_categories(query, current_user, per_entity_limit))
    suggestions.extend(_search_companies(query, current_user, per_entity_limit))

    # Deduplicate by type+id and sort by score.
    seen = set()
    unique_results = []
    for item in sorted(suggestions, key=lambda item: (-item["score"], item["entity_type"], item["title"])):
        key = (item["entity_type"], item["entity_id"])
        if key in seen:
            continue
        seen.add(key)
        unique_results.append(item)
        if len(unique_results) >= limit:
            break

    return unique_results
