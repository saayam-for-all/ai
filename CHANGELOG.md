# Changelog

Notable changes to the GenAI services. Each entry says what changed, why, and
**the behaviour difference a tester can observe** — the last part being the
reason this file exists rather than pointing at the commit log.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Entries are grouped by the issue they resolve, because that is the unit this
team works and reviews in.

## Unreleased

### Request detail accuracy — [#158](https://github.com/saayam-for-all/ai/issues/158)

Work on the LLM step that turns a help request into an answer. **Nothing about
the deployed prompt changes in this entry**: `utils.prompts.ACTIVE_VARIANT` is
still `"A"`, so a tester should see byte-identical answers to before. What
lands is the evidence, the machinery to finish the decision, and three defects
named.

**Found** — three defects in `utils/prompts.py`, none of which any test could
see, because the service returns a well-formed answer whichever prompt it built:

- **62 of the 80 taxonomy categories never reached their category prompt.**
  `category_prompts` is keyed on names the taxonomy does not use
  (`HOUSING_SUPPORT` vs. the real `HOUSING_ASSISTANCE`), so every top-level
  category and every deep leaf — `PLUMBING`, `MATH`,
  `CARDIAC_OR_BLOOD_PRESSURE` — silently fell back to the generic `General`
  prompt. The per-category prompt work from #47 was, for most requests, not
  running.
