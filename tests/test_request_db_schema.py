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

That guard worked. The assertion written here on 2026-08-30 for the rename the
wiki listed as *pending* - `req_user_id -> creator_id`, which is our WHERE
clause - failed on the first run after database#224 was applied, and named the
WHERE clause instead of letting the endpoint return "no request found" to every
caller in production. It has been rewritten to assert the current columns.

Naming the columns was never going to be enough on its own, though: it turns a
silent outage into a red test, which still costs a release. The second half of
this file covers what replaced the assumption - the statement is now built from
what `information_schema` says the store actually has, and every way that
discovery is allowed to degrade is pinned here, because a guardrail that fails
open without saying so is worse than no guardrail at all.
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


def test_the_request_row_is_looked_up_by_its_current_owner_columns():
    """`req_user_id` became `creator_id`, and this is the test that caught it.

    Written on 2026-08-30 asserting `WHERE r.req_user_id = %s`, with a note
    saying the database wiki listed the rename as pending and that this test
    would fail and point at the WHERE clause when it landed. It did exactly
    that: database#224 renamed the column and added `beneficiary_id` beside it,
    and this assertion failed on the next run.

    Both owner columns are matched because they are different people. The web
    client resolves its `user_id` from whichever the page happens to hold - the
    creator on My Requests, the beneficiary on All Requests - so filtering on
    one of them alone returns "no request found" for half of real traffic.
    """
    query = request_db.build_query(schema=SCHEMA)

    assert "WHERE r.req_id = %s" in query
    assert "(r.creator_id = %s OR r.beneficiary_id = %s)" in query
    assert "r.req_user_id" not in query
    assert "r.req_subj" in query and "r.req_desc" in query


def test_the_owner_predicate_is_never_dropped():
    """The only thing between a caller and somebody else's help request.

    A request row carries health, housing and financial detail. Whatever else
    degrades when the schema moves, the statement must never widen to `WHERE
    req_id = %s` alone, which would hand any request to anyone who knows its
    id.
    """
    for owners in [("creator_id",), ("creator_id", "beneficiary_id"),
                   ("creator_id", "beneficiary_id", "req_user_id")]:
        query = request_db.build_query(schema=SCHEMA, owner_columns=owners)
        for column in owners:
            assert f"r.{column} = %s" in query

    with pytest.raises(ValueError, match="no owner column"):
        # An empty owner set is not a query we are willing to build; the
        # discovery path raises SchemaMismatch long before this.
        request_db.build_query(schema=SCHEMA, owner_columns=())


def test_parameters_are_ordered_the_way_the_statement_names_them():
    """req_id first, then the user id once per owner column.

    Getting this pair out of step silently swaps the two filters and returns
    nothing for every caller, which reads exactly like an empty database.
    """
    owners = ("creator_id", "beneficiary_id")
    query = request_db.build_query(schema=SCHEMA, owner_columns=owners)

    assert query.index("r.req_id = %s") < query.index("r.creator_id = %s")
    assert request_db.build_params("SID-1", "REQ-1", owners) == ("REQ-1", "SID-1", "SID-1")


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



# -------------------------------------------------------------------
# Schema introspection - the guardrail against the next rename
# -------------------------------------------------------------------
#
# Two renames in three weeks, both announced only on a wiki page that nothing
# routes to the teams it names, both reaching us as a production failure. The
# statement is now built from what the database reports it actually has.
#
# These tests pin that behaviour and, just as importantly, every way it is
# allowed to degrade. A guardrail that fails open without saying so is worse
# than no guardrail at all.

#: The live Virginia layout after database#224.
CURRENT_COLUMNS = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id",
    "req_cat_id", "req_subj", "req_desc", "req_loc", "req_type_id",
    "req_priority_id", "req_status_id", "iscalamity", "submission_date",
]

#: The pre-database#224 layout, which the DDL repository and the Ireland
#: region scripts still describe today.
LEGACY_COLUMNS = [
    "req_id", "req_user_id", "req_cat_id", "req_subj", "req_desc", "req_loc",
    "req_type_id", "req_priority_id", "req_status_id", "iscalamity",
    "submission_date",
]

ROW = {
    "req_id": "REQ-1",
    "creator_id": "SID-1",
    "beneficiary_id": "SID-2",
    "req_subj": "Need winter coats",
    "req_desc": "Two children, no warm clothing.",
    "req_loc": "Chicago",
    "req_cat_id": "1",
    "submission_date": "2026-08-01 10:00:00",
}


