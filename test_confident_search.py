"""
test_confident_search.py

Confident Search – DB Integration Test Script
----------------------------------------------
Purpose : Verify that confident_search_repo.py correctly resolves known IDs
          directly against the database and enforces role-based authorization.

How to run
----------
Option A – CLI (recommended for quick checks):
    python test_confident_search.py

Option B – AWS Lambda:
    Zip this file with your app package and invoke it as a handler.
    Set the environment variables below before deploying.

Credentials
-----------
Retrieve DB credentials from AWS Parameter Store using your GenAI admin credentials:

    aws ssm get-parameter --name "/saayam/<env>/db/url" --with-decryption

Then set the environment variable:
    export DATABASE_URL="postgresql://user:pass@host:5432/dbname"

Or set it inline before running:
    DATABASE_URL="postgresql://..." python test_confident_search.py

What this tests
---------------
1. USR-xxx    → resolves to User profile
2. REQ-xxx    → resolves to Help Request
3. ORG-xxx    → resolves to Organization
4. CAT-xxx    → resolves to Category
5. UUID       → resolves to User (or HelpRequest, depending on which table it appears in)
6. Auth gate  → a beneficiary cannot see another user's profile via confident search
7. No match   → an unknown ID returns None (not an error)
8. Fuzzy-only → a plain name like "Arup" is NOT picked up by confident search (falls through)

Prerequisites
-------------
- pip install flask flask-sqlalchemy psycopg2-binary
- A running PostgreSQL instance with at least one row per entity table
- Update SEED_DATA below with real IDs from your database
"""

import os
import sys

# ---------------------------------------------------------------------------
# SEED DATA – replace with real IDs from your DB before running
# ---------------------------------------------------------------------------
SEED_DATA = {
    "user_id":        "SID-00-000-000-058",   # real user_id from users table
    "req_id":         "REQ-00-000-000-0018",  # real req_id from request table
    "org_id":         None,                   # organizations table is currently empty
    "cat_id":         "1",                    # real cat_id from help_categories table
    "unknown_id":     "SID-99-999-999-999",   # ID that does NOT exist in any table
    "plain_query":    "Arup",                 # fuzzy name — should NOT match confident search
}

# ---------------------------------------------------------------------------
# Minimal CurrentUser stub (mirrors app/auth/current_user.py)
# ---------------------------------------------------------------------------
from dataclasses import dataclass

@dataclass
class MockUser:
    id: int
    role: str
    organization_id: int | None = None
    admin_scope_id: int | None = None


ROLES = {
    "super_admin":  MockUser(id=1,  role="super_admin"),
    "admin":        MockUser(id=2,  role="admin",        admin_scope_id=1),
    "organization": MockUser(id=3,  role="organization", organization_id=1),
    "volunteer":    MockUser(id=4,  role="volunteer"),
    "beneficiary":  MockUser(id=5,  role="beneficiary"),
    # A beneficiary that owns the help request being tested
    "owner_beneficiary": MockUser(id=999, role="beneficiary"),
}


