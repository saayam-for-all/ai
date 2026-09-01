"""Fetch request + req_add_info + metadata in one query (Postgres).

This module holds the only database access in the whole GenAI deployment, and
every table it reads belongs to another team. Twice in three weeks that team has
changed a name underneath us and told us through a wiki page nobody routes:

* 2026-08-17 - `virginia_dev_saayam_rdbms.request` was renamed to `requests`
  (pluralization, database#73, CAPA#3). Every lookup raised `UndefinedTable`
  for thirteen days.
* database#224 - `req_user_id` was renamed to `creator_id`, and
  `beneficiary_id` and `lead_volunteer_id` were added beside it. Every lookup
  then raised `UndefinedColumn`, which is the failure that took the More
  Information button down a second time.

Hard-coding names is what made both outages ours. This module therefore asks
the database what it actually has, once per container, and builds the statement
from the answer. A rename we have not heard about costs a projected column, not
an outage.

The precedence is deliberate and is the same in every direction:

    explicit argument  ->  environment variable  ->  live introspection  ->  built-in default

Configuration still wins over introspection so that an operator can pin a name
during an incident without waiting for a release, and the built-in default is
the last resort so that a database we cannot introspect still gets a sensible
statement rather than no statement at all.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

import psycopg2
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.parameters.exceptions import GetParameterError
from psycopg2.extras import RealDictCursor


# -------------------------------------------------------------------
# The names we depend on
# -------------------------------------------------------------------

#: Candidate names for the help request table, in the order we prefer them.
#: `requests` is the live name since 2026-08-17; `request` is kept because the
#: DDL in saayam-for-all/database still creates the singular name and the
#: Ireland region has historically been migrated on a different day.
REQUEST_TABLE_CANDIDATES = ("requests", "request")

#: Columns that identify who a request belongs to, in the order we prefer them.
#: `creator_id` is the post-database#224 name for what used to be
#: `req_user_id`; `beneficiary_id` was added by the same change and is a
#: different person - the request is *for* them. The web client resolves its
#: `user_id` from whichever of those two its page happens to hold, so a lookup
#: that matches only one of them 404s for half the traffic.
OWNER_COLUMN_CANDIDATES = ("creator_id", "beneficiary_id", "req_user_id")

#: Request columns the answer is built from. Everything here is optional except
#: REQUIRED_REQUEST_COLUMNS: a column that has been renamed is projected as
#: NULL rather than failing the statement.
OPTIONAL_REQUEST_COLUMNS = (
    "req_cat_id",
    "req_loc",
    "req_type_id",
    "req_priority_id",
    "req_status_id",
    "iscalamity",
    "submission_date",
)

#: Without these there is no answer to generate, so their absence is a genuine
#: schema mismatch rather than something to degrade around.
REQUIRED_REQUEST_COLUMNS = ("req_id", "req_subj", "req_desc")

#: The additional-information join. These three were not in the rename set and
#: keep singular names. They are enrichment: if they disappear, the answer is
#: still worth generating from the request row alone.
ADDITIONAL_INFO_TABLES = ("req_add_info", "req_add_info_metadata", "list_item_metadata")


@dataclass(frozen=True)
class RequestSchema:
    """The shape of the request store as this container found it."""

    table: str
    owner_columns: tuple[str, ...]
    request_columns: frozenset[str]
    with_additional_info: bool
    discovered: bool

    @property
    def selected_optional_columns(self) -> tuple[str, ...]:
        return tuple(c for c in OPTIONAL_REQUEST_COLUMNS if c in self.request_columns)

    @property
    def missing_required_columns(self) -> tuple[str, ...]:
        return tuple(c for c in REQUIRED_REQUEST_COLUMNS if c not in self.request_columns)


class SchemaMismatch(RuntimeError):
    """The live store cannot answer this query no matter how it is phrased."""


#: A bare SQL identifier. Table and column names cannot be passed as bound
#: parameters, so they are interpolated into the statement - which means every
#: one of them has to be proved to be an identifier first. The names reaching
#: that interpolation come from `information_schema` and from environment
#: variables an operator sets during an incident; neither is attacker
#: controlled today, and neither should be the only reason this is safe.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(name: str, kind: str) -> str:
    """Return `name` if it is a bare SQL identifier, else raise."""
    text = str(name)
    if not _IDENTIFIER.match(text) or len(text) > 63:
        raise ValueError(f"invalid {kind} for a SQL statement: {name!r}")
    return text


# -------------------------------------------------------------------
# Connection
# -------------------------------------------------------------------

def _aws_region() -> str:
    explicit = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if explicit:
        return explicit

    # Fallback mapping from logical SAAYAM region to AWS region.
    return {
        "Virginia": "us-east-1",
        "Ireland": "eu-west-1",
    }.get(os.getenv("SAAYAM_REGION", "Virginia"), "us-east-1")


def _db_parameter_path() -> str:
    region = os.getenv("SAAYAM_REGION", "Virginia")
    role = os.getenv("SAAYAM_ROLE", "user")
    return f"/dev/saayam/db/{region}/GenAI/{role}"


def _load_db_config() -> dict[str, Any]:
    region = _aws_region()
    os.environ.setdefault("AWS_REGION", region)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)

    param_path = _db_parameter_path()
    try:
        raw_value = parameters.get_parameter(
            param_path,
            max_age=300,
            decrypt=True,
        )
    except GetParameterError as exc:
        message = str(exc)
        if "Unable to locate credentials" in message:
            raise ValueError(
                "AWS credentials not found for SSM access. "
                "Run `aws configure` or set AWS_PROFILE/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY "
                f"and verify with `aws sts get-caller-identity --region {region}`."
            ) from exc
        raise ValueError(
            f"Failed to fetch SSM parameter `{param_path}` in region `{region}`: {message}"
        ) from exc
    if not raw_value:
        raise ValueError("Empty SSM parameter value for DB config")

    if isinstance(raw_value, str):
        payload = json.loads(raw_value)
    else:
        payload = raw_value

    return {
        "host": payload.get("HOST"),
        "port": payload.get("PORT"),
        "dbname": payload.get("DATABASE NAME"),
        "user": payload.get("USERNAME"),
        "password": payload.get("PASSWORD"),
        "sslmode": payload.get("SSL"),
    }


def get_connection():
    db = _load_db_config()
    return psycopg2.connect(
        host=db["host"] or os.getenv("DB_HOST"),
        port=db["port"] or os.getenv("DB_PORT"),
        dbname=db["dbname"] or os.getenv("DB_NAME"),
        user=db["user"] or os.getenv("DB_USER"),
        password=db["password"] or os.getenv("DB_PASSWORD"),
        sslmode=db["sslmode"] or os.getenv("DB_SSLMODE"),
    )


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

def _schema() -> str:
    return os.getenv("SAAYAM_DB_SCHEMA", "virginia_dev_saayam_rdbms")


def _configured_table() -> str | None:
    """`SAAYAM_DB_REQUESTS_TABLE`, or None to let introspection decide."""
    value = (os.getenv("SAAYAM_DB_REQUESTS_TABLE") or "").strip()
    return value or None


def _configured_owner_columns() -> tuple[str, ...]:
    """`SAAYAM_DB_REQUEST_OWNER_COLUMNS`, comma separated, or () for default."""
    raw = os.getenv("SAAYAM_DB_REQUEST_OWNER_COLUMNS") or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _introspection_enabled() -> bool:
    """Introspection is on unless an operator turns it off.

    The escape hatch exists because the GenAI role's grants are managed by
    another team: if `information_schema` access is ever revoked, one
    environment variable restores the previous behaviour without a release.
    """
    return (os.getenv("SAAYAM_DB_SCHEMA_INTROSPECTION") or "").strip().lower() not in {
        "0",
        "off",
        "false",
        "no",
    }


def default_schema() -> RequestSchema:
    """What we assume when nobody has told us otherwise and we cannot look.

    These are the names as of database#224, which is what the live Virginia
    database has today.
    """
    owner = _configured_owner_columns() or ("creator_id", "beneficiary_id")
    return RequestSchema(
        table=_configured_table() or REQUEST_TABLE_CANDIDATES[0],
        owner_columns=owner,
        request_columns=frozenset(REQUIRED_REQUEST_COLUMNS)
        | frozenset(OPTIONAL_REQUEST_COLUMNS)
        | frozenset(owner),
        with_additional_info=True,
        discovered=False,
    )


# -------------------------------------------------------------------
# Introspection
# -------------------------------------------------------------------

# One statement, two answers: which of the candidate request tables exist and
# what columns they carry. Restricting on table_name keeps this cheap on a
# schema with 48 tables.
_REQUEST_COLUMNS_SQL = """
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema = %s
      AND table_name = ANY(%s)
