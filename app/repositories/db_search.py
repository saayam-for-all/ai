"""Shared execution helpers for the PostgreSQL search function contract."""

import re

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SearchBackendUnavailable(RuntimeError):
    """Raised when the configured database search layer cannot be used."""


def database_schema() -> str:
    schema = current_app.config.get(
        "SEARCH_DB_SCHEMA", "virginia_dev_saayam_rdbms"
    )
    if not isinstance(schema, str) or not _SCHEMA_RE.fullmatch(schema):
        raise SearchBackendUnavailable("SEARCH_DB_SCHEMA is invalid")
    return schema


def execute_search(statement, parameters):
    try:
        return db.session.execute(text(statement), parameters).mappings().all()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise SearchBackendUnavailable(
            "Database search functions are unavailable"
        ) from exc


def fuzzy_score(value) -> float:
    """Normalize DB relevance to the API's 0–100 scale below exact matches."""
    try:
        score = float(value or 0) * 100
    except (TypeError, ValueError):
        score = 0
    return round(max(0, min(score, 99)), 2)
