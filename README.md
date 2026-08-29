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

---

### 5. More Organizations
Returns 6 verified organizations (3 nonprofit, 3 for-profit) close to the user's location related to their request.

#### request Payload
```json
{
  "subject": "shelter",
  "description": "i am on the streets now i dont have a place to stay please help",
  "location": "San Jose, CA"
}
```

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

## CI/CD GitHub Actions Deployment

Any push to the `dev` branch triggers the multi-job parallel deploy workflow defined in `.github/workflows/deploy_aws_lambda.yml`. 

To ensure successful deployments, define the respective AWS credentials (`*_ACCESS_KEY`, `*_SECRET_KEY`, and `*_LAMBDA_ARN`) as repository action secrets in GitHub.
