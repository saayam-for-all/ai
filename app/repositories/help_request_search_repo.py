from typing import List


def search_help_requests(query: str, current_user, per_entity_limit: int = 10) -> List[dict]:
    # Fuzzy search — DB team (pg_trgm) implementation pending
    return []