class _IntrospectingCursor:
    """Answers the two introspection statements, then the real one."""

    def __init__(self, tables, join_tables=request_db.ADDITIONAL_INFO_TABLES,
                 rows=(), raises=None):
        #: {table_name: [column, ...]} for the request table candidates.
        self.tables = tables
        self.join_tables = tuple(join_tables)
        self.rows = list(rows)
        self.raises = raises
        self.query = None
        self.params = None
        self._pending = []

    def execute(self, query, params=None):
        if "information_schema.columns" in query:
            self._pending = [
                {"table_name": table, "column_name": column}
                for table, columns in self.tables.items()
                for column in columns
            ]
            return
        if "information_schema.tables" in query:
            self._pending = [{"table_name": t} for t in self.join_tables]
            return
        self.query, self.params = query, params
        if self.raises:
            raise self.raises
        self._pending = self.rows

    def fetchall(self):
        return self._pending


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, **_kwargs):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_schema_cache():
    """The resolved schema is cached per container, so per test as well."""
    request_db.reset_schema_cache()
    yield
    request_db.reset_schema_cache()


def _run(cursor, monkeypatch, user_id="SID-1", req_id="REQ-1"):
    conn = _Connection(cursor)
    monkeypatch.setattr(request_db, "get_connection", lambda: conn)
    result = request_db.get_request_full_details(user_id, req_id)
    return result, conn


# --- it reads what is actually there --------------------------------

def test_the_live_layout_is_discovered_and_used(monkeypatch):
    """The post-database#224 database: plural table, creator_id, beneficiary_id."""
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])

    result, _ = _run(cur, monkeypatch)

    assert "FROM virginia_dev_saayam_rdbms.requests r" in cur.query
    assert "(r.creator_id = %s OR r.beneficiary_id = %s)" in cur.query
    assert cur.params == ("REQ-1", "SID-1", "SID-1")
    assert result["req_subj"] == "Need winter coats"
    assert result["schema_discovered"] is True


def test_a_rolled_back_database_still_works(monkeypatch):
    """The exact failure of 2026-08-17 and database#224, in reverse.

    Ireland has historically been migrated on a different day, and the DDL in
    saayam-for-all/database still creates the singular table with the old
    column. Against that database the same code must produce the old
    statement rather than the outage we shipped twice.
    """
    cur = _IntrospectingCursor({"request": LEGACY_COLUMNS},
                               rows=[{**ROW, "req_user_id": "SID-1"}])

    result, _ = _run(cur, monkeypatch)

    assert "FROM virginia_dev_saayam_rdbms.request r" in cur.query
    assert "(r.req_user_id = %s)" in cur.query
    assert "creator_id" not in cur.query
    assert result["req_user_id"] == "SID-1"


def test_the_plural_table_wins_when_a_migration_leaves_both(monkeypatch):
    """A rename done by hand can leave a backup of the old table behind."""
    cur = _IntrospectingCursor(
        {"request": LEGACY_COLUMNS, "requests": CURRENT_COLUMNS}, rows=[ROW]
    )

    _run(cur, monkeypatch)

    assert "FROM virginia_dev_saayam_rdbms.requests r" in cur.query


def test_a_column_we_do_not_need_disappearing_costs_only_that_column(monkeypatch):
    """`iscalamity` or `req_loc` going away must not fail the whole statement.

    Phase 2 of the restructuring renames columns across 48 tables. Projecting
    a column that is gone raises UndefinedColumn and takes the endpoint down;
    projecting only what exists degrades one field.
    """
    without_location = [c for c in CURRENT_COLUMNS if c not in ("req_loc", "iscalamity")]
    cur = _IntrospectingCursor({"requests": without_location},
                               rows=[{k: v for k, v in ROW.items() if k != "req_loc"}])

    result, _ = _run(cur, monkeypatch)

    assert "r.req_loc" not in cur.query
    assert "r.iscalamity" not in cur.query
    assert result["req_loc"] is None
    assert result["iscalamity"] is None
    # The fields the answer is actually built from are still there.
    assert result["req_subj"] and result["req_desc"]


