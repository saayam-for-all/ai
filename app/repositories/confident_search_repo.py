"""
app/repositories/confident_search_repo.py

GenAI team responsibility: Confident Search (Exact Match / Redirect Handler).

This runs BEFORE fuzzy search. If the query matches a known ID pattern
and a DB record is found, we return a single result with score=100 and
the service will set auto_navigate=True, skipping fuzzy entirely.

Per the MOM:
  - user_id, primary_email_address  → redirect to User Profile
  - request_id (e.g. REQ-102)       → redirect to Help Request
  - org_id                           → redirect to Organization page
  - category_id                      → redirect to Category page
"""

import re
from sqlalchemy import func
from app.extensions import db
from app.models.user import User
from app.models.help_request import HelpRequest
from app.models.organization import Organization
from app.models.category import Category


# ---------------------------------------------------------------------------
# ID pattern checks  (same patterns as search_utils, kept local to avoid
# circular imports from utils importing models)
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_REQ_RE   = re.compile(r"^REQ-\d+$",  re.IGNORECASE)
_USR_RE   = re.compile(r"^USR-\d+$",  re.IGNORECASE)
_ORG_RE   = re.compile(r"^ORG-\d+$",  re.IGNORECASE)
_CAT_RE   = re.compile(r"^CAT-\d+$",  re.IGNORECASE)


def _is_uuid(q: str) -> bool:
    return bool(_UUID_RE.match(q))

def _is_email(q: str) -> bool:
    return bool(_EMAIL_RE.match(q))

def _is_req_id(q: str) -> bool:
    return bool(_REQ_RE.match(q))

def _is_usr_id(q: str) -> bool:
    return bool(_USR_RE.match(q))

def _is_org_id(q: str) -> bool:
    return bool(_ORG_RE.match(q))

def _is_cat_id(q: str) -> bool:
    return bool(_CAT_RE.match(q))


# ---------------------------------------------------------------------------
# Authorization helpers (mirrors the repo-level auth, applied here too)
# ---------------------------------------------------------------------------

def _user_is_authorized(user_row: User, current_user) -> bool:
    role = current_user.role
    if role in {"admin", "super_admin"}:
        return True
    if role == "organization":
        return user_row.organization_id == current_user.organization_id
    return user_row.id == current_user.id


def _help_request_is_authorized(req_row: HelpRequest, current_user) -> bool:
    role = current_user.role
    if role == "super_admin":
        return True
    if role == "admin":
        return req_row.admin_scope_id == current_user.admin_scope_id
    if role == "organization":
        return req_row.organization_id == current_user.organization_id
    if role == "volunteer":
        return (
            req_row.assigned_volunteer_id == current_user.id
            or req_row.is_public
        )
    if role == "beneficiary":
        return req_row.created_by == current_user.id
    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def confident_search(query: str, current_user) -> dict | None:
    """
    Attempt an exact-ID lookup across all relevant entities.

    Returns a single result dict (score=100) if found and authorized,
    or None if the query does not look like an ID / no record found.

    The caller (UniversalSearchService) uses the non-None return to
    short-circuit fuzzy search and set auto_navigate=True.
    """
    q = query.strip()
    q_lower = q.lower()

    # --- User: UUID or USR-xxx format → check user_id column
    if _is_uuid(q) or _is_usr_id(q):
        row = (
            db.session.query(User)
            .filter(func.lower(User.user_id) == q_lower)
            .first()
        )
        if row and _user_is_authorized(row, current_user):
            return _user_result(row)
        # Found but not authorized → return nothing (data-leakage prevention)
        if row:
            return None

    # --- User: exact email match
    if _is_email(q):
        # User model doesn't have email column yet — placeholder for when it does.
        # When ddl_users.sql adds primary_email_address, add:
        #   .filter(func.lower(User.primary_email_address) == q_lower)
        # For now, fall through to fuzzy.
        pass

    # --- Help Request: REQ-xxx or UUID
    if _is_req_id(q) or _is_uuid(q):
        row = (
            db.session.query(HelpRequest)
            .filter(func.lower(HelpRequest.request_id) == q_lower)
            .first()
        )
        if row and _help_request_is_authorized(row, current_user):
            return _help_request_result(row)
        if row:
            return None

    # --- Organization: ORG-xxx or UUID
    if _is_org_id(q) or _is_uuid(q):
        row = (
            db.session.query(Organization)
            .filter(func.lower(Organization.org_id) == q_lower)
            .first()
        )
        if row:  # orgs visible to all authenticated users per MOM
            return _org_result(row)

    # --- Category: CAT-xxx or UUID
    if _is_cat_id(q) or _is_uuid(q):
        row = (
            db.session.query(Category)
            .filter(func.lower(Category.category_id) == q_lower)
            .first()
        )
        if row:  # categories are public
            return _category_result(row)

    return None  # not an ID pattern or no match found


# ---------------------------------------------------------------------------
# Result builders  (score=100 signals exact/confident match to the service)
# ---------------------------------------------------------------------------

def _user_result(row: User) -> dict:
    return {
        "entity_type": "user",
        "entity_id": row.user_id,
        "title": row.full_name,
        "subtitle": f"Username: {row.username}",
        "score": 100,
        "url": f"/users/{row.id}",
        "match_type": "confident",
    }


def _help_request_result(row: HelpRequest) -> dict:
    return {
        "entity_type": "help_request",
        "entity_id": row.request_id,
        "title": row.title,
        "subtitle": "Help Request",
        "score": 100,
        "url": f"/help-requests/{row.id}",
        "match_type": "confident",
    }


def _org_result(row: Organization) -> dict:
    return {
        "entity_type": "organization",
        "entity_id": row.org_id,
        "title": row.name,
        "subtitle": "Organization",
        "score": 100,
        "url": f"/organizations/{row.id}",
        "match_type": "confident",
    }


def _category_result(row: Category) -> dict:
    return {
        "entity_type": "category",
        "entity_id": row.category_id,
        "title": row.name or row.label,
        "subtitle": "Category / Tag",
        "score": 100,
        "url": f"/categories/{row.id}",
        "match_type": "confident",
    }