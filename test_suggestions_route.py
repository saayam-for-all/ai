import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app


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


if __name__ == "__main__":
    unittest.main()
