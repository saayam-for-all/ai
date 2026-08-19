"""Translate authenticated API identity into the database search contract."""

from dataclasses import dataclass
from typing import Optional, Tuple

from app.auth.current_user import AuthenticationRequired


_ROLE_ACCESS_LEVELS = {
    "guest": 0,
    "beneficiary": 1,
    "requester": 1,
    "member": 2,
    "volunteer": 2,
    "organization": 3,
    "organization_admin": 3,
    "org_admin": 3,
    "admin": 4,
    "super_admin": 4,
}


@dataclass(frozen=True)
class SearchScope:
    user_id: str
    role: str
    access_level: int
    allowed_request_owner_ids: Tuple[str, ...]
    allowed_user_ids: Tuple[str, ...]
    allowed_org_ids: Tuple[str, ...]

    @property
    def is_admin(self) -> bool:
        return self.access_level >= 4

    def database_parameters(self) -> dict:
        return {
            "requester_user_id": self.user_id,
            "requester_access_level": self.access_level,
            "allowed_request_owner_ids": (
                list(self.allowed_request_owner_ids)
                if self.allowed_request_owner_ids else None
            ),
            "allowed_user_ids": (
                list(self.allowed_user_ids) if self.allowed_user_ids else None
            ),
            "allowed_org_ids": (
                list(self.allowed_org_ids) if self.allowed_org_ids else None
            ),
        }


def _value(current_user, name, default=None):
    if isinstance(current_user, dict):
        return current_user.get(name, default)
    return getattr(current_user, name, default)


def _identifiers(value) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    return tuple(
        dict.fromkeys(
            str(item) for item in value if item is not None and str(item)
        )
    )


def _with_identifier(
    values: Tuple[str, ...], identifier: Optional[str]
) -> Tuple[str, ...]:
    if identifier is None or not str(identifier):
        return values
    return tuple(dict.fromkeys((*values, str(identifier))))


def build_search_scope(current_user) -> SearchScope:
    if current_user is None:
        raise AuthenticationRequired("Authenticated user is required for search")

    user_id = _value(current_user, "id") or _value(current_user, "user_id")
    role = (
        str(_value(current_user, "role", ""))
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if not user_id or not role:
        raise AuthenticationRequired("Authenticated user id and role are required for search")

    access_level = _ROLE_ACCESS_LEVELS.get(role, 0)
    request_owner_ids = _identifiers(
        _value(current_user, "allowed_request_owner_ids")
    )
    user_ids = _identifiers(_value(current_user, "allowed_user_ids"))
    org_ids = _identifiers(_value(current_user, "allowed_org_ids"))

    self_visible_roles = {
        "beneficiary",
        "requester",
        "member",
        "volunteer",
        "organization",
        "organization_admin",
        "org_admin",
        "admin",
        "super_admin",
    }
    if role in self_visible_roles:
        request_owner_ids = _with_identifier(request_owner_ids, str(user_id))
        user_ids = _with_identifier(user_ids, str(user_id))

    organization_id = _value(current_user, "organization_id")
    if role in {"organization", "organization_admin", "org_admin"}:
        org_ids = _with_identifier(org_ids, organization_id)

    return SearchScope(
        user_id=str(user_id),
        role=role,
        access_level=access_level,
        allowed_request_owner_ids=request_owner_ids,
        allowed_user_ids=user_ids,
        allowed_org_ids=org_ids,
    )
