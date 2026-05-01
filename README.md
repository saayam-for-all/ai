# Generate Answer — AWS Lambda Endpoint

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Runtime](https://img.shields.io/badge/Runtime-AWS%20Lambda-orange)
![Architecture](https://img.shields.io/badge/Architecture-arm64-lightgrey)
![Primary LLM](https://img.shields.io/badge/LLM-Groq%20%7C%20Gemini-green)

A serverless AWS Lambda function that generates context-aware AI answers for user help requests on the Saayam platform. The service fetches request details from a PostgreSQL database and produces short, actionable responses using Groq (llama-3.1-8b-instant) as the primary LLM and Gemini 2.5 Flash as the fallback.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Supported Categories](#supported-categories)
5. [Prerequisites](#prerequisites)
6. [Environment Variables](#environment-variables)
7. [API Reference](#api-reference)
8. [Deployment](#deployment)
9. [Local Development and Testing](#local-development-and-testing)
10. [Design Decisions](#design-decisions)

---

## Overview

When a user submits a help request on Saayam (for example, requesting food assistance or housing support), this endpoint generates a tailored AI response for that specific request. The caller provides only the `user_id` and `req_id` — the service resolves the full request context (category, subject, description, location) from the database and uses it to build a prompt that guides the LLM toward a precise, location-aware answer.

The endpoint also supports multi-turn conversations. If the caller includes a `conversation_history`, previous exchanges are incorporated into the prompt so that follow-up questions are answered with full context.

---

## Architecture

```
Client
  |
  | POST /generate-answer
  v
API Gateway (HTTP API)
  |
  v
AWS Lambda (lambda_function.py)
  |
  |-- Fetch credentials --> AWS SSM Parameter Store
  |
  |-- Query request details --> PostgreSQL Database
  |
  |-- Map category ID --> Category name (utils/categories.py)
  |
  |-- Build system prompt --> utils/prompts.py
  |
  |-- Invoke LLM (primary) --> Groq: llama-3.1-8b-instant
  |        |
  |        |-- On failure or empty response
  |        v
  |-- Invoke LLM (fallback) --> Gemini 2.5 Flash
  |
  v
Response: { "answer": "..." }
```

**Key design choices:**

- **LangChain abstraction** — both Groq and Gemini are accessed through LangChain, making it straightforward to swap or add providers without changing the core logic.
- **Groq-first, Gemini fallback** — Groq delivers low-latency responses; Gemini acts as a reliability fallback if Groq is unavailable or returns an empty result.
- **SSM for secrets** — database credentials are never stored in environment variables or code. They are fetched at runtime from AWS Systems Manager Parameter Store with a 5-minute cache.
- **No direct question input** — the endpoint resolves the question from the database using IDs, keeping the API surface minimal and consistent with the Saayam data model.

---

## Project Structure

```
.
|-- lambda_function.py          # Lambda entry point: parses event, validates input,
|                               # orchestrates database and LLM calls, formats response
|-- requirements.txt            # Python dependencies
|-- utils/
|   |-- __init__.py             # GroqAnswerGenerationService: LangChain-based LLM
|   |                           # orchestration with Groq primary and Gemini fallback
|   |-- generate_answer_service.py  # Thin wrapper (generate_ai_answer) for backward
|   |                               # compatibility with older callers
|   |-- client.py               # Initializes groq_llm and gemini_llm from environment
|   |                           # variables using LangChain providers
|   |-- prompts.py              # 37+ category-specific system prompts;
|   |                           # get_conversational_prompt() and get_prompt() functions
|   |-- categories.py           # help_categories dict mapping numeric category IDs
|   |                           # (e.g. "1.1") to string constants (e.g. "FOOD_ASSISTANCE")
|   `-- request_db.py           # Fetches full request details from PostgreSQL using
|                               # credentials retrieved from AWS SSM Parameter Store
```

---

## Supported Categories

The service maps each request's numeric category ID to one of 37+ category constants. The LLM system prompt is selected based on this category, allowing responses to be tailored to the specific domain.

The six top-level domains are:

| Domain | Examples |
|---|---|
| Food and Essentials | Food Assistance, Grocery Shopping and Delivery, Cooking Help |
| Clothing Support | Donate Clothes, Borrow Clothes, Emergency Clothing Assistance, Tailoring |
| Housing Support | Find a Roommate, Renting Support, Moving Assistance, Home Repair Support |
| Education and Career | College Application Help, Tutoring, SOP / Essay Review |
| Healthcare and Wellness | Medical Navigation, Medicine Delivery, Mental Wellbeing Support |
| Elderly Support | Senior Living Relocation, Digital Support for Seniors, Errands and Transportation |

If the category ID does not match any known category, the service falls back to a general-purpose prompt. The complete list of category IDs and their constants is in `utils/categories.py`.

---

## Prerequisites

- Python 3.11
- Docker (required to build the Lambda layer for arm64)
- An AWS account with the following services configured:
  - AWS Lambda
  - Amazon API Gateway (HTTP API)
  - AWS Systems Manager Parameter Store
  - IAM role with permissions to read SSM parameters and write CloudWatch logs
- A Groq API key (required — primary LLM provider)
- A Gemini or Google API key (recommended — used as fallback)
- PostgreSQL database with the Saayam schema, reachable from the Lambda execution environment

---

## Environment Variables

Set the following in the Lambda function's **Configuration > Environment variables** section.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | API key for Groq. Used to call llama-3.1-8b-instant. |
| `GEMINI_API_KEY` | Recommended | — | API key for Gemini 2.5 Flash. Also accepted as `GOOGLE_API_KEY`. If absent, the Gemini fallback is disabled. |
| `AWS_REGION` | Yes (set by Lambda) | — | AWS region for SSM access. Lambda sets this automatically; set `AWS_DEFAULT_REGION` for local testing. |
| `SAAYAM_REGION` | No | `Virginia` | Logical deployment region. Accepted values: `Virginia`, `Ireland`. Used to construct the SSM parameter path. |
| `SAAYAM_GROUP` | No | `Database` | SSM parameter group. Used to construct the SSM parameter path. |
| `SAAYAM_ROLE` | No | `user` | SSM parameter role. Used to construct the SSM parameter path. |
| `SAAYAM_DB_SCHEMA` | No | `virginia_dev_saayam_rdbms` | PostgreSQL schema name used in all queries. |

**SSM Parameter Path**

Database credentials are fetched from:

```
/dev/saayam/db/{SAAYAM_REGION}/GenAI/{SAAYAM_ROLE}
```

The parameter value must be a JSON string with the following keys:

```json
{
  "HOST": "your-db-host",
  "PORT": "5432",
  "DATABASE NAME": "your-db-name",
  "USERNAME": "your-db-user",
  "PASSWORD": "your-db-password",
  "SSL": "require"
}
```

---

## API Reference

### POST /generate-answer

Generates an AI answer for an existing Saayam help request.

#### Request Body

```json
{
  "user_id": "string",
  "req_id": "string",
  "conversation_history": [
    { "role": "user", "content": "string" },
    { "role": "assistant", "content": "string" }
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | Yes | The ID of the user who submitted the request. |
| `req_id` | string | Yes | The ID of the help request to answer. Also accepted as `request_id`. |
| `conversation_history` | array | No | Prior conversation turns for multi-turn support. Each entry must have a `role` (`user` or `assistant`) and a `content` string. Entries with other roles are silently ignored. |

#### Success Response — 200

```json
{
  "answer": "The nearest food bank in your area is..."
}
```

#### Error Responses

| Status Code | Condition | Response Body |
|---|---|---|
| `400` | `user_id` or `req_id` is missing from the request body | `{"error": "user_id and req_id (or request_id) are required"}` |
| `400` | The request record in the database has an empty `req_desc` | `{"error": "description missing (req_desc empty)"}` |
| `400` | The request record in the database has an empty `req_subj` | `{"error": "subject missing (req_subj empty)"}` |
| `404` | No request found for the given `user_id` and `req_id` | `{"error": "No data found for given user_id and req_id"}` |
| `502` | The database returned an error (upstream failure) | `{"error": "<database error message>"}` |
| `500` | An unhandled exception occurred inside the Lambda | `{"error": "<exception message>"}` |

> **Note:** If both Groq and Gemini fail to produce an answer, the Lambda returns HTTP 200 with `{"answer": "Error: Failed to generate answer"}`. This is intentional — the caller always receives a well-formed response object.

---

## Deployment

### Step 1 — Build the Lambda Layer

AWS Lambda requires third-party packages to be compiled for Linux arm64. Use Docker to build the dependencies:

```bash
docker run --rm -v "$PWD":/app -w /app amazonlinux:2023 bash -c "
  dnf install -y python3.11-pip &&
  python3.11 -m pip install \
    --platform manylinux2014_aarch64 \
    --only-binary=:all: \
    -r requirements.txt -t python
"
```

Package the layer:

```bash
zip -r layer.zip python
```

### Step 2 — Package the Application Code

```bash
zip -r deploy-package.zip . -x "python/*" "layer.zip" "*.git*"
```

### Step 3 — Create the Lambda Function

In the AWS Console or via CLI:

- **Runtime:** Python 3.11
- **Architecture:** arm64
- **Handler:** `lambda_function.lambda_handler`
- **Execution role:** Must have `ssm:GetParameter` and `logs:CreateLogGroup` / `logs:PutLogEvents` permissions

Upload `deploy-package.zip` under **Code > Upload from .zip file**.

### Step 4 — Create and Attach the Lambda Layer

1. In the AWS Console, go to **Lambda > Layers > Create layer**.
2. Upload `layer.zip`, select **arm64** as the compatible architecture, and choose **Python 3.11** as the compatible runtime.
3. Attach the layer to your Lambda function under **Configuration > Layers**.

### Step 5 — Set Environment Variables

In **Configuration > Environment variables**, add all variables listed in the [Environment Variables](#environment-variables) section.

### Step 6 — Configure API Gateway

1. Create an **HTTP API** in Amazon API Gateway.
2. Add a route: `POST /generate-answer`.
3. Integrate the route with your Lambda function.
4. Deploy the API to a stage and copy the Invoke URL.

---

## Local Development and Testing

### Setup

1. Clone the repository and check out the branch:

```bash
git clone https://github.com/saayam-for-all/ai.git
cd ai
git checkout feature/ujjwal-generate-groq-gemini-answer
```

2. Create a virtual environment and install dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file in the project root (loaded automatically via `python-dotenv`):

```env
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
AWS_DEFAULT_REGION=us-east-1
SAAYAM_REGION=Virginia
SAAYAM_DB_SCHEMA=virginia_dev_saayam_rdbms
```

4. Configure AWS credentials for SSM access:

```bash
aws configure
```

### Invoke the Lambda Handler Directly

```python
from lambda_function import lambda_handler

event = {
    "body": {
        "user_id": "user-123",
        "req_id": "req-456"
    }
}

result = lambda_handler(event, None)
print(result)
```

### Test with curl (after deployment)

**Single-turn request:**

```bash
curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/generate-answer \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "req_id": "req-456"
  }'
```

**Multi-turn request with conversation history:**

```bash
curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/generate-answer \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "req_id": "req-456",
    "conversation_history": [
      { "role": "user", "content": "Where is the nearest food bank?" },
      { "role": "assistant", "content": "The nearest food bank is at 123 Main St, open weekdays 9am-5pm." }
    ]
  }'
```

**Expected response:**

```json
{
  "answer": "Based on your location and request, here are the steps to access food assistance..."
}
```

---

## Design Decisions

**LangChain as the LLM abstraction layer**
Both Groq and Gemini are accessed through LangChain's provider integrations. This ensures a uniform interface for message formatting, invocation, and response parsing regardless of the underlying provider.

**Groq primary, Gemini fallback**
Groq's llama-3.1-8b-instant is selected for its low latency and cost efficiency. Gemini 2.5 Flash is used as a silent fallback — if Groq returns an empty response or raises an exception, the service retries with Gemini transparently.

**Request resolution by ID, not by direct input**
The caller provides `user_id` and `req_id` rather than the question text directly. This ensures answers are always generated against the canonical request data stored in the database, preventing prompt injection through client-supplied text and keeping the API surface minimal.

**Conversation history for multi-turn support**
Prior turns are injected into the LangChain message chain between the system prompt and the current user message. Only `user` and `assistant` roles are accepted; any other role is silently dropped during normalization in `GroqAnswerGenerationService._normalize_history()`.

**SSM-backed database credentials**
Database connection details are never stored in environment variables or source code. They are fetched from AWS SSM Parameter Store at invocation time (with a 5-minute in-memory cache via `aws-lambda-powertools`), reducing the blast radius of a credential leak.

**Soft failure on LLM errors**
If both LLM providers fail, the Lambda returns HTTP 200 with `{"answer": "Error: Failed to generate answer"}` rather than a 500. This prevents upstream callers from treating a transient LLM outage as a hard service failure, and keeps the response schema consistent.