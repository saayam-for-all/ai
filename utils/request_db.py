"""Fetch request + req_add_info + metadata in one query (Postgres)."""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg2
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.parameters.exceptions import GetParameterError
from psycopg2.extras import RealDictCursor


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
    group = os.getenv("SAAYAM_GROUP", "Database")
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


def _schema() -> str:
    return os.getenv("SAAYAM_DB_SCHEMA", "virginia_dev_saayam_rdbms")


def get_request_full_details(user_id: str, req_id: str) -> dict[str, Any]:
    """
    Returns request row fields plus additional_info grouped by metadata question.
    On failure or no rows, returns {"error": "..."}.
    """
    sch = _schema()
    query = f"""
        SELECT
            r.req_id,
            r.req_user_id,
            r.req_cat_id,
            r.req_subj,
            r.req_desc,
            r.req_loc,
            r.req_type_id,
            r.req_priority_id,
            r.req_status_id,
            r.iscalamity,
            r.submission_date,
            m.field_name_key   AS question,
            m.field_type,
            l.item_value       AS list_answer,
            rai.field_value
        FROM {sch}.request r
        LEFT JOIN {sch}.req_add_info rai
            ON r.req_id = rai.req_id
        LEFT JOIN {sch}.req_add_info_metadata m
            ON rai.field_id = m.field_id
        LEFT JOIN {sch}.list_item_metadata l
            ON rai.item_id = l.item_id
        WHERE r.req_user_id = %s
          AND r.req_id = %s
        ORDER BY rai.field_id;
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, (user_id, req_id))
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

        first = dict(rows[0])
        result: dict[str, Any] = {
            "req_id": first["req_id"],
            "req_user_id": first["req_user_id"],
            "req_cat_id": first["req_cat_id"],
            "req_subj": first["req_subj"],
            "req_desc": first["req_desc"],
            "req_loc": first["req_loc"],
            "req_type_id": first["req_type_id"],
            "req_priority_id": first["req_priority_id"],
            "req_status_id": first["req_status_id"],
            "iscalamity": first["iscalamity"],
            "submission_date": str(first["submission_date"])
            if first.get("submission_date") is not None
            else None,
            "additional_info": [],
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

    except Exception as e:
        # Connection refusals, auth failures and a missing schema all land here.
        # None of them mean the request is absent, so none of them should be
        # reported to the caller as one.
        return {
            "error": f"{type(e).__name__}: {e}",
            "error_kind": "unavailable",
        }

    finally:
        if conn:
            conn.close()
