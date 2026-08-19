import unittest
from math import inf
from unittest.mock import patch

from flask import Flask

from app.auth.current_user import AuthenticationRequired
from app.repositories.db_search import SearchBackendUnavailable
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

        with patch(
            "app.routes.search.get_current_user",
            return_value=None,
        ), patch(
            "app.routes.search.UniversalSearchService.search",
            return_value=expected_response,
        ) as mock_search:
            response = self.client.post(
                "/api/search",
                json={
                    "q": "hello",
                    "page": 2,
                    "limit": 5,
                },
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
        self.assertEqual(
            response.get_json()["message"],
            "Invalid or missing JSON body",
        )

    def test_post_search_rejects_non_string_query(self):
        invalid_queries = [None, 42, True, ["hello"], {"term": "hello"}]

        with patch(
            "app.routes.search.UniversalSearchService.search",
        ) as mock_search:
            for query in invalid_queries:
                with self.subTest(query=query):
                    response = self.client.post(
                        "/api/search",
                        json={"q": query},
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(
                        response.get_json()["message"],
                        "Search query must be a string",
                    )

        mock_search.assert_not_called()

    def test_get_search_accepts_query_parameters(self):
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

        current_user = {
            "user_id": "SID-00-000-000-058",
            "role": "super_admin",
        }

        with patch(
            "app.routes.search.get_current_user",
            return_value=current_user,
        ), patch(
            "app.routes.search.UniversalSearchService.search",
            return_value=expected_response,
        ) as mock_search:
            response = self.client.get(
                "/api/search?q=hello&page=2&limit=5"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_response)

        mock_search.assert_called_once_with(
            query="hello",
            page=2,
            limit=5,
            current_user=current_user,
        )

    def test_get_search_invalid_page_and_limit_use_defaults(self):
        expected_response = {
            "success": True,
            "message": "Search completed",
            "query": "hello",
            "page": 1,
            "limit": 10,
            "total": 0,
            "auto_navigate": False,
            "target": None,
            "results": [],
        }

        with patch(
            "app.routes.search.get_current_user",
            return_value=None,
        ), patch(
            "app.routes.search.UniversalSearchService.search",
            return_value=expected_response,
        ) as mock_search:
            response = self.client.get(
                "/api/search?q=hello&page=invalid&limit=invalid"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_response)

        mock_search.assert_called_once_with(
            query="hello",
            page=1,
            limit=10,
            current_user=None,
        )

    def test_post_search_numeric_strings_are_converted(self):
        expected_response = {
            "success": True,
            "message": "Search completed",
            "query": "hello",
            "page": 3,
            "limit": 7,
            "total": 0,
            "auto_navigate": False,
            "target": None,
            "results": [],
        }

        with patch(
            "app.routes.search.get_current_user",
            return_value=None,
        ), patch(
            "app.routes.search.UniversalSearchService.search",
            return_value=expected_response,
        ) as mock_search:
            response = self.client.post(
                "/api/search",
                json={
                    "q": "hello",
                    "page": "3",
                    "limit": "7",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_response)

        mock_search.assert_called_once_with(
            query="hello",
            page=3,
            limit=7,
            current_user=None,
        )

    def test_post_search_non_finite_pagination_uses_defaults(self):
        expected_response = {
            "success": True,
            "message": "Search completed",
            "query": "hello",
            "page": 1,
            "limit": 10,
            "total": 0,
            "auto_navigate": False,
            "target": None,
            "results": [],
        }

        with patch(
            "app.routes.search.get_current_user",
            return_value=None,
        ), patch(
            "app.routes.search.UniversalSearchService.search",
            return_value=expected_response,
        ) as mock_search:
            response = self.client.post(
                "/api/search",
                json={"q": "hello", "page": inf, "limit": -inf},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_response)

        mock_search.assert_called_once_with(
            query="hello",
            page=1,
            limit=10,
            current_user=None,
        )

    def test_search_requires_authentication(self):
        with patch(
            "app.routes.search.get_current_user",
            side_effect=AuthenticationRequired,
        ):
            response = self.client.get("/api/search?q=hello")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["error_code"],
            "authentication_required",
        )

    def test_search_backend_failure_returns_service_unavailable(self):
        with patch(
            "app.routes.search.get_current_user",
            return_value={"user_id": "SID-1", "role": "admin"},
        ), patch(
            "app.routes.search.UniversalSearchService.search",
            side_effect=SearchBackendUnavailable,
        ):
            response = self.client.get("/api/search?q=hello")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error_code"],
            "search_backend_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
