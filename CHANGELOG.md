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