"""

_TABLES_PRESENT_SQL = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = %s
      AND table_name = ANY(%s)
"""

# Resolved once per Lambda container, keyed by schema so that a function
# configured for two regions cannot serve one region's layout to the other.
_schema_cache: dict[str, RequestSchema] = {}


def reset_schema_cache() -> None:
    """Drop the per-container cache. Used by the suite and by operators."""
    _schema_cache.clear()


def _rows_to_table_columns(rows: Iterable[Any]) -> dict[str, set[str]]:
    """Group `(table_name, column_name)` rows, tolerating either row style.

    `RealDictCursor` yields mappings; a plain cursor yields tuples. Reading the
    result both ways keeps introspection independent of how the caller
    configured its cursor.
    """
    found: dict[str, set[str]] = {}
    for row in rows:
        if isinstance(row, dict):
            table = row.get("table_name")
            column = row.get("column_name")
        else:
            table, column = row[0], row[1]
        if table is None or column is None:
            continue
        found.setdefault(str(table), set()).add(str(column))
    return found


def discover_schema(cur, schema: str) -> RequestSchema:
    """Ask the database what the request store actually looks like.

    Raises SchemaMismatch when the store cannot answer this query at all -
    there is no request table, or it has no column that says who a request
    belongs to. Both are unrecoverable here and must not be papered over: see
    the note on authorization in `_where_clause`.
    """
    # A pinned table is looked up like any other candidate and preferred over
    # them. Reading the pinned name but another table's columns would put the
    # override right back into the class of bug it exists to work around.
    pinned = _configured_table()
    candidates = (pinned, *REQUEST_TABLE_CANDIDATES) if pinned else REQUEST_TABLE_CANDIDATES

    cur.execute(_REQUEST_COLUMNS_SQL, (schema, list(candidates)))
    by_table = _rows_to_table_columns(cur.fetchall())

    table = next((t for t in candidates if t in by_table), None)
    if table is None:
        raise SchemaMismatch(
            f"no request table in schema {schema}: looked for "
            f"{', '.join(candidates)}"
        )

    columns = by_table[table]

    configured_owners = _configured_owner_columns()
    if configured_owners:
        # An operator pinned these. Honour them, but only the ones that exist,
        # so a stale pin degrades to the discovered set instead of breaking.
        owners = tuple(c for c in configured_owners if c in columns)
    else:
        owners = tuple(c for c in OWNER_COLUMN_CANDIDATES if c in columns)

    if not owners:
        raise SchemaMismatch(
            f"{schema}.{table} has no recognised owner column: looked for "
            f"{', '.join(OWNER_COLUMN_CANDIDATES)}"
        )

    cur.execute(_TABLES_PRESENT_SQL, (schema, list(ADDITIONAL_INFO_TABLES)))
    present = {
        (row.get("table_name") if isinstance(row, dict) else row[0])
        for row in cur.fetchall()
    }
    with_additional_info = set(ADDITIONAL_INFO_TABLES) <= present

    return RequestSchema(
        table=table,
        owner_columns=owners,
        request_columns=frozenset(columns),
        with_additional_info=with_additional_info,
        discovered=True,
    )


