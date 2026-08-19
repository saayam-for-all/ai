import json
import os
from typing import Optional


def _get_database_url() -> Optional[str]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    secret_name = os.getenv("DATABASE_URL_SECRET_NAME")
    if not secret_name:
        return None

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        raise RuntimeError(
            "boto3 is required to load DATABASE_URL_SECRET_NAME from Secrets Manager"
        )

    client = boto3.client("secretsmanager")
    try:
        secret_response = client.get_secret_value(SecretId=secret_name)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"Unable to load database secret: {exc}") from exc

    secret_string = secret_response.get("SecretString")
    if not secret_string:
        raise RuntimeError("Secrets Manager response did not contain SecretString")

    secret_data = json.loads(secret_string)
    return secret_data.get("DATABASE_URL")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    API_URL_PREFIX = os.getenv("API_URL_PREFIX", "/api")
    AUTH_USER_ID_HEADER = os.getenv("AUTH_USER_ID_HEADER", "X-Api-User-Id")
    AUTH_USER_ROLE_HEADER = os.getenv("AUTH_USER_ROLE_HEADER", "X-Api-User-Role")
    DATABASE_SCHEMA = os.getenv(
        "DATABASE_SCHEMA",
        os.getenv("SEARCH_DB_SCHEMA", "virginia_dev_saayam_rdbms"),
    )
    SEARCH_DB_SCHEMA = os.getenv("SEARCH_DB_SCHEMA", DATABASE_SCHEMA)
    if DATABASE_SCHEMA != SEARCH_DB_SCHEMA:
        raise RuntimeError(
            "DATABASE_SCHEMA and SEARCH_DB_SCHEMA must identify the same schema"
        )
