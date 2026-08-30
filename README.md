# Saayam For All AI Services (AWS Lambda)

A suite of serverless backend services built on AWS Lambda that provides context-aware AI capabilities, classification, search, and emergency contact resolution for the Saayam platform.

These services run independently as separate Lambda functions or under a single unified routing Lambda function.

---

## Architecture & Deployment Model

This codebase supports two hosting paradigms:
1. **Unified Endpoint Routing**: Routing all service requests through a single entry point (`lambda_function.lambda_handler`) using a `"service"` selector parameter.
2. **Independent Microservices (Recommended)**: Deploying five separate AWS Lambda functions sharing the same deployment package, each pointing to its own dedicated handler entry point.

### Handlers & Configurations

| Lambda Service | Entry Point Handler | Recommended Memory | Recommended Timeout |
| :--- | :--- | :--- | :--- |
| **Predict Category** | `lambda_function.predict_category_handler` | 256 MB | 15 seconds |
| **Generate Subject** | `lambda_function.generate_subject_handler` | 256 MB | 15 seconds |
| **Generate Answer** | `lambda_function.generate_answer_handler` | 1024 MB | 60 seconds |
| **Emergency Contacts** | `lambda_function.emergency_contacts_handler` | 256 MB | 15 seconds |
| **More Organizations** | `lambda_function.search_orgs_handler` | 512 MB | 45 seconds |

---

## Project Structure

```text
ai/
├── .github/workflows/
│   └── deploy_aws_lambda.yml      # CI/CD pipeline deploying all 5 functions in parallel
├── services/
│   ├── emergency.py               # Emergency contact geolocation and lookup logic
│   ├── emergency_numbers.json     # Global emergency numbers database by country/state/city
│   └── classification_service.py  # Category prediction algorithms
├── utils/
│   ├── categories.py              # Category mappings
│   ├── categories_with_description.py # Category description mappings
│   ├── client.py                  # SSM Parameter Store LLM client bootstrap (Groq/Gemini)
│   ├── generate_answer_service.py # Core answer generation service
│   ├── request_db.py              # Database request details fetcher
│   ├── search_orgs.py             # More Organizations (search nonprofits/for-profits)
│   └── subject_generator.py       # Subject line generation service
├── lambda_function.py             # Entry points for all AWS Lambda functions
├── requirements.txt               # Pipeline dependencies
└── README.md                      # This file
```

---

## Environment & Secrets Configuration

All services leverage **AWS SSM Parameter Store** (and IAM Roles) to access keys rather than exposing them as raw environment variables.
* **SSM Parameter Names**:
  - `/dev/saayam/GenAI/groq/key` (Groq API Key)
  - `/dev/saayam/GenAI/gemini/key` (Gemini API Key)

---

## Service Details & curl Test Cases

### 1. Predict Category
Classifies description text into a ranked list of help categories.

#### request Payload
```json
{
  "description": "Need help with tutoring in math"
}
```

#### curl Command
```bash
curl -X POST https://<api-gateway-url>/predict-category \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Need help with tutoring in math"
  }'
```

---

### 2. Generate Subject
Generates a short, descriptive subject line from a user's request details.

#### request Payload
```json
{
  "description": "Need help finding and leasing the best apartment  in San Jose under 1500$ budget"
}
```

#### curl Command
```bash
curl -X POST https://<api-gateway-url>/generate-subject \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Need help finding and leasing the best apartment  in San Jose under 1500$ budget"
  }'
```

---

### 3. Generate Answer
Generates a structured, context-aware response to a help request. Backs the
**More Information** button on the Request Details page.

The database is a *source* of the request text, not a precondition. Send the
text you already have and the request row is never read; send identifiers and
the row is read to fill in what is missing. See issue #169.

#### request Payload — text supplied by the caller (no database read)
```json
{
  "subject": "Need winter coats",
  "description": "Two children, no warm clothing, snow forecast next week.",
  "location": "Chicago",
  "category": "Clothing",
  "conversation_history": []
}
```

#### request Payload — looked up from the request row
```json
{
  "user_id": "SID-00-000-02-356",
  "req_id": "REQ-00-000-000-0377",
  "conversation_history": []
}
```

`user_id` also accepts `userId`, `req_user_id`, `beneficiary_id`,
`beneficiaryId` and `userDBid`. `req_id` also accepts `request_id`,
`requestId` and `id`, which is what the Request Details page holds. At least
one of the two payload styles must be satisfied: either `subject` **and**
`description`, or `user_id` **and** `req_id`.

#### Response
```json
{ "answer": "<markdown>", "source": "request" }
```

This method uses **non-proxy** integration, so the client reads
`response.body.answer`. `source` is `"request"` when the text came from the
payload and `"database"` when it came from the request row.