def resolve_schema(cur, schema: str) -> RequestSchema:
    """Cached `discover_schema`, falling back to the configured default.

    Introspection is a convenience, never a dependency: if the query fails for
    any reason other than a genuine mismatch - a permission we do not have, a
    driver quirk, a `information_schema` that is not there - we carry on with
    the built-in names, which is exactly the behaviour this module had before.
    """
    cached = _schema_cache.get(schema)
    if cached is not None:
        return cached

    if not _introspection_enabled():
        resolved = default_schema()
    else:
        try:
            resolved = discover_schema(cur, schema)
        except SchemaMismatch:
            # Genuine and unrecoverable. Do not cache it: the database team
            # applies DDL by hand, and the next container should look again.
            raise
        except Exception as exc:  # pragma: no cover - defensive, exercised in tests
            print(
                "WARN: request schema introspection failed, falling back to "
                f"configured names: {type(exc).__name__}: {exc}"
            )
            resolved = default_schema()

    _schema_cache[schema] = resolved
    return resolved


# -------------------------------------------------------------------
# Statement
# -------------------------------------------------------------------

def _where_clause(owner_columns: tuple[str, ...]) -> str:
    """`req_id` plus an owner match across every owner column that exists.

    The owner predicate is not optional. It is the only thing standing between
    a caller and somebody else's help request, which carries health, housing
    and financial detail. If a schema is ever found with no owner column at
    all, `discover_schema` raises rather than dropping this clause.
    """
    if not owner_columns:
        raise ValueError(
            "refusing to build a request lookup with no owner column: the "
            "statement would return any request to any caller"
        )
    owners = " OR ".join(
        f"r.{_identifier(column, 'owner column')} = %s" for column in owner_columns
    )
    return f"WHERE r.req_id = %s\n          AND ({owners})"


