import unittest
from unittest.mock import patch

from app.auth.current_user import CurrentUser
from app.services.universal_search_service import UniversalSearchService


class UniversalSearchServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.service = UniversalSearchService()
        self.user = CurrentUser(id="admin-1", role="super_admin")

    @patch("app.services.universal_search_service.search_organizations")
    @patch("app.services.universal_search_service.search_users")
    @patch("app.services.universal_search_service.search_help_requests")
    @patch("app.services.universal_search_service.confident_search")
    def test_fans_out_across_db_mvp_entities_and_ranks_results(
        self, confident, requests, users, organizations
    ):
        confident.return_value = None
        requests.return_value = [{
            "entity_type": "help_request", "entity_id": "REQ-1", "score": 70
        }]
        users.return_value = [{
            "entity_type": "user", "entity_id": "SID-1", "score": 90
        }]
        organizations.return_value = [{
            "entity_type": "organization", "entity_id": "ORG-1", "score": 80
        }]

        response = self.service.search("medical", 1, 10, self.user)

        self.assertTrue(response["success"])
        self.assertEqual(
            [item["entity_id"] for item in response["results"]],
            ["SID-1", "ORG-1", "REQ-1"],
        )
        self.assertFalse(response["auto_navigate"])
        requests.assert_called_once_with("medical", self.user, 10)
        users.assert_called_once_with("medical", self.user, 10)
        organizations.assert_called_once_with("medical", self.user, 10)

    @patch("app.services.universal_search_service.search_organizations")
    @patch("app.services.universal_search_service.search_users")
    @patch("app.services.universal_search_service.search_help_requests")
    @patch("app.services.universal_search_service.confident_search", return_value=None)
    def test_page_size_controls_candidate_fetch_and_slice(
        self, confident, requests, users, organizations
    ):
        requests.return_value = [
            {"entity_type": "help_request", "entity_id": f"REQ-{i}", "score": 100-i}
            for i in range(6)
        ]
        users.return_value = []
        organizations.return_value = []

        response = self.service.search("medical", 2, 2, self.user)

        requests.assert_called_once_with("medical", self.user, 4)
        self.assertEqual(
            [item["entity_id"] for item in response["results"]],
            ["REQ-2", "REQ-3"],
        )

    @patch("app.services.universal_search_service.confident_search")
    def test_exact_match_remains_the_only_auto_navigation_path(self, confident):
        exact = {
            "entity_type": "user", "entity_id": "SID-1", "score": 100
        }
        confident.return_value = exact

        response = self.service.search("SID-00-000-000-001", 3, 5, self.user)

        self.assertTrue(response["auto_navigate"])
        self.assertEqual(response["target"], exact)
        self.assertEqual(response["page"], 1)

    def test_query_validation_happens_before_database_work(self):
        for query, message in (
            ("", "Search query is required"),
            ("x", "at least 2 characters"),
            ("x" * 201, "at most 200 characters"),
        ):
            with self.subTest(query_length=len(query)):
                response = self.service.search(query, 1, 10, self.user)
                self.assertFalse(response["success"])
                self.assertIn(message, response["message"])


if __name__ == "__main__":
    unittest.main()