def test_losing_the_additional_info_tables_drops_the_join_not_the_answer(monkeypatch):
    """Enrichment is enrichment. The request row alone still answers."""
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS},
                               join_tables=("req_add_info",), rows=[ROW])

    result, _ = _run(cur, monkeypatch)

    assert "req_add_info_metadata" not in cur.query
    assert "LEFT JOIN" not in cur.query
    assert "ORDER BY" not in cur.query
    assert result["additional_info"] == []
    assert result["req_desc"] == ROW["req_desc"]


# --- it refuses where refusing is correct ---------------------------

def test_no_request_table_at_all_is_a_schema_mismatch(monkeypatch):
    """Neither name present: this is our statement being wrong, not an outage."""
    cur = _IntrospectingCursor({})

    result, _ = _run(cur, monkeypatch)

    assert result["error_kind"] == "schema_mismatch"
    assert "no request table" in result["error"]


def test_a_table_with_no_owner_column_is_refused_rather_than_widened(monkeypatch):
    """Never trade authorization for availability.

    If every owner column were renamed at once, dropping the predicate would
    keep the endpoint "working" while handing any request to anyone holding
    its id. It fails closed instead.
    """
    ownerless = [c for c in CURRENT_COLUMNS
                 if c not in ("creator_id", "beneficiary_id")]
    cur = _IntrospectingCursor({"requests": ownerless})

    result, _ = _run(cur, monkeypatch)

    assert result["error_kind"] == "schema_mismatch"
    assert "owner column" in result["error"]


def test_losing_the_text_the_answer_is_built_from_is_a_schema_mismatch(monkeypatch):
    """Without req_subj/req_desc there is nothing to answer, so say so."""
    cur = _IntrospectingCursor(
        {"requests": [c for c in CURRENT_COLUMNS if c != "req_desc"]}
    )

    result, _ = _run(cur, monkeypatch)

    assert result["error_kind"] == "schema_mismatch"
    assert "req_desc" in result["error"]


def test_a_mismatch_is_not_cached_so_the_next_container_looks_again(monkeypatch):
    """The database team applies DDL by hand; a mismatch is often minutes old."""
    cur = _IntrospectingCursor({})
    _run(cur, monkeypatch)

    healthy = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])
    result, _ = _run(healthy, monkeypatch)

    assert "error" not in result


# --- it degrades rather than failing --------------------------------

def test_introspection_that_is_not_permitted_falls_back_to_the_known_names(
    capsys, monkeypatch
):
    """Our database grants are managed by another team.

    Losing `information_schema` access must cost us the guardrail, not the
    endpoint: the statement falls back to the names this file ships with,
    which is exactly the behaviour before introspection existed.
    """
    class _Denied(_IntrospectingCursor):
        def execute(self, query, params=None):
            if "information_schema" in query:
                raise psycopg2.errors.InsufficientPrivilege("permission denied")
            return super().execute(query, params)

    cur = _Denied({"requests": CURRENT_COLUMNS}, rows=[ROW])
    result, _ = _run(cur, monkeypatch)

    assert "error" not in result
    assert "(r.creator_id = %s OR r.beneficiary_id = %s)" in cur.query
    assert result["schema_discovered"] is False
    # Silent degradation is how we got here in the first place.
    assert "introspection failed" in capsys.readouterr().out


def test_introspection_can_be_switched_off_without_a_release(monkeypatch):
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])
    monkeypatch.setenv("SAAYAM_DB_SCHEMA_INTROSPECTION", "off")

    result, _ = _run(cur, monkeypatch)

    assert result["schema_discovered"] is False
    assert "FROM virginia_dev_saayam_rdbms.requests r" in cur.query


def test_the_resolved_schema_is_cached_for_the_life_of_the_container(monkeypatch):
    """One introspection per cold start, not one per invocation."""
    calls = []

    class _Counting(_IntrospectingCursor):
        def execute(self, query, params=None):
            if "information_schema.columns" in query:
                calls.append(query)
            return super().execute(query, params)

    cur = _Counting({"requests": CURRENT_COLUMNS}, rows=[ROW])
    conn = _Connection(cur)
    monkeypatch.setattr(request_db, "get_connection", lambda: conn)

    request_db.get_request_full_details("SID-1", "REQ-1")
    request_db.get_request_full_details("SID-1", "REQ-2")

    assert len(calls) == 1