def build_query(
    schema: str | None = None,
    requests_table: str | None = None,
    owner_columns: tuple[str, ...] | None = None,
    request_columns: Iterable[str] | None = None,
    with_additional_info: bool = True,
) -> str:
    """Build the statement this module runs.

    Split out from the call that executes it so the suite can assert which
    tables and columns we depend on without opening a connection. Those names
    are owned by another team and have changed underneath us twice.
    """
    sch = _identifier(schema if schema is not None else _schema(), "schema")
    base = default_schema()

    table = requests_table if requests_table is not None else base.table
    owners = owner_columns if owner_columns is not None else base.owner_columns
    available = (
        frozenset(request_columns) if request_columns is not None else base.request_columns
    )

    projected = list(REQUIRED_REQUEST_COLUMNS)
    projected += [c for c in OPTIONAL_REQUEST_COLUMNS if c in available]
    projected += [c for c in owners if c not in projected]

    table = _identifier(table, "table name")
    select_lines = ",\n            ".join(
        f"r.{_identifier(column, 'column name')}" for column in projected
    )

    if with_additional_info:
        select_lines += (
            ",\n            m.field_name_key   AS question"
            ",\n            m.field_type"
            ",\n            l.item_value       AS list_answer"
            ",\n            rai.field_value"
        )
        joins = f"""
        LEFT JOIN {sch}.req_add_info rai
            ON r.req_id = rai.req_id
        LEFT JOIN {sch}.req_add_info_metadata m
            ON rai.field_id = m.field_id
        LEFT JOIN {sch}.list_item_metadata l
            ON rai.item_id = l.item_id"""
        order_by = "\n        ORDER BY rai.field_id;"
    else:
        joins = ""
        order_by = ";"

    return f"""
        SELECT
            {select_lines}
        FROM {sch}.{table} r{joins}
        {_where_clause(tuple(owners))}{order_by}
    """


def build_params(user_id: str, req_id: str, owner_columns: tuple[str, ...]) -> tuple:
    """Positional parameters for `build_query`, in the order it names them."""
    return (req_id, *([user_id] * len(owner_columns)))


# -------------------------------------------------------------------
# Read
# -------------------------------------------------------------------

