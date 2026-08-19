import os
from dataclasses import dataclass
from typing import Optional, Tuple
from flask import g, request


@dataclass
class CurrentUser:
    id: str
    role: str
    organization_id: Optional[str] = None
    admin_scope_id: Optional[str] = None
    allowed_request_owner_ids: Tuple[str, ...] = ()
    allowed_user_ids: Tuple[str, ...] = ()
    allowed_org_ids: Tuple[str, ...] = ()


class AuthenticationRequired(ValueError):
    """Raised when trusted authentication context is missing."""


def _as_identifier_tuple(value) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    return tuple(str(item) for item in value if item is not None and str(item))


def _identity_value(identity, name, default=None):
    if isinstance(identity, dict):
        return identity.get(name, default)
    return getattr(identity, name, default)


def get_current_user() -> CurrentUser:
    """
    Assumes trusted auth middleware put the user in flask.g. API Gateway
    identity headers provide the basic user id and role. Entity scopes are
    accepted only from trusted middleware, never from client-supplied headers.
    """
    user = getattr(g, "current_user", None)
    if user:
        return CurrentUser(
            id=_identity_value(user, "id") or _identity_value(user, "user_id"),
            role=_identity_value(user, "role"),
            organization_id=_identity_value(user, "organization_id"),
            admin_scope_id=_identity_value(user, "admin_scope_id"),
            allowed_request_owner_ids=_as_identifier_tuple(
                _identity_value(user, "allowed_request_owner_ids")
            ),
            allowed_user_ids=_as_identifier_tuple(
                _identity_value(user, "allowed_user_ids")
            ),
            allowed_org_ids=_as_identifier_tuple(
                _identity_value(user, "allowed_org_ids")
            ),
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

    raise AuthenticationRequired("Authenticated user not found in request context")
