# Changelog

Notable changes to the GenAI services. Each entry says what changed, why, and
**the behaviour difference a tester can observe** — the last part being the
reason this file exists rather than pointing at the commit log.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Entries are grouped by the issue they resolve, because that is the unit this
team works and reviews in.

## Unreleased

### Testing infrastructure — [#171](https://github.com/saayam-for-all/ai/issues/171)

**Added**

- `pytest.ini` — fixed `testpaths`, strict markers and strict config. `pytest`
  previously worked only by accident of filename discovery at the repository
  root and collected `__pycache__` noise.
- `tests/` — the loose root-level `test_*.py` files moved into one package,
  with `tests/conftest.py` providing shared fixtures (event builders, fakes for
  the model, the database and organization search, and a body reader that
  handles both integration styles) so tests stop re-declaring their own mocks.
- Kind markers on every test: `unit`, `contract`, `dataset`, `integration`,
  plus `slow` and `needs_network`. QA can now run a slice —
  `python -m pytest -m contract` — instead of the whole suite.
- **A network guardrail.** An autouse fixture fails any unmarked test that
  opens a URL. Some tests were reaching ipinfo.io and Nominatim live, so the
  suite's result depended on a third party's uptime and rate limits.
- `pytest-cov` and `requirements-dev.txt`, kept out of `requirements.txt` so
  the Lambda bundle does not carry test tooling.
- `tests/test_router.py` — 31 tests covering `lambda_handler`, which nothing
  tested before. Each service suite calls its own handler directly, so a
  routing mistake would have passed every test while breaking the deployed API.
- `tools/gen_test_catalogue.py` and the documentation set: `QA_RUNBOOK.md`,
  `TEST_CATALOGUE.md` (generated from the suite, so it cannot go stale),
  `COVERAGE.md` and `REGRESSION_AUDIT.md`.

**Fixed** — two defects the router tests surfaced:

- A **malformed request body returned `500`**. The router parsed the body before
  dispatch to find the service name and let `JSONDecodeError` escape. A client
  error reported as a server error is unactionable in an alert.
  *Observable difference:* `POST` with body `{not json` now returns **`400`**
  with `{"error": "Request body is not valid JSON"}` instead of a `500`. When
  the query string already names the service, dispatch proceeds and the routed
  handler reports the bad payload in its own error contract.
- The router's catch-all **returned the raw exception text to the caller**
  (`{"error": str(e)}`). Provider and driver messages quote the API key, the
  host and the connection string, so this path could hand a caller a
  credential. The individual handlers had been hardened; the router had not.
  *Observable difference:* an unexpected failure now returns
  `{"error": "Request failed"}` and the detail appears in CloudWatch only.

**Observable difference overall:** `python -m pytest` runs green from a clean
checkout with a stated count (**63** on this branch), in about a second rather
than five, with no network access required.

---

The three entries below describe work on separate branches, each with its own
pull request. They are recorded here so QA has one place to see what is
changing and what to verify. Full detail, including residual risk, is in
[`docs/testing/REGRESSION_AUDIT.md`](docs/testing/REGRESSION_AUDIT.md).

### Emergency Contacts — [#146](https://github.com/saayam-for-all/ai/issues/146) · PR [#175](https://github.com/saayam-for-all/ai/pull/175)

**Fixed**

- Resolution never crosses a border. A missing state or city falls back to that
  **same country's** general emergency line; an unresolvable country returns
  `404` with no numbers rather than another country's.
  *Observable difference:* request a country with a partial directory entry and
  you get that country's own general line flagged `is_fallback: true`, or a
  `404` — never US numbers.
- `AU` corrected from `"0"` to `"000"`. `"0"` is not dialable; Australia's
  Triple Zero had lost its leading zeros. `general_emergency` backfilled where
  it was missing.
- The `502`. Emergency Contacts is the only method on **PROXY** integration,
  which requires a string body; the error path returned an object, so API
  Gateway rejected our own response.
  *Observable difference:* forcing an error returns a `500` whose body is a
  JSON **string**, instead of an undiagnosable `502`.

**Added** — `docs/emergency_numbers_provenance.md` (every changed number traced
to an official source, plus the rule that a model may research a number but
never decide one, and is never called at request time); a `test` job in the
deploy workflow gating `build` and `deploy`; PRs run tests only and never touch
AWS.

