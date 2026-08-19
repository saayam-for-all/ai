from typing import List

from app.auth.search_scope import build_search_scope
from app.repositories.db_search import database_schema, execute_search, fuzzy_score


def search_organizations(
    query: str, current_user, per_entity_limit: int = 10
) -> List[dict]:
    scope = build_search_scope(current_user)
    params = scope.database_parameters()
    params.update({"query_text": query, "limit_results": per_entity_limit})
    schema = database_schema()
    rows = execute_search(
        f"""
        SELECT * FROM {schema}.search_organizations(
            CAST(:query_text AS TEXT),
            CAST(:limit_results AS INTEGER),
            CAST(:requester_access_level AS SMALLINT),
            CAST(:allowed_org_ids AS VARCHAR(255)[])
        )
        """,
        params,
    )
    return [
        {
            "entity_type": "organization",
            "entity_id": row["org_id"],
            "title": row.get("org_name") or row["org_id"],
            "subtitle": (
                ", ".join(
                    value
                    for value in (row.get("city_name"), row.get("state_code"))
                    if value
                )
                or "Organization"
            ),
            "score": fuzzy_score(row.get("relevance_score")),
            "url": f"/organizations/{row['org_id']}",
            "match_type": "fuzzy",
        }
        for row in rows
    ]
