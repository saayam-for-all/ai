"""
app/repositories/confident_search_repo.py

GenAI team responsibility: Confident Search (Exact Match / Redirect Handler).

This runs BEFORE fuzzy search. If the query matches a known ID pattern
and a DB record is found, we return a single result with score=100 and
the service will set auto_navigate=True, skipping fuzzy entirely.

Per the MOM:
  - user_id, primary_email_address  → redirect to User Profile
  - req_id (e.g. REQ-102)           → redirect to Help Request
  - org_id                           → redirect to Organization page
  - cat_id                           → redirect to Category page
"""

import re
from typing import Optional
from sqlalchemy import func
from app.extensions import db
from app.models.user import User
from app.models.help_request import HelpRequest
from app.models.organization import Organization
from app.models.category import Category


# ---------------------------------------------------------------------------
# ID pattern checks
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_REQ_RE   = re.compile(r"^REQ-\d{2}-\d{3}-\d{3}-\d{4}$")
_USR_RE   = re.compile(r"^SID-\d{2}-\d{3}-\d{3}-\d{3}$")
_ORG_RE   = re.compile(r"^ORG-\d+$")           # org table empty; pattern TBD
_CAT_RE   = re.compile(r"^\d+(\.\d+)*$")       # matches 1, 1.1, 0.0.0.0.0


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
# Authorization helpers
# ---------------------------------------------------------------------------

def _user_is_authorized(user_row: User, current_user) -> bool:
    role = current_user.role
    if role in {"admin", "super_admin"}:
        return True
    # beneficiary/volunteer can only see their own profile
    return user_row.user_id == current_user.id


def _help_request_is_authorized(req_row: HelpRequest, current_user) -> bool:
    role = current_user.role
    if role == "super_admin":
        return True
    if role in {"admin", "organization", "volunteer"}:
        return req_row.to_public or True  # no org/scope columns on request table
    if role == "beneficiary":
        return req_row.req_user_id == current_user.id
    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def confident_search(query: str, current_user) -> Optional[dict]:
    """
    Attempt an exact-ID lookup across all relevant entities.

    Returns a single result dict (score=100) if found and authorized,
    or None if the query does not look like an ID / no record found.
    """
    q = query.strip()
    q_lower = q.lower()

    # --- User: USR-xxx format
    if _is_usr_id(q):
        row = (
            db.session.query(User)
            .filter(func.lower(User.user_id) == q_lower)
            .first()
        )
        if row and _user_is_authorized(row, current_user):
            return _user_result(row)
        if row:
            return None

    # --- User: exact email match
    if _is_email(q):
        row = (
            db.session.query(User)
            .filter(func.lower(User.primary_email_address) == q_lower)
            .first()
        )
        if row and _user_is_authorized(row, current_user):
            return _user_result(row)
        if row:
            return None

    # --- User or HelpRequest: UUID
    if _is_uuid(q):
        row = (
            db.session.query(User)
            .filter(func.lower(User.user_id) == q_lower)
            .first()
        )
        if row and _user_is_authorized(row, current_user):
            return _user_result(row)
        if row:
            return None

        row = (
            db.session.query(HelpRequest)
            .filter(func.lower(HelpRequest.req_id) == q_lower)
            .first()
        )
        if row and _help_request_is_authorized(row, current_user):
            return _help_request_result(row)
        if row:
            return None

    # --- Help Request: REQ-xxx
    if _is_req_id(q):
        row = (
            db.session.query(HelpRequest)
            .filter(func.lower(HelpRequest.req_id) == q_lower)
            .first()
        )
        if row and _help_request_is_authorized(row, current_user):
            return _help_request_result(row)
        if row:
            return None

    # --- Organization: ORG-xxx
    if _is_org_id(q):
        row = (
            db.session.query(Organization)
            .filter(func.lower(Organization.org_id) == q_lower)
            .first()
        )
        if row:
            return _org_result(row)

    # --- Category: CAT-xxx
    if _is_cat_id(q):
        row = (
            db.session.query(Category)
            .filter(func.lower(Category.cat_id) == q_lower)
            .first()
        )
        if row:
            return _category_result(row)

    return None


# ---------------------------------------------------------------------------
# Result builders
# ---------------------------------------------------------------------------

def _user_result(row: User) -> dict:
    return {
        "entity_type": "user",
        "entity_id": row.user_id,
        "title": row.full_name,
        "subtitle": f"Email: {row.primary_email_address}",
        "score": 100,
        "url": f"/users/{row.user_id}",
        "match_type": "confident",
    }


def _help_request_result(row: HelpRequest) -> dict:
    return {
        "entity_type": "help_request",
        "entity_id": row.req_id,
        "title": row.req_subj,
        "subtitle": "Help Request",
        "score": 100,
        "url": f"/help-requests/{row.req_id}",
        "match_type": "confident",
    }


def _org_result(row: Organization) -> dict:
    return {
        "entity_type": "organization",
        "entity_id": row.org_id,
        "title": row.org_name,
        "subtitle": "Organization",
        "score": 100,
        "url": f"/organizations/{row.org_id}",
        "match_type": "confident",
    }


def _category_result(row: Category) -> dict:
    return {
        "entity_type": "category",
        "entity_id": row.cat_id,
        "title": row.cat_name,
        "subtitle": "Category / Tag",
        "score": 100,
        "url": f"/categories/{row.cat_id}",
        "match_type": "confident",
    }
