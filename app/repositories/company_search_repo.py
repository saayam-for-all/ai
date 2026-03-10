from sqlalchemy import or_, func
from app.extensions import db
from app.utils.search_utils import normalize_query, build_contains_pattern, score_text_match

# Uncomment when model exists
# from app.models.company import Company


def search_companies(query: str, current_user, per_entity_limit: int = 10) -> list[dict]:
    """
    Keep safe for now if Company is not finalized in the data model.
    """
    return []

    # Example implementation once Company exists:
    #
    # q = normalize_query(query)
    # contains = build_contains_pattern(query)
    #
    # matched_rows = (
    #     db.session.query(Company)
    #     .filter(
    #         or_(
    #             func.lower(Company.company_id) == q,
    #             func.lower(Company.name).like(contains),
    #         )
    #     )
    #     .limit(per_entity_limit)
    #     .all()
    # )
    #
    # results = []
    # for row in matched_rows:
    #     score = score_text_match(
    #         query=query,
    #         entity_id=row.company_id,
    #         primary_text=row.name,
    #         secondary_text="",
    #         tags=[],
    #     )
    #
    #     results.append(
    #         {
    #             "entity_type": "company",
    #             "entity_id": row.company_id,
    #             "title": row.name,
    #             "subtitle": "Company",
    #             "score": score,
    #             "url": f"/companies/{row.id}",
    #         }
    #     )
    #
    # return results