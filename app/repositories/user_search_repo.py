from typing import List

from app.auth.search_scope import build_search_scope
from app.repositories.db_search import database_schema, execute_search, fuzzy_score


def search_users(
    query: str, current_user, per_entity_limit: int = 10
) -> List[dict]:
    scope = build_search_scope(current_user)
    params = scope.database_parameters()
    params.update({"query_text": query, "limit_results": per_entity_limit})
    schema = database_schema()
    rows = execute_search(
        f"""
        SELECT * FROM {schema}.search_users(
            CAST(:query_text AS TEXT),
            CAST(:limit_results AS INTEGER),
            CAST(:requester_user_id AS VARCHAR(255)),
            CAST(:requester_access_level AS SMALLINT),
            CAST(:allowed_user_ids AS VARCHAR(255)[])
        )
        """,
        params,
    )
    return [
        {
            "entity_type": "user",
            "entity_id": row["user_id"],
            "title": row.get("full_name") or row["user_id"],
            "subtitle": f"Email: {row.get('primary_email_address') or 'N/A'}",
            "score": fuzzy_score(row.get("relevance_score")),
            "url": f"/users/{row['user_id']}",
            "match_type": "fuzzy",
        }
        for row in rows
    ]
