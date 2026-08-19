import unittest
from types import SimpleNamespace

from app.auth.current_user import CurrentUser
from app.repositories.confident_search_repo import (
    _help_request_is_authorized,
    _organization_is_authorized,
    _user_is_authorized,
)


class SearchAuthorizationTestCase(unittest.TestCase):
    def test_user_search_is_limited_to_admin_or_explicit_scope(self):
        row = SimpleNamespace(user_id="SID-2")
        beneficiary = CurrentUser(id="SID-1", role="beneficiary")
        scoped_volunteer = CurrentUser(
            id="SID-1", role="volunteer", allowed_user_ids=("SID-2",)
        )

        self.assertFalse(_user_is_authorized(row, beneficiary))
        self.assertTrue(_user_is_authorized(row, scoped_volunteer))

    def test_help_request_no_longer_allows_every_non_admin(self):
        private_row = SimpleNamespace(
            req_user_id="SID-2", to_public=False
        )
        public_row = SimpleNamespace(
            req_user_id="SID-2", to_public=True
        )
        volunteer = CurrentUser(id="SID-1", role="volunteer")

        self.assertFalse(_help_request_is_authorized(private_row, volunteer))
        self.assertTrue(_help_request_is_authorized(public_row, volunteer))

    def test_organization_requires_admin_or_explicit_scope(self):
        row = SimpleNamespace(org_id="ORG-2")
        org_admin = CurrentUser(
            id="SID-1", role="organization_admin", organization_id="ORG-1"
        )
        admin = CurrentUser(id="SID-9", role="admin")

        self.assertFalse(_organization_is_authorized(row, org_admin))
        self.assertTrue(_organization_is_authorized(row, admin))


if __name__ == "__main__":
    unittest.main()