### Generate Answer — [#169](https://github.com/saayam-for-all/ai/issues/169) · PR [#176](https://github.com/saayam-for-all/ai/pull/176)

**Changed**

- The database is a source, not a precondition. A payload carrying `subject`
  and `description` is answered **without opening a Postgres connection**.
  *Observable difference:* with the request store down, the More Information
  button works for any caller that sends the text it already has.
- `psycopg2` is imported lazily. At module scope, a packaging problem in that
  one compiled dependency took down every service in the deployment.

**Fixed**

- Error classification. `404` (no such request), `503`
  `REQUEST_STORE_UNAVAILABLE` with `retryable: true` (store down), `502`
  `ANSWER_GENERATION_FAILED` / `ANSWER_EMPTY` (model), `400` (bad payload).
  *Observable difference:* a model outage used to return `200` with the string
  `"Error: Failed to generate answer"` as the answer, rendered to the
  beneficiary as advice. It is now a `502`.
- Identifier aliases accept the spellings the web client sends.
- Errors no longer leak the DSN, host or API key; logging records payload key
  names, never values.

### Generate Answer — request table pluralization — [#169](https://github.com/saayam-for-all/ai/issues/169)

**Fixed**

- **The request lookup read a table that no longer exists.** The database team
  renamed `virginia_dev_saayam_rdbms.request` to `requests` in the live
  Virginia database on **2026-08-17**, as part of the pluralization tracked in
  [database#73](https://github.com/saayam-for-all/database/issues/73) and
  recorded in [CAPA#3](https://github.com/saayam-for-all/CAPA/issues/3). Our
  statement still named the singular table, so every lookup raised
  `UndefinedTable`.
  *Observable difference:* a More Information call that falls back to the
  database — one sending `user_id` and `req_id` without `subject` and
  `description` — returned `503 REQUEST_STORE_UNAVAILABLE` on **every** attempt
  since 17 August. It now reaches the row.
  Only the request table was in the rename set; `req_add_info`,
  `req_add_info_metadata` and `list_item_metadata` keep their singular names.

**Changed**

- **A stale statement is no longer dressed up as an outage.** A
  `psycopg2.ProgrammingError` — `UndefinedTable`, `UndefinedColumn` or a syntax
  error — is classified `schema_mismatch` and returns `500`
  `REQUEST_STORE_SCHEMA_MISMATCH` with `retryable: false`, instead of the
  retryable `503` used for a database that is down.
  *Observable difference:* this is why the rename went unnoticed for thirteen
  days. Every caller was told "store unavailable, please retry", so the
  signature looked like a database still being rebuilt rather than a query that
  had gone stale. The driver message still goes to CloudWatch only.
- The schema and request table names are read from `SAAYAM_DB_SCHEMA` and
  `SAAYAM_DB_REQUESTS_TABLE`. The DDL in `saayam-for-all/database` is applied to
  the live database by hand and lags it — the schema files on `dev` and `main`
  still create a singular `request` today — so a deployment has to be
  correctable without a code change if a rename lands or is rolled back.

**Added**

- `tests/test_request_db_schema.py` — 9 tests naming, in one reviewable place,
  every table and key column we depend on in another team's schema. Nothing in
  the suite executed this statement before: all endpoint tests mock the lookup
  at `_lookup_request`, which is precisely why a renamed table passed 190 green
  tests. Includes a guard on `req_user_id`, which the same wiki page lists as
  pending rename to `creator_id`.

### Generate Answer — owner column rename and schema drift — [#169](https://github.com/saayam-for-all/ai/issues/169)

The second half of the same migration. Pluralization was only one of the
changes applied to the live `requests` table; the entry above fixed the table
name, and the very next call failed on a column.

**Fixed**

- **`req_user_id` no longer exists.** It was renamed to `creator_id` and
  `beneficiary_id` / `lead_volunteer_id` were added alongside it, per
  [database#224](https://github.com/saayam-for-all/database/issues/224). Our
  statement both projected and filtered on the old name, so every
  database-backed lookup raised `UndefinedColumn`.
  *Observable difference:* a More Information call sending `user_id` and
  `req_id` returned `500 REQUEST_STORE_SCHEMA_MISMATCH` on every attempt. It
  now reaches the row.
- **Both owner columns are matched.** `creator_id` and `beneficiary_id` are
  different people — the creator raised the request, the beneficiary is who it
  is for. The web client resolves the `user_id` it sends from whichever its
  page happens to hold, so filtering on one alone returned "no request found"
  for a large share of real traffic.

**Added**

- **Schema introspection.** The statement is now built from what
  `information_schema` reports the request store actually has, resolved once
  per Lambda container and cached per schema. A renamed optional column is
  projected as `NULL`; a missing additional-info table drops the join; a
  singular `request` table with `req_user_id` — which the DDL repository and
  the Ireland region scripts still describe — produces the old statement
  instead of an outage.
  *Observable difference:* neither of the two renames that took this endpoint
  down would have taken it down under this code.
- **A degraded answer instead of a dead end.** When the request store cannot
  be read and the person has asked a follow-up question, that question is
  answered on its own and the response carries `source: "conversation"` and
  `degraded: "<code>"`. The failure is still logged to CloudWatch and still
  named in the response.
  *Observable difference:* mid-conversation, a store outage now produces an
  answer marked as general rather than an error dialog.
- **A presentable `message` on store-failure responses**, so a client can show
  the person something human. Deliberately not called `answer`: it is never
  advice and must never be rendered as any.
- **The additional-info join is finally read.** `req_add_info` and its metadata
  have been fetched on every lookup since this endpoint was written and the
  result was discarded. The answers the beneficiary filled in now reach the
  model as request context.
  *Observable difference:* answers reference details from the request form —
  household size, dates, documents held — that were previously invisible to the
  model.
- `gender` and `age` are passed through to the prompt builder when the caller
  sends them. The builder has always accepted them; the handler never sent
  them.

**Changed**

- Two new operator overrides beside the existing `SAAYAM_DB_SCHEMA` and
  `SAAYAM_DB_REQUESTS_TABLE`: `SAAYAM_DB_REQUEST_OWNER_COLUMNS` (comma
  separated) pins the owner predicate, and `SAAYAM_DB_SCHEMA_INTROSPECTION=off`
  disables discovery. Configuration still beats discovery so an incident can be
  handled without a release; a pin that names a column the database no longer
  has degrades to the discovered set rather than breaking.

**Security**

- The owner predicate is never dropped. If a schema is ever found with no
  recognised owner column the lookup fails closed with `schema_mismatch`,
  rather than widening to `WHERE req_id = %s` and handing any request to
  anyone holding its id.
- The degraded path is not reachable from `not_found`. A request that does not
  exist, or does not belong to the caller, is still a `404` even when a
  follow-up question is present — otherwise a guessed `req_id` would be
  answered on the strength of the question alone.

**Added — tests** (`tests/test_request_db_schema.py`, `tests/test_generate_answer.py`)

- 249 tests pass, up from 190. Coverage 65%, up from 56%;
  `utils/request_db.py` 84%, `lambda_function.py` 93%.
- The guard written in the previous entry did its job: the test asserting
  `WHERE r.req_user_id = %s` failed on the first run after the rename landed,
  naming the WHERE clause. It has been rewritten to assert the current columns
  and now records that history.
- New coverage for every degradation path — rolled-back database, missing
  optional column, missing join tables, introspection denied, introspection
  disabled, stale operator pin, two regions with different layouts — and for
  every refusal: no request table, no owner column, no `req_desc`.

### Organizations search — [#170](https://github.com/saayam-for-all/ai/issues/170) · PR [#177](https://github.com/saayam-for-all/ai/pull/177)

**Added**

- A Gemini fallback. Answer generation had had one since the model migration in
  #150; organization search had none, so a single Groq outage emptied the tab.
  *Observable difference:* with Groq unavailable, results still return.
- `normalize_organization()` guarantees all 13 names in `ORGANIZATION_FIELDS`
  on every row, with rating, size and org type coerced to stable types.

**Fixed**

- A total provider outage returned an empty success. It is now `502` with
  `code: ORG_SEARCH_UNAVAILABLE` **and** `organizations: []`, so an outage is
  distinguishable from "no results" while the tab still renders.

**Documented** — this endpoint is the GenAI half of `orgAggregatorList`, which
answers open question **D15** in the BRD. Its envelope and field names are a
contract a consumer in another repository depends on.
