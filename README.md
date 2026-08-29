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
Generates structured context-aware responses to user help requests based on database records.

#### request Payload
```json
{
  "user_id": "SID-00-000-02-356",
  "req_id": "REQ-00-000-000-0377",
  "conversation_history": []
}
```

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
