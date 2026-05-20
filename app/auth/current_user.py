import os
from dataclasses import dataclass
from typing import Optional
from flask import g, request


@dataclass
class CurrentUser:
    id: str
    role: str
    organization_id: Optional[int] = None
    admin_scope_id: Optional[int] = None


def get_current_user() -> CurrentUser:
    """
    Assumes your auth middleware already put the user in flask.g.
    In DEV mode, falls back to X-Dev-User-Id and X-Dev-User-Role headers.
    """
    user = getattr(g, "current_user", None)
    if user:
        return CurrentUser(
            id=user.id,
            role=user.role,
            organization_id=getattr(user, "organization_id", None),
            admin_scope_id=getattr(user, "admin_scope_id", None),
        )

    user_id_header = os.getenv("AUTH_USER_ID_HEADER", "X-Api-User-Id")
    user_role_header = os.getenv("AUTH_USER_ROLE_HEADER", "X-Api-User-Role")
    user_id = request.headers.get(user_id_header)
    user_role = request.headers.get(user_role_header)

    if user_id and user_role:
        return CurrentUser(id=user_id, role=user_role)

    if os.getenv("FLASK_ENV") == "development":
        return CurrentUser(
            id=request.headers.get("X-Dev-User-Id", "SID-00-000-000-058"),
            role=request.headers.get("X-Dev-User-Role", "super_admin"),
        )

    raise ValueError("Authenticated user not found in request context")