| Status | Meaning |
|---|---|
| 200 | Answer generated |
| 400 | Neither text nor identifiers supplied, or the body is not a JSON object |
| 404 | No request row for that `user_id` / `req_id` |
| 503 | `REQUEST_STORE_UNAVAILABLE` — Postgres is down; retryable |
| 502 | `ANSWER_GENERATION_FAILED` / `ANSWER_EMPTY` — the model failed |

A model failure is never reported as a 200. Driver-level database errors are
logged to CloudWatch and never returned to the caller.

#### What the client must do with each status

| Status | Client behaviour |
| --- | --- |
| `200` | Render `answer`. It is markdown. |
| `400` | A payload bug — the request did not carry text *or* identifiers. Do not retry unchanged. |
| `404` | The request genuinely does not exist. Do not retry. |
| `503` | Postgres is down. The body carries `"retryable": true` — offer a retry rather than showing a permanent failure. |
| `502` | Answer generation failed. Show "couldn't generate an answer", **not** the raw body. |

The old behaviour returned `200` with the literal string
`"Error: Failed to generate answer"` in `answer`, which the page rendered to
the beneficiary as if it were advice, and which hid model outages from every
metric. Clients must stop treating a `200` as proof of a usable answer and
must branch on the status code.

**Send the text when you have it.** The Request Details page already displays
`subject` and `description`, so passing them means the answer does not depend
on the request store being up at all. Sending only identifiers makes the call
fail whenever Postgres is unavailable.

#### Operational notes

`utils/request_db.py` imports `psycopg2`, a compiled C extension, and is
imported **lazily** inside the lookup rather than at module scope. At module
scope a packaging problem in that one dependency took down every service in the
deployment — including `predict_category` and `emergency_contacts`, which never
touch the database — before any handler code could run.

The handler logs the **key names** of the payload and never its values. A help
request description carries health, housing and financial detail, and the
headers carry the caller's token.

`.github/scripts/deploy_lambda.sh` verifies the deployed function's Python
runtime and fails the deploy on a mismatch, because a silent runtime drift is
how the `psycopg2` breakage reached production in the first place.

#### Regression tests covering this service

| File | Proves |
| --- | --- |
| `test_generate_answer.py` | Every row of the status table above; that a payload carrying text performs **no** database call; that all identifier aliases resolve; and that no API key, host or provider name appears in any error body. |
| `test_client_imports.py` | The module imports without the database driver present, so one dependency cannot take down the other services. |

#### curl Command
```bash
curl -X POST https://<api-gateway-url>/generate-answer \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "SID-00-000-02-356",
    "req_id": "REQ-00-000-000-0377",
    "conversation_history": []
  }'
```

---

### 4. Emergency Contacts
Resolves matching emergency numbers based on query parameters (latitude/longitude, zipcode, or IP geolocation).

#### request Payload (Body or Query string)
```json
{
  "zip": "95112",
  "country": "US",
  "language": "en"
}
```

#### curl Command (POST)
```bash
curl -X POST https://<api-gateway-url>/emergency-contacts \
  -H "Content-Type: application/json" \
  -d '{
    "zip": "95112",
    "country": "US",
    "language": "en"
  }'
```

#### curl Command (GET query fallback)
```bash
curl -X GET "https://<api-gateway-url>/emergency-contacts?zip=95112&country=US&language=en"
```

#### Response

```json
{
  "services": {
    "general_emergency": { "dial_number": "112", "display_number": "११२", "source": "directory", "is_fallback": false },
    "fire":              { "dial_number": "101", "display_number": "१०१", "source": "directory", "is_fallback": false },
    "women_helpline":    { "dial_number": "112", "display_number": "११२", "source": "general_emergency_fallback", "is_fallback": true }
  },
  "language": "hi",
  "country": "IN",
  "match_level": "country",
  "resolved_location": { "country": "IN" }
}
```

- `dial_number` is always ASCII and is what a click-to-call link must use.
  `display_number` is the same number in the requested language's numerals.
- `is_fallback` is `true` when the directory holds no entry for that service in
  that country and the country's own general emergency line is being returned
  instead. Label those rows as a general emergency line rather than presenting
  them as the specific service.