def _shape_result(rows: list[dict[str, Any]], schema: RequestSchema) -> dict[str, Any]:
    """Turn the joined rows into the request object the handler consumes.

    Every field is read with `.get`, because the projection is now built from
    what the database has rather than from what this file assumes. A column
    that was renamed arrives as absent, and absent has to mean None rather than
    KeyError.
    """
    first = dict(rows[0])

    def value(column: str) -> Any:
        return first.get(column)

    owner = next(
        (first.get(column) for column in schema.owner_columns if first.get(column)),
        None,
    )

    submission = value("submission_date")
    result: dict[str, Any] = {
        "req_id": value("req_id"),
        "creator_id": first.get("creator_id"),
        "beneficiary_id": first.get("beneficiary_id"),
        # Retained so that anything still reading the pre-database#224 name
        # keeps working. It carries whichever owner column actually matched.
        "req_user_id": owner,
        "req_cat_id": value("req_cat_id"),
        "req_subj": value("req_subj"),
        "req_desc": value("req_desc"),
        "req_loc": value("req_loc"),
        "req_type_id": value("req_type_id"),
        "req_priority_id": value("req_priority_id"),
        "req_status_id": value("req_status_id"),
        "iscalamity": value("iscalamity"),
        "submission_date": str(submission) if submission is not None else None,
        "additional_info": [],
        "schema_discovered": schema.discovered,
    }

    questions: dict[str, dict[str, Any]] = {}
    for row in rows:
        r = dict(row)
        field = r.get("question")
        if field is None:
            continue
        f_type = r.get("field_type")
        l_ans = r.get("list_answer")
        ft_ans = r.get("field_value")

        if field not in questions:
            questions[field] = {
                "question": field,
                "field_type": f_type,
                "answers": [],
            }

        if l_ans:
            questions[field]["answers"].append(l_ans)
        elif ft_ans:
            questions[field]["answers"].append(ft_ans)

    result["additional_info"] = list(questions.values())
    return result


def get_request_full_details(user_id: str, req_id: str) -> dict[str, Any]:
    """Read one request row plus its additional info.

    On failure returns `{"error": ..., "error_kind": ...}` where `error_kind`
    is one of:

    * `not_found`      - the store answered, and this request is not in it.
    * `schema_mismatch`- our statement no longer matches the store. Retrying
                         cannot fix it, and calling it an outage is exactly how
                         the 2026-08-17 rename went unnoticed for thirteen days.
    * `unavailable`    - the store did not answer. Retrying might fix it.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        schema_name = _schema()
        schema = resolve_schema(cur, schema_name)

        missing = schema.missing_required_columns
        if missing:
            raise SchemaMismatch(
                f"{schema_name}.{schema.table} is missing required column(s): "
                f"{', '.join(missing)}"
            )

        query = build_query(
            schema=schema_name,
            requests_table=schema.table,
            owner_columns=schema.owner_columns,
            request_columns=schema.request_columns,
            with_additional_info=schema.with_additional_info,
        )
        cur.execute(query, build_params(user_id, req_id, schema.owner_columns))
        rows = cur.fetchall()

        if not rows:
            # error_kind lets the caller tell "this request does not exist"
            # (a 404 the client can act on) from "the store is down" (a 503 the
            # client should retry). Matching on the message text, which is what
            # the handler used to do, made a rebuilt but empty database look
            # exactly like a bad req_id.
            return {
                "error": "No data found for given user_id and req_id",
                "error_kind": "not_found",
            }

        return _shape_result(rows, schema)

    except SchemaMismatch as e:
        # Raised by introspection, not by the driver: the store is up and
        # answering, and it does not have what this query needs.
        return {"error": f"SchemaMismatch: {e}", "error_kind": "schema_mismatch"}

    except psycopg2.ProgrammingError as e:
        # UndefinedTable, UndefinedColumn and a plain syntax error all say the
        # same thing: this statement no longer matches the database it is being
        # run against. Introspection should now prevent both renames from
        # reaching here, so anything that does is a shape we have not seen and
        # is worth the same loud, non-retryable signal.
        return {
            "error": f"{type(e).__name__}: {e}",
            "error_kind": "schema_mismatch",
        }

    except Exception as e:
        # Connection refusals and auth failures land here. Neither means the
        # request is absent, so neither should be reported to the caller as one.
        return {
            "error": f"{type(e).__name__}: {e}",
            "error_kind": "unavailable",
        }

    finally:
        if conn:
            conn.close()
