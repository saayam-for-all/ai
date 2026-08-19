import unittest
from types import SimpleNamespace

from app.auth.current_user import AuthenticationRequired, CurrentUser
from app.auth.search_scope import build_search_scope


class SearchScopeTestCase(unittest.TestCase):
    def test_admin_maps_to_database_access_level_four(self):
        scope = build_search_scope(CurrentUser(id="admin-1", role="super_admin"))

        self.assertEqual(scope.access_level, 4)
        self.assertTrue(scope.is_admin)
        self.assertIn("admin-1", scope.allowed_user_ids)

    def test_non_admin_scope_includes_trusted_entity_ids(self):
        user = CurrentUser(
            id="volunteer-1",
            role="volunteer",
            allowed_request_owner_ids=("requester-1",),
            allowed_user_ids=("requester-1",),
            allowed_org_ids=("org-1",),
        )

        scope = build_search_scope(user)

        self.assertEqual(scope.access_level, 2)
        self.assertEqual(
            scope.allowed_request_owner_ids,
            ("requester-1", "volunteer-1"),
        )
        self.assertEqual(scope.allowed_user_ids, ("requester-1", "volunteer-1"))
        self.assertEqual(scope.allowed_org_ids, ("org-1",))

    def test_org_admin_includes_own_organization(self):
        user = CurrentUser(
            id="org-admin-1",
            role="org-admin",
            organization_id="org-42",
        )

        scope = build_search_scope(user)

        self.assertEqual(scope.role, "org_admin")
        self.assertEqual(scope.access_level, 3)
        self.assertEqual(scope.allowed_org_ids, ("org-42",))

    def test_guest_and_unknown_roles_fail_closed(self):
        for role in ("guest", "unexpected-role"):
            with self.subTest(role=role):
                scope = build_search_scope(CurrentUser(id="user-1", role=role))
                self.assertEqual(scope.allowed_request_owner_ids, ())
                self.assertEqual(scope.allowed_user_ids, ())
                self.assertEqual(scope.allowed_org_ids, ())

    def test_mapping_identity_is_supported(self):
        scope = build_search_scope({"user_id": "user-1", "role": "beneficiary"})
        self.assertEqual(scope.user_id, "user-1")
        self.assertEqual(scope.allowed_user_ids, ("user-1",))

    def test_missing_identity_is_rejected(self):
        for user in (None, SimpleNamespace(id="", role="volunteer")):
            with self.subTest(user=user):
                with self.assertRaises(AuthenticationRequired):
                    build_search_scope(user)


if __name__ == "__main__":
    unittest.main()