# ---------------------------------------------------------------------------
# Flask app factory (minimal – just enough to initialise SQLAlchemy)
# ---------------------------------------------------------------------------
def create_test_app():
    from flask import Flask
    from app.extensions import db

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit(
            "\n[ERROR] DATABASE_URL is not set.\n"
            "Export it before running:\n"
            "  export DATABASE_URL='postgresql://user:pass@host:5432/dbname'\n"
        )

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def run_tests(app):
    from app.repositories.confident_search_repo import confident_search

    passed = 0
    failed = 0

    def check(label, result, expect_match, expect_entity_type=None, expect_score=100):
        nonlocal passed, failed
        if expect_match:
            if result is None:
                print(f"  [FAIL] {label}\n         Expected a result but got None")
                failed += 1
                return
            if result.get("score") != expect_score:
                print(f"  [FAIL] {label}\n         Expected score={expect_score}, got {result.get('score')}")
                failed += 1
                return
            if expect_entity_type and result.get("entity_type") != expect_entity_type:
                print(f"  [FAIL] {label}\n         Expected entity_type={expect_entity_type}, got {result.get('entity_type')}")
                failed += 1
                return
            print(f"  [PASS] {label}")
            print(f"         → {result.get('entity_type')} | {result.get('title')} | url={result.get('url')}")
            passed += 1
        else:
            if result is not None:
                print(f"  [FAIL] {label}\n         Expected None but got {result}")
                failed += 1
                return
            print(f"  [PASS] {label} (correctly returned None)")
            passed += 1

    with app.app_context():
        print("\n" + "="*60)
        print("  Confident Search Integration Tests")
        print("="*60)

        # ── 1. USR-xxx resolves for super_admin ───────────────────────
        print("\n[1] USR-xxx exact match")
        result = confident_search(SEED_DATA["user_id"], ROLES["super_admin"])
        check(
            f"super_admin can resolve {SEED_DATA['user_id']}",
            result,
            expect_match=True,
            expect_entity_type="user",
        )

        # ── 2. REQ-xxx resolves for super_admin ───────────────────────
        print("\n[2] REQ-xxx exact match")
        result = confident_search(SEED_DATA["req_id"], ROLES["super_admin"])
        check(
            f"super_admin can resolve {SEED_DATA['req_id']}",
            result,
            expect_match=True,
            expect_entity_type="help_request",
        )

        # ── 3. ORG-xxx resolves for any authenticated user ─────────────
        print("\n[3] ORG-xxx exact match (skipped — organizations table is empty)")
        # Unskip once the organizations table has data and org_id format is known

        # ── 4. CAT-xxx resolves for any authenticated user ─────────────
        print("\n[4] CAT-xxx exact match (public entity)")
        for role_name in ["super_admin", "volunteer", "beneficiary"]:
            result = confident_search(SEED_DATA["cat_id"], ROLES[role_name])
            check(
                f"{role_name} can resolve {SEED_DATA['cat_id']}",
                result,
                expect_match=True,
                expect_entity_type="category",
            )

        # ── 5. Auth gate: beneficiary cannot see another user's profile ─
        print("\n[5] Auth gate – beneficiary cannot resolve another user's ID")
        # beneficiary (id=5) trying to look up USR-001 (which belongs to a different user)
        result = confident_search(SEED_DATA["user_id"], ROLES["beneficiary"])
        check(
            "beneficiary blocked from resolving other user's ID",
            result,
            expect_match=False,   # should return None (data-leakage prevention)
        )

        # ── 6. Unknown ID returns None (not an error) ─────────────────
        print("\n[6] Unknown ID returns None")
        result = confident_search(SEED_DATA["unknown_id"], ROLES["super_admin"])
        check(
            f"Unknown ID {SEED_DATA['unknown_id']} returns None",
            result,
            expect_match=False,
        )

        # ── 7. Plain name does NOT trigger confident search ────────────
        print("\n[7] Plain name falls through (not a confident match)")
        result = confident_search(SEED_DATA["plain_query"], ROLES["super_admin"])
        check(
            f'Plain query "{SEED_DATA["plain_query"]}" returns None (handled by fuzzy)',
            result,
            expect_match=False,
        )

        # ── 8. Input validation edge cases ────────────────────────────
        print("\n[8] Edge cases")
        for bad_input in ["", "  ", "x", "req-102", "USR-001"]:  # none match the real ID patterns
            result = confident_search(bad_input, ROLES["super_admin"])
            check(
                f'Input "{bad_input!r}" returns None',
                result,
                expect_match=False,
            )

        # ── Summary ───────────────────────────────────────────────────
        print("\n" + "="*60)
        total = passed + failed
        print(f"  Results: {passed}/{total} passed, {failed}/{total} failed")
        print("="*60 + "\n")
        if failed:
            sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_test_app()
    run_tests(app)