import unittest
from unittest.mock import patch

from flask import Flask
from app.routes.search import search_bp


class SearchRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(search_bp, url_prefix="/api")
        self.app.testing = True
        self.client = self.app.test_client()

    def test_post_search_accepts_json_body(self):
        expected_response = {
            "success": True,
            "message": "Search completed",
            "query": "hello",
            "page": 2,
            "limit": 5,
            "total": 0,
            "auto_navigate": False,
            "target": None,
            "results": [],
        }

        with patch("app.routes.search.get_current_user", return_value=None), patch(
            "app.routes.search.UniversalSearchService.search",
            return_value=expected_response,
        ) as mock_search:
            response = self.client.post(
                "/api/search",
                json={"q": "hello", "page": 2, "limit": 5},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_response)
        mock_search.assert_called_once_with(
            query="hello",
            page=2,
            limit=5,
            current_user=None,
        )

    def test_post_search_invalid_json_body_returns_400(self):
        response = self.client.post(
            "/api/search",
            data="not-a-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["message"], "Invalid or missing JSON body")


if __name__ == "__main__":
    unittest.main()
