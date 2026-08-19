"""Validated database schema configuration shared by search models."""

import os
import re


_DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_schema_name(value: str) -> str:
    if not isinstance(value, str) or not _SCHEMA_RE.fullmatch(value):
        raise RuntimeError("DATABASE_SCHEMA must be a valid SQL identifier")
    return value


DATABASE_SCHEMA = validate_schema_name(
    os.getenv("DATABASE_SCHEMA", os.getenv("SEARCH_DB_SCHEMA", _DEFAULT_SCHEMA))
)
