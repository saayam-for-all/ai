from dataclasses import dataclass
from flask import g


@dataclass
class CurrentUser:
    id: int
    role: str
    organization_id: int | None = None
    admin_scope_id: int | None = None


def get_current_user() -> CurrentUser:
    """
    Assumes your auth middleware already put the user in flask.g.
    Adjust this based on your real auth flow.
    """
    user = getattr(g, "current_user", None)
    if not user:
        raise ValueError("Authenticated user not found in request context")

    return CurrentUser(
        id=user.id,
        role=user.role,
        organization_id=getattr(user, "organization_id", None),
        admin_scope_id=getattr(user, "admin_scope_id", None),
    )