"""The SQL this service runs must match the live database - issue #169.

`utils/request_db.py` holds the only database access in the whole GenAI
deployment: one statement, four tables. Those tables belong to another team,
and on 2026-08-17 one of them was renamed underneath us -
`virginia_dev_saayam_rdbms.request` became `requests` - as part of the
pluralization tracked in saayam-for-all/database#73 and recorded in
saayam-for-all/CAPA#3. Nothing in this repository noticed, because every test
of the More Information endpoint mocks the lookup at `_lookup_request` and so
never executes the statement at all.

These tests close that gap in the only way a hermetic suite can. They do not
prove the names are right in the live database - nothing here can reach it.
What they do is make the names we depend on **explicit and reviewable in one
place**, so that a future rename is a deliberate, visible edit rather than a
silent runtime failure that surfaces as a 503 in production.

Two of the assertions below are about a rename that has already been announced
but not yet applied: the same wiki page lists `req_user_id -> creator_id` as a
pending change to the request table, and that column is our WHERE clause.
"""
import re

import psycopg2
import pytest

from utils import request_db

pytestmark = pytest.mark.unit


SCHEMA = "test_schema"


def _qualified_names(query):
    """Every schema-qualified table the statement reads."""
    return {
        table
        for _kw, table in re.findall(
            rf"\b(FROM|JOIN)\s+{SCHEMA}\.([A-Za-z0-9_]+)", query
        )
    }


# -------------------------------------------------------------------
# The names we depend on
# -------------------------------------------------------------------

def test_the_help_request_table_is_plural():
    """`request` was renamed to `requests` in the live database on 2026-08-17.

    Reading the singular name raises UndefinedTable on every call, which is
    what made More Information fail with "Request store is unavailable".
    """
    query = request_db.build_query(schema=SCHEMA)

    assert f"FROM {SCHEMA}.requests r" in query
    assert f"FROM {SCHEMA}.request r" not in query


def test_the_joined_tables_keep_their_singular_names():
    """Only the request table was in the rename set.

    req_add_info, req_add_info_metadata and list_item_metadata are absent from
    the ALTER TABLE list on the database wiki, so pluralizing them "for
    consistency" would break this query just as surely as the original rename.
    """
    tables = _qualified_names(request_db.build_query(schema=SCHEMA))

    assert {"req_add_info", "req_add_info_metadata", "list_item_metadata"} <= tables


def test_the_query_reads_no_table_that_is_not_declared_here():
    """The complete list of another team's tables that we depend on.

    If this fails, the statement grew a dependency without anyone recording it,
    and the next schema change will hit a table nobody is watching.
    """
    expected = {"requests", "req_add_info", "req_add_info_metadata", "list_item_metadata"}

    assert _qualified_names(request_db.build_query(schema=SCHEMA)) == expected


def test_the_request_row_is_looked_up_by_req_user_id():
    """`req_user_id` is announced to become `creator_id`, and it is our filter.

    The database wiki lists the rename under the request table's pending
    changes. When it lands, this test fails and points at the WHERE clause,
    rather than the endpoint starting to return "no request found" for every
    caller in production.
    """
    query = request_db.build_query(schema=SCHEMA)

    assert "WHERE r.req_user_id = %s" in query
    assert "r.req_subj" in query and "r.req_desc" in query


def test_the_table_name_can_be_corrected_without_a_release(monkeypatch):
    """The DDL repository lags the live database, so this has to be operable.

    If a rename is rolled back, or a region is migrated on a different day, a
    deployment must be fixable by configuration rather than by a code change
    and a redeploy.
    """
    monkeypatch.setenv("SAAYAM_DB_SCHEMA", "ireland_dev_saayam_rdbms")
    monkeypatch.setenv("SAAYAM_DB_REQUESTS_TABLE", "request")

    query = request_db.build_query()

    assert "FROM ireland_dev_saayam_rdbms.request r" in query


# -------------------------------------------------------------------
# What a mismatch is reported as
# -------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, raises):
        self._raises = raises

    def execute(self, *_args, **_kwargs):
        raise self._raises

    def fetchall(self):  # pragma: no cover - execute always raises first
        return []


class _FakeConnection:
    def __init__(self, raises):
        self._raises = raises
        self.closed = False

    def cursor(self, **_kwargs):
        return _FakeCursor(self._raises)

    def close(self):
        self.closed = True


def _connection_raising(exc, monkeypatch):
    conn = _FakeConnection(exc)
    monkeypatch.setattr(request_db, "get_connection", lambda: conn)
    return conn


def test_a_renamed_table_is_a_schema_mismatch_and_not_an_outage(monkeypatch):
    """The distinction that would have caught this in a day instead of thirteen.

    Reported as "unavailable", a stale statement is indistinguishable from a
    database that is down, and the advice to the caller - retry - is useless.
    """
    _connection_raising(
        psycopg2.errors.UndefinedTable(
            'relation "virginia_dev_saayam_rdbms.request" does not exist'
        ),
        monkeypatch,
    )

    result = request_db.get_request_full_details("SID-1", "REQ-1")

    assert result["error_kind"] == "schema_mismatch"


def test_a_renamed_column_is_also_a_schema_mismatch(monkeypatch):
    """The announced `req_user_id -> creator_id` rename must land in this branch."""
    _connection_raising(
        psycopg2.errors.UndefinedColumn('column r.req_user_id does not exist'),
        monkeypatch,
    )

    result = request_db.get_request_full_details("SID-1", "REQ-1")

    assert result["error_kind"] == "schema_mismatch"


def test_a_database_that_is_down_is_still_a_retryable_outage(monkeypatch):
    """The new branch must not swallow the case it was split out of."""
    _connection_raising(
        psycopg2.OperationalError("could not connect to server: Connection refused"),
        monkeypatch,
    )

    result = request_db.get_request_full_details("SID-1", "REQ-1")

    assert result["error_kind"] == "unavailable"


def test_the_connection_is_released_when_the_statement_fails(monkeypatch):
    """A mismatch fires on every single call, so a leak here exhausts the pool."""
    conn = _connection_raising(
        psycopg2.errors.UndefinedTable("relation does not exist"), monkeypatch
    )

    request_db.get_request_full_details("SID-1", "REQ-1")

    assert conn.closed is True
