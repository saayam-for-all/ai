from typing import List

from app.auth.search_scope import build_search_scope
from app.repositories.db_search import database_schema, execute_search, fuzzy_score


def search_help_requests(
    query: str, current_user, per_entity_limit: int = 10
) -> List[dict]:
    scope = build_search_scope(current_user)
    params = scope.database_parameters()
    params.update({"query_text": query, "limit_results": per_entity_limit})
    schema = database_schema()
    rows = execute_search(
        f"""
        SELECT * FROM {schema}.search_requests(
            CAST(:query_text AS TEXT),
            CAST(:limit_results AS INTEGER),
            CAST(:requester_user_id AS VARCHAR(255)),
            CAST(:requester_access_level AS SMALLINT),
            CAST(:allowed_request_owner_ids AS VARCHAR(255)[])
        )
        """,
        params,
    )
    return [
        {
            "entity_type": "help_request",
            "entity_id": row["req_id"],
            "title": row.get("req_subj") or row["req_id"],
            "subtitle": row.get("cat_name") or row.get("req_loc") or "Help Request",
            "score": fuzzy_score(row.get("relevance_score")),
            "url": f"/help-requests/{row['req_id']}",
            "match_type": "fuzzy",
        }
        for row in rows
    ]
