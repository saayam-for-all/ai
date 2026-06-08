# Generate Answer API (AWS Lambda)

A serverless backend service that generates **context-aware, actionable AI responses** for user help requests on the Saayam platform.

This service uses:

* **Groq (Llama 3.1)** as the primary LLM (fast, low latency)
* **Gemini 2.5 Flash** as a fallback for reliability

---

## Overview

The Generate Answer API takes a **user request ID**, fetches full request details from a database, and generates a helpful response tailored to the user’s situation.

It supports context categories such as:

* Food & Essentials
* Clothing Support
* Housing Support
* Education & Career
* Healthcare & Wellness
* Elderly Support

### Key Idea

The Generate Answer Lambda Function Pipeline:

1. Receives `user_id`, `req_id`, and `conversation_history`
2. Fetches structured data from a PostgreSQL-compatible Amazon Aurora database
3. Maps the request to a category
4. Builds a category-specific prompt
5. Generates an answer using LLMs

---

## System Architecture

```
Client Request
     ↓
API Gateway (POST /generate-answer)
     ↓
AWS Lambda (lambda_function.py)
     ↓
Amazon Aurora RDS - PostgreSQL (Fetch Request Data)
     ↓
Category Mapping
     ↓
Prompt Generation
     ↓
LLM Invocation (Groq → Gemini fallback)
     ↓
Generated Answer
     ↓
API Response
```

---

## Project Structure

```
.
├── lambda_function.py             # Lambda entry point
├── requirements.txt               # Dependencies
├── utils/
│   ├── __init__.py                # Core LLM orchestration logic
│   ├── generate_answer_service.py # Wrapper for answer generation
│   ├── client.py                  # Groq & Gemini initialization
│   ├── prompts.py                 # Category-based prompt templates
│   ├── categories.py              # Category ID → name mapping
│   └── request_db.py              # PostgreSQL data fetching
├── .github/workflows/             # CI/CD deployment (optional)
```

---

## API Contract

### Endpoint

```
POST /generate-answer
```

### Request Body

```json
{
  "user_id": "string",
  "req_id": "string",
  "conversation_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

### Fields

| Field                | Required | Description                        |
| -------------------- | -------- | ---------------------------------- |
| user_id              | Yes      | ID of the user                     |
| req_id               | Yes      | ID of the help request             |
| conversation_history | No       | Previous chat messages for context |

---

### Response

```json
{
  "answer": "Based on your situation, here are some options..."
}
```

---

##  Environment Variables

Set in **Lambda → Configuration → Environment Variables**:

```env
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
```

### Required Services

* AWS Lambda
* API Gateway

---

##  Deployment

These steps are performed by GitHub Actions on successful push to the branch

### 1. Build Lambda Layer

```bash
docker run --rm -v "$PWD":/app -w /app amazonlinux:2023 bash -c "
  dnf install -y python3.11-pip &&
  python3.11 -m pip install \
    --platform manylinux2014_aarch64 \
    --only-binary=:all: \
    -r requirements.txt -t python
"
```

```bash
zip -r layer.zip python
```

---

### 2. Package Code

```bash
zip -r deploy-package.zip . -x "python/*" "layer.zip" "*.git*"
```

---

### 3. Create Lambda

* Runtime: Python 3.11
* Architecture: arm64
* Handler: `lambda_function.lambda_handler`

---

##  Design Decisions

### 1. Privacy focused ID-based request system

- Avoids exposing PII on every request
- Simplifies modification and querying on user and request data

### 2. Category-specific prompting

- Improves answer relevance by tailoring prompts to domain
- Allows for quick prompt creation adhereing to the catergory
- Enables conversation history session to focus on a single topic

<!-- ---

##  Known Gaps / Improvements

* Add **error handling standardization**
* Improve **prompt safety (avoid repetition attacks)**
* Add **rate limiting / logging**
* Include **sample database schema**
* Add **end-to-end test cases** -->

---

##  Example Request

```json
{
  "user_id": "SID-00-000-000-050",
  "req_id": "REQ-00-000-000-0085",
  "conversation_history": [
    {
      "role": "user",
      "content": "I need help finding food"
    }
  ]
}
```
