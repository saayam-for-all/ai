# Search Functionality — Issue #90

This document is the implementation contract and review checklist for
[Issue #90](https://github.com/saayam-for-all/ai/issues/90). It reconciles the
AI/API work with the database implementation in
[database PR #220](https://github.com/saayam-for-all/database/pull/220).

## MVP boundary

The Phase 1 universal-search API fans out across the database-approved entities
and merges their ranked results:

| Entity | Searchable fields | Database entry point |
|---|---|---|
| Help requests | category name, subject, description, location | `search_requests(...)` |
| Users | full name and exact/fuzzy primary email | `search_users(...)` |
| Organizations | name and city | `search_organizations(...)` |

Category names are searchable through help requests. Categories also remain in
the autocomplete endpoint. Companies are excluded from Phase 1 because the DB
MVP does not expose a company-search function.

Exact user IDs, request IDs, organization IDs, category IDs, UUIDs, and email
addresses continue through confident search before the fuzzy fan-out. Only an
authorized exact match can set `auto_navigate=true`. Fuzzy matches always require
the user to choose a result.

Semantic/vector search is outside this MVP. Autocomplete exists as a separate
API extension and does not change the universal-search ranking contract.

## Request flow

1. API Gateway or trusted middleware supplies the authenticated user ID and role.
2. The API validates query and pagination inputs.
3. Confident search checks recognized exact identifiers and applies authorization.
4. If there is no exact result, the service calls all three DB search functions.
5. The API normalizes scores, deduplicates, globally ranks, and paginates results.
6. Missing auth returns `401`; an unavailable DB search layer returns `503`.

## Authorization contract

The API maps named roles into the DB function's `requester_access_level` and
passes explicit allowed-entity arrays from trusted middleware.

| API role | DB level | Default search visibility |
|---|---:|---|
| `super_admin`, `admin` | 4 | All three MVP entities |
| `organization`, `organization_admin`, `org_admin` | 3 | Own user/requests plus explicitly scoped users, request owners, and organizations |
| `volunteer`, `member` | 2 | Own user/requests plus explicitly assigned scopes |
| `beneficiary`, `requester` | 1 | Own user and own requests |
| `guest` or unknown | 0 | No DB fuzzy results unless a future approved public-search contract is added |

Scope arrays (`allowed_request_owner_ids`, `allowed_user_ids`, and
`allowed_org_ids`) are read only from trusted middleware objects in `flask.g`.
They are never accepted from client headers. API Gateway identity headers carry
only the basic user ID and role.

The DB functions independently enforce the same access inputs. This is the
agreed double-layer RBAC model: the API does not expose an unscoped result, and
the database also filters every function call.

## API behavior

### `GET /api/search`

Query parameters:

- `q`: required, 2–200 characters
- `page`: positive integer, default `1`
- `limit`: 1–20, default `10`

### `POST /api/search`

```json
{
  "q": "medical transportation",
  "page": 1,
  "limit": 10
}
```

Non-string JSON queries return `400`. Invalid pagination values use safe
defaults. Missing authentication returns a structured `401` response.

### Result shape

```json
{
  "success": true,
  "message": "Search completed",
  "query": "medical transportation",
  "page": 1,
  "limit": 10,
  "total": 3,
  "auto_navigate": false,
  "target": null,
  "results": [
    {
      "entity_type": "help_request",
      "entity_id": "REQ-00-000-000-0018",
      "title": "Need medical transportation",
      "subtitle": "Medical Care",
      "score": 83.0,
      "url": "/help-requests/REQ-00-000-000-0018",
      "match_type": "fuzzy"
    }
  ]
}
```

## Configuration

| Setting | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy database connection | none |
| `DATABASE_URL_SECRET_NAME` | Optional Secrets Manager lookup | none |
| `DATABASE_SCHEMA` | Schema containing exact-search and suggestion tables | `SEARCH_DB_SCHEMA` or `virginia_dev_saayam_rdbms` |
| `SEARCH_DB_SCHEMA` | Schema containing the search functions | `DATABASE_SCHEMA` or `virginia_dev_saayam_rdbms` |
| `AUTH_USER_ID_HEADER` | API Gateway user ID header | `X-Api-User-Id` |
| `AUTH_USER_ROLE_HEADER` | API Gateway role header | `X-Api-User-Role` |

Both schema settings are validated as SQL identifiers. Deployments should set
one regional schema value for both settings; setting either one also supplies
the other's default, and conflicting values are rejected at startup.

## Validation

Database-free API validation:

```bash
python -m unittest discover -v
python -m compileall -q app test_*.py
```

The unit suite verifies route validation, authentication errors, role mapping,
scope propagation, DB function parameters, result normalization, fan-out,
ranking, pagination, and fail-closed authorization.

## Deployment and completion checklist

- [x] Exact/confident-search API path
- [x] Suggestions endpoint
- [x] GET and POST request validation
- [x] API role-to-DB access-level mapping
- [x] Trusted entity-scope propagation
- [x] Requests/users/organizations fan-out and merged ranking
- [x] Fail-closed exact-match and suggestion authorization
- [x] Database-unavailable `503` behavior
- [x] Database-free unit coverage
- [ ] Review and merge database PR #220
- [ ] Deploy DB search scripts to an approved QA database
- [ ] Set the correct `DATABASE_SCHEMA`/`SEARCH_DB_SCHEMA` for the target region
- [ ] Run the DB PR's QA index/function checks and capture evidence
- [ ] Run API integration tests with approved sanitized accounts for each role
- [ ] Verify query plans and latency with representative QA data
- [ ] Obtain Product and Security sign-off on the matrix above
- [ ] Merge the API PR, deploy, smoke test, and close Issue #90

The unchecked items require repository maintainers, an authorized QA database,
or named stakeholder approval. They must not be represented as complete based
on local mocks alone.