def test_two_regions_do_not_share_one_resolved_layout(monkeypatch):
    """Virginia is migrated; Ireland may not be. The cache is keyed by schema."""
    virginia = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])
    _run(virginia, monkeypatch)

    monkeypatch.setenv("SAAYAM_DB_SCHEMA", "ireland_dev_saayam_rdbms")
    ireland = _IntrospectingCursor({"request": LEGACY_COLUMNS},
                                   rows=[{**ROW, "req_user_id": "SID-1"}])
    _run(ireland, monkeypatch)

    assert "FROM ireland_dev_saayam_rdbms.request r" in ireland.query
    assert "(r.req_user_id = %s)" in ireland.query


# --- configuration still beats discovery ----------------------------

def test_an_operator_can_pin_the_table_during_an_incident(monkeypatch):
    """The pin wins over both candidates - but it is looked up like them.

    Reading the pinned name while projecting another table's columns would put
    the override straight back into the class of bug it exists to work around,
    so the pinned table is introspected too and its own columns are used.
    """
    monkeypatch.setenv("SAAYAM_DB_REQUESTS_TABLE", "requests_backup")
    backup_columns = [c for c in CURRENT_COLUMNS if c != "iscalamity"]
    cur = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS, "requests_backup": backup_columns}, rows=[ROW]
    )

    _run(cur, monkeypatch)

    assert "FROM virginia_dev_saayam_rdbms.requests_backup r" in cur.query
    assert "r.iscalamity" not in cur.query


def test_a_pin_naming_a_table_that_is_not_there_degrades_to_what_is(monkeypatch):
    """A pin set during an incident and forgotten must not become the next one.

    The same rule as a stale owner-column pin: configuration beats discovery
    only where configuration describes something real.
    """
    monkeypatch.setenv("SAAYAM_DB_REQUESTS_TABLE", "requests_backup")
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])

    result, _ = _run(cur, monkeypatch)

    assert "FROM virginia_dev_saayam_rdbms.requests r" in cur.query
    assert "error" not in result


@pytest.mark.parametrize(
    "hostile",
    ["requests; DROP TABLE users", "requests--", 'requests" OR "1"="1',
     "req uests", "", "1requests", "r" * 64],
)
def test_a_name_that_is_not_an_identifier_never_reaches_the_statement(hostile):
    """Table and column names cannot be bound as parameters, so they are checked.

    Nothing attacker-controlled reaches these arguments today: they come from
    `information_schema` and from environment variables an operator sets. That
    is a reason to be relaxed about the risk, not a reason for it to be the
    only thing standing between an environment variable and the statement.
    """
    with pytest.raises(ValueError, match="invalid"):
        request_db.build_query(schema=SCHEMA, requests_table=hostile)

    with pytest.raises(ValueError, match="invalid"):
        request_db.build_query(schema=SCHEMA, owner_columns=(hostile,))

    with pytest.raises(ValueError, match="invalid"):
        request_db.build_query(schema=hostile)


def test_an_operator_can_pin_the_owner_columns(monkeypatch):
    """Useful if the two ids ever stop meaning what we think they mean."""
    monkeypatch.setenv("SAAYAM_DB_REQUEST_OWNER_COLUMNS", "creator_id")
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])

    _run(cur, monkeypatch)

    assert "(r.creator_id = %s)" in cur.query
    assert "beneficiary_id = %s" not in cur.query


def test_a_stale_pin_degrades_to_what_exists_rather_than_breaking(monkeypatch):
    """A pin set during an incident and forgotten must not become the next one."""
    monkeypatch.setenv("SAAYAM_DB_REQUEST_OWNER_COLUMNS", "req_user_id,creator_id")
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])

    _run(cur, monkeypatch)

    assert "(r.creator_id = %s)" in cur.query
    assert "req_user_id" not in cur.query


# --- the connection is always returned ------------------------------

def test_the_connection_is_released_after_a_successful_read(monkeypatch):
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[ROW])
    _, conn = _run(cur, monkeypatch)

    assert conn.closed is True


def test_the_connection_is_released_when_introspection_refuses(monkeypatch):
    """A mismatch fires on every call, so a leak here exhausts the pool."""
    _, conn = _run(_IntrospectingCursor({}), monkeypatch)

    assert conn.closed is True