- **The prompt contradicts itself.** `BASE_INSTRUCTION` forbids naming
  organizations, addresses and emergency numbers; the category bodies it is
  interpolated into demand them ("ALWAYS include relevant emergency phone
  numbers"). Measured consequence: on one corpus case the model spent 1453
  output tokens failing to reconcile the two and **returned nothing 3 times out
  of 6**, which `utils/__init__.py` reads as a Groq outage and answers from
  Gemini instead — a silent model switch and a double bill.
- **The length rules fight the content rules** — 2-3 sentences under 60 words,
  against bodies demanding an enumerated `(1)(2)(3)` answer.

**Added**

- `utils/prompts.py` — five selectable prompt variants behind
  `get_conversational_prompt(..., variant=)`, with `ACTIVE_VARIANT` choosing
  what production serves. Variant A is the deployed prompt, verified
  byte-identical, so the baseline is real. B fixes category routing; C removes
  the contradictions; D adds an anti-invention block; E restores the
  concreteness C and D cost. Category resolution now walks the taxonomy
  upwards, so a new leaf inherits its parent's prompt instead of degrading to
  `General` — coverage goes from 18 of 80 categories to 79 of 80.
- `tools/request_detail_corpus.py` — 55 labeled help requests across 49
  taxonomy categories, including 5 crisis cases and 24 adversarial ones (a
  request filed under the wrong category, three needs in one request, no
  location, a prompt-disclosure probe).
- `tools/measure_prompt_accuracy.py` — the A/B harness. Three metrics (intent
  fidelity, groundedness, constraint adherence), crisis escalation and false
  escalation reported separately so a variant cannot buy a headline by being
  unsafe, paired per-case bootstrap confidence intervals, and cross-judging by
  two other models. Resumable, because a full run costs ~660k tokens against a
  200k/day free-tier cap.
- `docs/metrics/REQUEST_DETAIL_ACCURACY.md` — the defects, the method, the
  measured results, the quota arithmetic, and what is still outstanding.
- `tests/test_request_detail_prompts.py` and
  `tests/test_prompt_accuracy_metrics.py` — 237 hermetic tests. They pin the
  routing defect at its exact count so it cannot silently return, and pin
  `ACTIVE_VARIANT == "A"` so no one ships a variant the A/B has not judged.

**Removed**

- `get_prompt()` in `utils/prompts.py` — 67 lines of dead code. Nothing had
  ever called it; only `get_conversational_prompt` is on the answer path, and
  the two had drifted apart.
- `utils/prompts_no_hallucination_reviewed.py` — 753 lines, never imported. Its
  anti-hallucination block is now variant D, where it can be measured.

**Changed — the deployed prompt.** `utils.prompts.ACTIVE_VARIANT` moves from
`"A"` to `"F"`. A tester will see shorter answers (mean 63 -> 52 words), far
fewer invented organizations and phone numbers, and — the reason F ships rather
than E — a request describing danger to life now gets told to contact emergency
services.

Measured on the 55-case corpus, paired per case against the previously deployed
prompt, 95% percentile bootstrap:

| | A (was deployed) | E | **F (shipped)** | F vs A, 95% CI | sig. |
|---|---|---|---|---|---|
| Intent fidelity | 0.751 | 0.780 | 0.771 | +0.020 [-0.061, +0.099] | no |
| Groundedness | 0.681 | 0.790 | **0.846** | +0.164 [+0.066, +0.268] | **yes** |
| Constraint adherence | 0.912 | 0.982 | 0.961 | +0.049 [+0.023, +0.074] | **yes** |
| Composite | 0.782 | 0.851 | **0.859** | +0.078 [+0.033, +0.124] | **yes** |
| Crisis escalation | 1/5 | 1/5 | **5/5** | | |
| False escalation (all 50 non-crisis cases) | 2/50 | **0/50** | 4/50 | | |

**The substantive finding is the row that is not in the composite.** Variant E
beat the baseline on composite by +0.070, significant, and would have shipped on
a single score — while answering a person describing suicidal thoughts, and a
person fleeing their home at night with a child, by suggesting they ask Saayam
for a volunteer. Crisis escalation and false escalation were deliberately kept
out of the composite, and they are the only reason that did not happen.

Scored strictly — does the answer name a real emergency contact, rather than
merely sound urgent — **the previously deployed prompt escalated 1 of 5
life-threatening cases.** The regex check caught the judge scoring "look into
local shelters... reach out to community groups or hotlines" as an escalation
when it names nothing.

**Added**

- Variant F: escalation outranks the length limit, published emergency and
  crisis numbers are permitted (a national emergency line is public
  infrastructure, not an unverifiable third-party contact), and a Saayam
  volunteer may never be the answer to a life-threatening situation.
- `detect_escalation()` — a deterministic second reading of the metric that
  gates deployment, so it never rests on one model's opinion.
- `--rescore` — recomputes every code-side metric from stored answers with no
  model calls, so correcting a metric does not cost another day of token quota.

**Fixed — in the measurement, not the service.** `score_constraints()` was
marking down *"Call emergency services immediately."* — the correct four-word
reply to a toddler with a non-blanching rash — for not ending with a
conversational question. A format metric that penalises correct safety
behaviour is the composite's mistake one level down. The follow-up-question
checks are now waived when an answer names a real emergency contact, and only
then.

**Corrected after review** — two of this entry's own claims were wrong, both
found by review on #201:

- **F over-escalates, and the metric hid it.** False escalation was computed
  over one case and read "0 of 1". Over all 50 non-crisis cases it is **4 of 50
  for F against 2 of 50 for the prompt it replaces** — twice as often. A year of
  heavy periods with exhaustion was answered *"Call your local emergency
  services now"*; no heating with a baby got a seven-word *"Call emergency
  services now for immediate help."* with intent falling 0.5 to 0.00. The format
  waiver compounded it by discounting all four, and now fires only on cases
  labelled `safety: crisis`. F's composite moves 0.862 to 0.859.
- **Variant B was not "A plus routing".** The regex that lifted the deployed
  base instruction into a constant matched a commented-out older copy, so B
  carried no rule against phone numbers. The claim that fixing category routing
  *without* fixing the contradictions is worse than doing nothing **is
  withdrawn** — that variant never tested it. Variant A was unaffected and is
  still byte-identical to the deployed prompt.

**Known limits of the shipped result** — all three variants ran all 55 cases,
but crisis escalation still rests on five of them, which is thin for the
highest-stakes behaviour in the service. Intent fidelity is a tie with the
baseline, not a gain. On the burning-socket case F escalates but drops "turn off
the breaker", which the baseline gave; the cause is one clause in the override
("say the urgent thing first **and stop**") and the fix is deliberately not
applied here, because editing a prompt after measuring it means shipping
something untested — it is variant G, in
`docs/metrics/REQUEST_DETAIL_ACCURACY.md` section 9. B, C and D still have only
pilot-scale evidence.

**Also not done, deliberately** — `utils/client.py` builds the answer-generation
client without `reasoning_effort`, which
`services/classification_service.py` already sets for the same model and the
same reason. That is the root cause of the empty responses above. Changing it
would alter the baseline underneath the A/B, so it is documented as a separate
defect rather than smuggled in here.

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
### Generate Answer — follow-up questions — [#183](https://github.com/saayam-for-all/ai/issues/183)

**Fixed**

- **The chat answered the original request instead of the follow-up question.**
  The More Information modal appends the person's new question to
  `conversation_history` and sends nothing else, so from the second turn
  onwards the last entry of the transcript *is* the question. The service put
  it one turn upstream and made the final message
  `Subject: <subject>\nQuestion: <original description>` — and the final
  message is the one a model answers. Every follow-up was therefore answered as
  if the person had re-asked their request.
  *Observable difference:* asking "which documents do I need to bring?" used to
  return another general answer about the original request. It now answers the
  question. Demonstrated before and after on the same payload:

  ```
  before  'Subject: Need help with fixing wooden cabinet\nQuestion: Need help with tiling wooden cabinet'
  after   'Which documents do I need to bring?'
  ```

  The request itself is still given to the model — as background appended to
  the system prompt, which is where context belongs rather than in the position
  the model treats as the question.
- **A transcript that was not a list raised `TypeError` from inside the
  service.** The handler drops a non-list before it gets there, but this is a
  public service method and the data team's aggregator invokes the package
  directly, so it cannot assume a caller has checked.

**Changed**

- Single-shot behaviour is unchanged, deliberately and byte-for-byte: with no
  history — the opening click, and the aggregator's direct invoke — the prompt
  is exactly what it was, and the request-context block is not added at all.

**Security**

- A `system` role in the client transcript is still dropped, so a caller cannot
  replace the instructions the answer is generated under. This was already true
  and is now covered by a test, because the follow-up path is a second place
  that reads the transcript.

**Added**

- Bounds on what a client transcript can spend: `MAX_HISTORY_MESSAGES` (20
  most recent turns) and `MAX_MESSAGE_CHARS` (4000 per message). The modal
  enforces five questions and 250 characters in the browser, which is a UI
  convenience, not a limit anyone else is held to. Trimming never removes the
  question being asked.
- `tests/test_answer_conversation.py` — 21 tests over the exact message list
  that would be sent to the provider. Nothing in the suite asserted prompt
  assembly before, which is why a wrong final turn passed 200 green tests.
  Includes the regression test for this defect, the single-shot prompt asserted
  literally, transcript hygiene (non-dict entries, unknown roles, blank turns,
  a trailing assistant turn) and the Groq→Gemini fallback on a follow-up.

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
