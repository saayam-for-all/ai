# Regression audit

For each fix currently in flight: the original defect, how to reproduce it, the
fix, the tests that prove it, and what remains unverifiable from here. Written
for someone deciding whether a change is safe to merge, not for someone who
already knows the history.

The three fixes live on their own branches and are reviewed on their own pull
requests. This document is the shared context; the per-issue detail is in each
pull request.

| Issue | Branch | Pull request |
| --- | --- | --- |
| [#146](https://github.com/saayam-for-all/ai/issues/146) | `sameer/issue-146/emergency-contacts-within-country` | [#175](https://github.com/saayam-for-all/ai/pull/175) |
| [#169](https://github.com/saayam-for-all/ai/issues/169) | `sameer/issue-169/generate-answer-without-database` | [#176](https://github.com/saayam-for-all/ai/pull/176) |
| [#170](https://github.com/saayam-for-all/ai/issues/170) | `sameer/issue-170/org-search-contract-and-fallback` | [#177](https://github.com/saayam-for-all/ai/pull/177) |
| [#171](https://github.com/saayam-for-all/ai/issues/171) | `sameer/issue-171/regression-test-infrastructure` | this branch |

---

## #146 — Emergency Contacts returned the wrong country's numbers

### The defect

Three separate failures behind one report:

1. **Cross-border numbers.** When the directory had no entry for a country, or
   only a partial one, resolution fell through to another jurisdiction. A user
   abroad could be shown US numbers.
2. **Undialable values.** `AU` was stored as `"0"` for police, ambulance and
   fire. Australia's emergency number is `000`; the leading zeros had been lost,
   the classic symptom of a number round-tripped through a spreadsheet as an
   integer. Several countries had no `general_emergency` value at all.
3. **An opaque 502.** Emergency Contacts is the only method on **Lambda PROXY**
   integration, which requires the response body to be a *string*. The error
   path returned an object, so API Gateway rejected our own response and the
   page saw a `502` with nothing to diagnose.

### Reproduction

Call the endpoint with a country whose directory entry was missing or partial
and observe another country's numbers; or force any exception inside the
service and observe the `502`.

### The fix

Resolution is strictly within the requested country: a missing state or city
falls back to that **same country's** general emergency line, flagged
`is_fallback: true`, and an unresolvable country returns `404` with **no
numbers at all**. An explicit `country` parameter discards finer-grained
fields resolved elsewhere, so a city in another country cannot match by
coincidence. `AU` corrected; `general_emergency` backfilled. Every error path,
including the router's, now uses `_proxy_response`.

### Covering tests

`test_emergency_dataset.py` (dataset) asserts the shipped directory is
internally consistent — no empty or undialable value, no number belonging to
another country. `test_emergency_locale.py` (unit, expanded 6 → 32) covers
resolution order, within-country fallback and numeral localisation.
`test_response_contract.py` (contract) pins the proxy envelope on the error
paths so the `502` cannot return.

### Residual risk

- **Directory coverage is 73 countries.** The gaps are catalogued in
  `docs/emergency_numbers_provenance.md` and each needs a human-verified
  official source. The failure mode for a gap is now `404`, which is safe.
- **Country *names* only partly resolve.** `country` is matched as an ISO
  alpha-2 code; full names go through a small alias map covering the US, India,
  the UK and the UAE, so `?country=DE` resolves and `?country=Germany` returns
  `404`. Pre-existing, unchanged by the fix, and it fails safely — but callers
  should send the code.
- **The web client substitutes its own defaults** when a field is missing,
  which can reintroduce a wrong number on the client side. Different team's
  repository; a hand-off, not fixable here.

---

## #169 — "More Information" failed for everyone whenever Postgres was down

### The defect

`generate_answer` opened a database connection on **every** call to fetch the
request text — including calls from the Request Details page, which already
displays the subject and description and passes them in the payload. While the
request store was unavailable the button failed for everyone.

Two aggravating factors:

- **`psycopg2` was imported at module scope.** It is a compiled C extension, so
  a wheel built for a different Python minor version than the function's
  configured runtime failed the whole module — taking down `predict_category`,
  `generate_subject`, `emergency_contacts` and `search_orgs`, none of which
  touch the database, before any handler code ran.
- **Failures were unreportable.** A model outage returned `200` with the literal
  string `"Error: Failed to generate answer"` in the `answer` field, which the
  page rendered to the beneficiary as if it were advice, and which hid every
  outage from metrics. A store that was down was indistinguishable from a
  request that did not exist, because the handler matched on message text.

### Reproduction

Stop Postgres and call the endpoint with a valid subject and description: it
fails, though nothing it needs is missing. Or point the model client at a
retired model id and observe a `200`.

### The fix

The database became a *source*, not a precondition: a payload carrying subject
and description is answered without touching Postgres, and the lookup fills in
only what the caller did not send. `psycopg2` is imported lazily inside
`_lookup_request`. `utils/request_db.py` returns a structured `error_kind`, so
"absent" (`404`) and "store down" (`503`, retryable) are distinct. Model
failures are `502`. The response carries `source` (`request` / `database`) so a
degraded run is legible. Identifier aliases accept the spellings the web client
actually sends.

### Covering tests

`test_generate_answer.py` (contract, 27 tests) covers every documented status
code. The no-database claim is proven by patching the lookup to **raise if
called**, so the test fails if Postgres is touched at all rather than merely
being unused. Error bodies are asserted to contain no API key, host or DSN.
`test_import_blast_radius.py` (integration) pins the lazy import: it fails if
`lambda_function` imports `psycopg2` at module scope, and checks Emergency
Contacts still answers while the driver is unimportable.

### Residual risk

- **The request store is still down or being rebuilt.** Calls that genuinely
  need a `req_id` lookup keep returning `503` — now correct, retryable and
  legible, rather than a silent failure.
- **The benefit depends on the client sending the text it already has**, and on
  it branching on the status code instead of printing `answer` unconditionally.
  Both are in a different team's repository.
- **The driver itself is only 15% covered.** Everything past the connection
  call needs a live Postgres in CI.

---

## #170 — One provider outage emptied the Organizations tab

### The defect

`search_orgs` is the GenAI half of `v1/ml/orgAggregatorList`: the data team's
`saayam-org-aggregator` invokes it directly and reads
`payload["body"]["organizations"]`. That made the envelope and the field names
a **contract** — and nothing in the repository said so, nothing tested it, and
the endpoint had **no provider fallback**. Answer generation had had a Groq to
Gemini fallback since the model migration in #150; organization search never
did. A single Groq outage emptied the tab, and returned a shape that made an
outage indistinguishable from "no organizations found".

### Reproduction

Make the Groq client fail and call the endpoint: an empty result with a success
status, identical to a genuine no-results answer.

### The fix

Providers are tried in order, Groq then Gemini. `OrganizationSearchError` is
raised only when **every** provider fails and becomes a `502` carrying
`code: ORG_SEARCH_UNAVAILABLE` **and** `organizations: []`, so the tab renders
an empty state instead of throwing on `undefined`. `normalize_organization()`
guarantees all 13 names in `ORGANIZATION_FIELDS` on every row, with rating,
size and org type coerced to stable types. The body stays an object, because
this method is non-proxy and the caller reads `body.organizations` directly.

### Covering tests

`test_org_search_contract.py` (contract, 24 tests) pins the envelope, all 13
field names against a deliberately ragged model-shaped row, the provider
fallback, and the outage response.

### Residual risk

- **`orgAggregatorList` is not a deployed endpoint yet.** The GenAI side is
  ready; the data team must wire the aggregator to it.
- **Interface mismatch.** The aggregator expects
  `(subject, description, location, category)`; webapp #1301 sends
  `(request_id, beneficiary_id)`. Someone must own that translation.
- **A SQL injection exists in the aggregator's `helpers.py`** — `mission` and
  `city_name` are interpolated with f-strings. Different repository; flagged for
  that team and deserving its own security issue.
- **`rating` on a 0–10 scale is misread.** Any value above `5` is treated as a
  0–100 score and divided by 20, so `7.5/10` becomes `0.4`.

---

## #171 — This branch

### The defect

Three fixes in flight and no way for QA to regression-test any of them: tests
were loose `test_*.py` files at the repository root with no runner
configuration, no markers, no coverage measurement, no changelog and no
runbook. Each branch passed its own suite; nobody could run the union, and
nobody outside the authoring branch could tell what a pass proved.

Worse, some tests were making **live network calls** — to ipinfo.io and
Nominatim — so the suite's result depended on a third party's uptime.

### The fix

`pytest.ini` with strict markers and a fixed `testpaths`; the suite moved into
`tests/` with a `conftest.py` holding shared fixtures; every file classified
`unit` / `contract` / `dataset` / `integration`; `pytest-cov` wired with a
threshold; and an autouse guardrail that **fails any unmarked test that opens a
URL**. Adding that guardrail cut the suite from roughly 5 seconds to under 1
and made it deterministic.

### Gaps this work found and closed

Building the router tests surfaced two defects that no per-service suite could
have caught, because each of those suites calls its own handler directly and
never exercises the dispatcher:

1. **A malformed body became a `500`.** The router parsed the body before
   dispatch to discover the service name, and let `JSONDecodeError` escape. A
   bad payload reported as a server error is both wrong and unactionable in an
   alert. It is now a `400`, and when the query string already named the
   service, dispatch proceeds and the routed handler reports it in its own
   contract.
2. **The router's catch-all returned `str(e)` to the caller.** Provider and
   driver messages quote the API key, the host and the connection string, so
   this path could hand a caller a credential. The individual handlers had been
   hardened; the router had not. The detail now goes to CloudWatch and the
   caller gets a status.

Both fixes are on this branch, with tests.

### Residual risk

- **Coverage is 39% on this branch** and rises to 56% once the three fixes
  land. `services/classification_service.py` at 19% is the largest untested
  area and is not covered by any in-flight fix.
- **Nothing here tests a deployed environment.** A green suite means the
  contract held, not that AWS answers. Deployed smoke tests need access this
  team does not have.
- **The union is proven locally, not in CI.** Merging all three onto this
  branch gives 190 tests passing with no test lost, but until the branches
  merge, CI can only gate each one separately.
