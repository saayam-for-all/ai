import unittest
from unittest.mock import patch

from flask import Flask

from app.auth.current_user import CurrentUser
from app.repositories.help_request_search_repo import search_help_requests
from app.repositories.organization_search_repo import search_organizations
from app.repositories.user_search_repo import search_users


class SearchRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SEARCH_DB_SCHEMA"] = "virginia_dev_saayam_rdbms"
        self.context = self.app.app_context()
        self.context.push()
        self.user = CurrentUser(id="admin-1", role="super_admin")

    def tearDown(self):
        self.context.pop()

    def test_help_request_search_calls_db_contract_and_maps_result(self):
        rows = [{
            "req_id": "REQ-1",
            "cat_name": "Medical Care",
            "req_subj": "Need transportation",
            "req_loc": "San Jose",
            "relevance_score": 0.83,
        }]
        with patch(
            "app.repositories.help_request_search_repo.execute_search",
            return_value=rows,
        ) as execute:
            results = search_help_requests("medical", self.user, 20)

        statement, params = execute.call_args.args
        self.assertIn("search_requests", statement)
        self.assertEqual(params["requester_access_level"], 4)
        self.assertEqual(params["limit_results"], 20)
        self.assertEqual(results[0]["score"], 83.0)
        self.assertEqual(results[0]["match_type"], "fuzzy")

    def test_user_search_maps_email_and_clamps_fuzzy_score(self):
        rows = [{
            "user_id": "SID-1",
            "full_name": "Maya Medical",
            "primary_email_address": "maya@example.test",
            "relevance_score": 1.4,
        }]
        with patch(
            "app.repositories.user_search_repo.execute_search",
            return_value=rows,
        ) as execute:
            results = search_users("maya", self.user, 10)

        self.assertIn("search_users", execute.call_args.args[0])
        self.assertEqual(results[0]["score"], 99)
        self.assertEqual(results[0]["subtitle"], "Email: maya@example.test")

    def test_organization_search_passes_allowed_org_scope(self):
        user = CurrentUser(
            id="org-admin-1",
            role="organization_admin",
            organization_id="ORG-7",
        )
        rows = [{
            "org_id": "ORG-7",
            "org_name": "Medical Transport Network",
            "city_name": "San Jose",
            "state_code": "CA",
            "relevance_score": 0.7,
        }]
        with patch(
            "app.repositories.organization_search_repo.execute_search",
            return_value=rows,
        ) as execute:
            results = search_organizations("medical", user, 10)

        params = execute.call_args.args[1]
        self.assertEqual(params["requester_access_level"], 3)
        self.assertEqual(params["allowed_org_ids"], ["ORG-7"])
        self.assertEqual(results[0]["subtitle"], "San Jose, CA")

    def test_invalid_schema_is_rejected_before_execution(self):
        self.app.config["SEARCH_DB_SCHEMA"] = "unsafe;drop"
        with self.assertRaisesRegex(RuntimeError, "SEARCH_DB_SCHEMA is invalid"):
            search_users("maya", self.user, 10)


if __name__ == "__main__":
    unittest.main()
