import os
import unittest
from math import inf
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app
from app.auth.current_user import AuthenticationRequired
from app.repositories.db_search import SearchBackendUnavailable


class SuggestionsRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()

    def test_get_suggestions_returns_results(self):
        expected_response = {
            "success": True,
            "message": "Suggestions fetched",
            "query": "sid-00",
            "limit": 5,
            "total": 1,
            "results": [
                {
                    "entity_type": "user",
                    "entity_id": "SID-00-000-000-058",
                    "title": "Shenghan Cheng",
                    "subtitle": "Email: abcd@b.com",
                    "url": "/users/SID-00-000-000-058",
                    "score": 100,
                    "match_type": "id_prefix",
                }
            ],
        }

        with patch("app.routes.suggestions.get_current_user", return_value=None), patch(
            "app.routes.suggestions.SuggestionService.suggest",
            return_value=expected_response,
        ) as mock_suggest:
            response = self.client.get("/api/suggestions?q=SID-00&limit=5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_response)
        mock_suggest.assert_called_once_with(query="SID-00", limit=5, current_user=None)

    def test_post_suggestions_invalid_json_body_returns_400(self):
        response = self.client.post(
            "/api/suggestions",
            data="not-a-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["message"], "Invalid or missing JSON body")

    def test_post_suggestions_rejects_non_string_query(self):
        response = self.client.post("/api/suggestions", json={"q": ["sid"]})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error_code"], "invalid_query_type")

    def test_non_finite_limit_uses_default(self):
        expected = {
            "success": True,
            "message": "Suggestions fetched",
            "query": "sid",
            "limit": 10,
            "total": 0,
            "results": [],
        }
        with patch(
            "app.routes.suggestions.get_current_user", return_value=None
        ), patch(
            "app.routes.suggestions.SuggestionService.suggest",
            return_value=expected,
        ) as suggest:
            response = self.client.post(
                "/api/suggestions", json={"q": "sid", "limit": inf}
            )

        self.assertEqual(response.status_code, 200)
        suggest.assert_called_once_with(query="sid", limit=10, current_user=None)

    def test_suggestions_requires_authentication(self):
        with patch(
            "app.routes.suggestions.get_current_user",
            side_effect=AuthenticationRequired,
        ):
            response = self.client.get("/api/suggestions?q=sid")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error_code"], "authentication_required")

    def test_suggestion_backend_failure_returns_service_unavailable(self):
        with patch(
            "app.routes.suggestions.get_current_user", return_value=object()
        ), patch(
            "app.routes.suggestions.SuggestionService.suggest",
            side_effect=SearchBackendUnavailable,
        ):
            response = self.client.get("/api/suggestions?q=sid")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error_code"],
            "search_backend_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