# --- the additional-info shape the prompt is now built from ---------
#
# This grouping used to be dead weight: the handler fetched it and threw it
# away. It now reaches the model, so its shape is a contract and the rows it
# folds together come from another team's metadata tables.

def _info_rows(*extra):
    """Request row repeated once per additional-info row, as the join returns it."""
    return [{**ROW, **fields} for fields in extra]


def test_repeated_join_rows_are_grouped_into_one_entry_per_question(monkeypatch):
    """The join repeats the request row once per answer; the caller wants one."""
    cur = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS},
        rows=_info_rows(
            {"question": "Sizes needed", "field_type": "list",
             "list_answer": "Age 6", "field_value": None},
            {"question": "Sizes needed", "field_type": "list",
             "list_answer": "Age 9", "field_value": None},
            {"question": "How many children?", "field_type": "text",
             "list_answer": None, "field_value": "2"},
        ),
    )

    result, _ = _run(cur, monkeypatch)

    assert result["additional_info"] == [
        {"question": "Sizes needed", "field_type": "list",
         "answers": ["Age 6", "Age 9"]},
        {"question": "How many children?", "field_type": "text",
         "answers": ["2"]},
    ]


def test_a_request_with_no_additional_info_still_returns_the_row(monkeypatch):
    """LEFT JOIN gives one row with every metadata column NULL."""
    cur = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS},
        rows=_info_rows({"question": None, "field_type": None,
                         "list_answer": None, "field_value": None}),
    )

    result, _ = _run(cur, monkeypatch)

    assert result["additional_info"] == []
    assert result["req_subj"] == ROW["req_subj"]


def test_a_question_that_was_asked_but_not_answered_carries_no_answers(monkeypatch):
    """Both answer columns NULL means the beneficiary skipped the field."""
    cur = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS},
        rows=_info_rows({"question": "Preferred contact time", "field_type": "text",
                         "list_answer": None, "field_value": None}),
    )

    result, _ = _run(cur, monkeypatch)

    assert result["additional_info"] == [
        {"question": "Preferred contact time", "field_type": "text", "answers": []}
    ]


def test_the_list_answer_wins_over_the_free_text_column(monkeypatch):
    """A list-backed field stores its label in list_item_metadata, not field_value."""
    cur = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS},
        rows=_info_rows({"question": "Housing status", "field_type": "list",
                         "list_answer": "Renting", "field_value": "3"}),
    )

    result, _ = _run(cur, monkeypatch)

    assert result["additional_info"][0]["answers"] == ["Renting"]


def test_submission_date_is_stringified_and_a_missing_one_stays_none(monkeypatch):
    """It is a timestamp on the way out of psycopg2 and JSON on the way to a client."""
    import datetime

    dated = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS},
        rows=[{**ROW, "submission_date": datetime.datetime(2026, 8, 1, 10, 0)}],
    )
    result, _ = _run(dated, monkeypatch)
    assert result["submission_date"] == "2026-08-01 10:00:00"

    undated = _IntrospectingCursor(
        {"requests": CURRENT_COLUMNS}, rows=[{**ROW, "submission_date": None}]
    )
    result, _ = _run(undated, monkeypatch)
    assert result["submission_date"] is None


def test_introspection_reads_tuple_rows_as_well_as_dict_rows():
    """The cursor factory is the caller's choice, not this function's business."""
    from utils.request_db import _rows_to_table_columns

    as_tuples = _rows_to_table_columns([("requests", "req_id"), ("requests", "creator_id")])
    as_dicts = _rows_to_table_columns([
        {"table_name": "requests", "column_name": "req_id"},
        {"table_name": "requests", "column_name": "creator_id"},
    ])

    assert as_tuples == as_dicts == {"requests": {"req_id", "creator_id"}}
    assert _rows_to_table_columns([(None, "req_id"), ("requests", None)]) == {}


def test_a_request_that_is_not_there_is_not_found_and_not_an_outage(monkeypatch):
    """Zero rows after a healthy introspection means exactly one thing.

    During the rebuild the tables existed but held nothing, and reporting that
    as an outage is what made an empty database look like a bad req_id.
    """
    cur = _IntrospectingCursor({"requests": CURRENT_COLUMNS}, rows=[])

    result, conn = _run(cur, monkeypatch)

    assert result["error_kind"] == "not_found"
    assert conn.closed is True