- Numbers never cross a border. If the country cannot be resolved, or the
  country is not in the directory, the endpoint answers `404` rather than
  returning another country's numbers. **Clients must render "unavailable" in
  that case and must not substitute a default of their own** — a hardcoded
  `911` or `988` is the safety violation described in
  [issue #146](https://github.com/saayam-for-all/ai/issues/146).
- Pass `service=<name>` to request a single service. Recognised names are
  `general_emergency`, `police`, `ambulance`, `fire`, `disaster_management`,
  `women_helpline` and `suicide_helpline`.

Provenance for the numbers in `services/emergency_numbers.json` is recorded in
[`docs/emergency_numbers_provenance.md`](docs/emergency_numbers_provenance.md).

#### Status codes

| Code | Meaning | What the client should do |
| --- | --- | --- |
| `200` | Numbers resolved for the requested country. | Render them. Label any row with `is_fallback: true` as a general emergency line. |
| `404` | The country could not be resolved, or is not in the directory. **No numbers are returned.** | Render "unavailable". **Never substitute a default.** |
| `500` | The lookup itself failed. Body is `{"error": "Emergency services lookup failed"}`. | Render "unavailable" and retry. Detail is in CloudWatch, deliberately not in the response. |

This method is the only one on **Lambda PROXY integration**, so its body is a
JSON **string**. Returning an object body here is what made API Gateway reject
our own response and surface an undiagnosable `502` — the failure reported in
[issue #146](https://github.com/saayam-for-all/ai/issues/146). Every path,
including the error paths and the router fallback, now goes through
`_proxy_response`.

#### Resolution order

`lat`/`lng` (reverse geocoded) → `zip`/`city`/`state` (geocoded) → bare `city`
matched in the directory, but **only when exactly one country contains it** →
caller IP. An explicit `country` overrides all of the above and **discards**
finer-grained fields resolved elsewhere, so a city belonging to a different
country cannot match by coincidence.

Within a country: the requested state or city entry, else that **same
country's** `general_emergency` line, marked `is_fallback: true`. There is no
step that leaves the country.

#### Known limitation

`country` is matched as an **ISO 3166 alpha-2 code** (`DE`, `IN`, `BR`).
Full country *names* resolve only through a small alias map covering the United
States, India, the United Kingdom and the UAE, so `?country=DE` resolves but
`?country=Germany` returns `404`. This is pre-existing behaviour and it fails
*safely* — no numbers rather than the wrong country's — but callers should send
the alpha-2 code. Widening this is tracked as remaining work on issue #146.

#### Regression tests covering this service

| File | Proves |
| --- | --- |
| `test_emergency_dataset.py` | Every entry in the shipped directory is well-formed: no empty or undialable value, no number belonging to another country. |
| `test_emergency_locale.py` | Resolution order, within-country fallback, `is_fallback` flagging, per-service match level, and numeral localisation. |
| `test_response_contract.py` | The proxy envelope, including on the error paths, so the `502` cannot come back. |

---

### 5. More Organizations
Returns 6 verified organizations (3 nonprofit, 3 for-profit) close to the user's location related to their request.

**This endpoint has a second consumer outside this repository.** The data
team's `saayam-org-aggregator` serves `v1/ml/orgAggregatorList` for the Request
Details **Organizations** tab, and reaches this function by direct
`lambda.invoke` rather than through API Gateway:

```python
# saayam-for-all/data : data-engineering/src/saayam-org-aggregator/helpers.py
response = lambda_client.invoke(
    FunctionName="More_Org_GenAI_Py_v3126",
    Payload=json.dumps({"subject": ..., "description": ..., "location": ...}),
)
orgs = pd.DataFrame(json.loads(response["Payload"].read())["body"]["organizations"])
```

Two things follow, and both are pinned by `test_org_search_contract.py`:

* `body` **must stay a JSON object**, not a string. Serialising it breaks the
  Organizations tab from a different repository (this is what PR #165 would
  have done before PR #166 reverted it).
* The field names below are a **contract**, not an implementation detail.
  Renaming or dropping one is a cross-team change. See issue #170.

#### request Payload
```json
{
  "subject": "shelter",
  "description": "i am on the streets now i dont have a place to stay please help",
  "location": "San Jose, CA",
  "category": "Housing"
}
```

`subject` and `location` are optional — `location` defaults to
`"United States"`. `category` is optional and, when the aggregator passes the
one it already resolved for its database half, seeds the `causes` field.

#### Response
```json
{
  "organizations": [
    {
      "organization_name": "Second Harvest Food Bank",
      "org_type": "nonprofit",
      "size": "large",
      "rating": 4.8,
      "location": "San Jose, CA",
      "contact": "+1-408-555-0100",
      "email": "info@example.org",
      "source": "https://www.charitynavigator.org/example",
      "web_url": "https://example.org",
      "mission": "...",
      "description": "...",
      "relevance": "...",
      "causes": "Food Security"
    }
  ]
}
```

Every field in `utils.search_orgs.ORGANIZATION_FIELDS` is present on every row,
even when the model omits it, so a caller building a DataFrame never gets a
ragged frame. `rating` is always a float clamped to 0.0–5.0 with one decimal
(a 0–100 source score is divided by 20); `size` is `small`/`medium`/`large` or
empty; `org_type` is `nonprofit`/`for-profit` or empty.

| Status | Meaning |
|---|---|
| 200 | Organizations found |
| 400 | `description` missing |
| 502 | `ORG_SEARCH_UNAVAILABLE` — every model provider failed |

The search tries **Groq first, then Gemini**. A single-provider outage no
longer takes the Organizations tab down. `organizations` is present as `[]`
even on the error responses, so a caller that reads it before checking the
status gets an empty list rather than a `KeyError`.

#### This endpoint is the GenAI half of `orgAggregatorList`

The data team's `saayam-org-aggregator` Lambda invokes this function directly
behind `v1/ml/orgAggregatorList` and reads `payload["body"]["organizations"]`.
That makes the envelope and the field names a **contract**, not an
implementation detail. Two consequences:

- The body stays a JSON **object**. This method is on **non-proxy**
  integration, so API Gateway returns the structure as-is and the caller reads
  `body.organizations` directly. Serialising the body to a string here would
  turn every one of those reads into `undefined`.
- The 13 names in `utils.search_orgs.ORGANIZATION_FIELDS` are fixed. Renaming
  or dropping one silently breaks a consumer in a different repository, so
  `test_org_search_contract.py` pins them.

This answers open question **D15** in the BRD for
[issue #170](https://github.com/saayam-for-all/ai/issues/170): the Lambda GenAI
owes for `orgAggregatorList` is this one, `search_orgs`.

The service is reachable under `search_orgs`, `search_org` and
`find_nonprofits`.

#### Normalisation rules and their edges

Model output is prose, so every row is coerced before it leaves:

| Field | Rule |
| --- | --- |
| `rating` | Float clamped to `0.0`–`5.0`, one decimal. A value above `5` is read as a 0–100 score and divided by 20. Anything unparseable becomes `0.0`. |
| `size` | `small` / `medium` / `large`, else empty. |
| `org_type` | `nonprofit` / `for-profit`, else empty. |
| `location` | Falls back to the request's `location` when the model omits it. |
| `causes` | Seeded from the request's `category` when the model omits it. |
| all others | Present as `""` rather than absent. |

**Known edge:** because any rating above `5` is treated as a 0–100 score, a
model that answers on a 0–10 scale has `7.5` rewritten to `0.4`. Ratings are
only as trustworthy as the source the model cites, and no caller should rank
organizations on this field alone.

#### Regression tests covering this service

| File | Proves |
| --- | --- |
| `test_org_search_contract.py` | The body is an object; all 13 field names are present on every row even when the model returns a ragged one; the Groq to Gemini fallback; and that a total outage returns `502` with `ORG_SEARCH_UNAVAILABLE` and `organizations: []` rather than a silent empty `200`. |

#### curl Command
```bash
curl -X POST https://<api-gateway-url>/more-organizations \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "shelter",
    "description": "i am on the streets now i dont have a place to stay please help",
    "location": "San Jose, CA"
  }'
```

---

## Testing

The suite is hermetic: no API keys, no AWS credentials, and no network access.

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

A clean run is **63 tests** in about a second. Run one slice with a marker —
`python -m pytest -m contract` is the one to start from for any web-client bug
report, because contract tests mirror what the browser actually sees.

| Marker | Scope |
| --- | --- |
| `unit` | One function, collaborators mocked, no I/O. |
| `contract` | The Lambda event in, the JSON envelope out. |
| `dataset` | The shipped data files, such as `services/emergency_numbers.json`. |
| `integration` | Several modules together, still hermetic. Routing and blast radius. |
| `needs_network` | Hits a live service. **Excluded from the default run and from CI.** |

`tests/conftest.py` fails any unmarked test that opens a URL, so the suite
cannot start depending on a third party's uptime by accident.

| Document | What it is for |
| --- | --- |
| [`docs/testing/QA_RUNBOOK.md`](docs/testing/QA_RUNBOOK.md) | Run the suite and interpret the result with no prior context. |
| [`docs/testing/TEST_CATALOGUE.md`](docs/testing/TEST_CATALOGUE.md) | What each test protects. Generated by `tools/gen_test_catalogue.py`. |
| [`docs/testing/COVERAGE.md`](docs/testing/COVERAGE.md) | Current coverage, the CI threshold, and what is deliberately uncovered. |
| [`docs/testing/REGRESSION_AUDIT.md`](docs/testing/REGRESSION_AUDIT.md) | Per-issue: the defect, the fix, the covering tests, the residual risk. |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed and the behaviour difference a tester can observe. |

Every pull request into `dev` runs the full suite and the coverage gate. Build
and deploy are skipped on pull requests, so a PR never touches AWS.

---

## CI/CD GitHub Actions Deployment

Any push to the `dev` branch triggers the multi-job parallel deploy workflow defined in `.github/workflows/deploy_aws_lambda.yml`. 

To ensure successful deployments, define the respective AWS credentials (`*_ACCESS_KEY`, `*_SECRET_KEY`, and `*_LAMBDA_ARN`) as repository action secrets in GitHub.
