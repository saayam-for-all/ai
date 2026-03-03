# AI Support Answer Generator (AWS Lambda)

This service is a serverless application designed to generate support answers from a category taxonomy using LLMs. The generate-answer flow uses **LangChain** with **Groq (llama-3.1-8b-instant)** as primary and **Gemini (gemini-2.5-flash)** as fallback.

---

## Project Overview

The application accepts a `category_id`, `subject`, and `description` (with optional `location`, `gender`, `age`, and `conversation_history`) and returns a generated answer. Categories are mapped from a predefined taxonomy including Food, Clothing, Housing, Education, Healthcare, and Elderly support.

### Core Files

- `lambda_function.py` – Lambda entry point handling request/response formatting  
- `utils/generate_answer_service.py` – Answer generation service wrapper  
- `utils/langchain_models.py` – LangChain model layer with Groq → Gemini fallback  
- `utils/prompts.py` – Prompt construction  
- `utils/categories.py` – Category taxonomy mapping  
- `requirements.txt` – Python dependencies (`groq`, `google-genai`, `python-dotenv`, `langchain-*`)  

---

## 1. Create the Lambda Layer

AWS Lambda requires third-party libraries to be packaged in a Linux-compatible format.  
Use Docker to build dependencies for **Python 3.11 (arm64)**:

```bash
docker run --rm -v "$PWD":/app -w /app amazonlinux:2023 bash -c "
  dnf install -y python3.11-pip &&
  python3.11 -m pip install     --platform manylinux2014_aarch64     --only-binary=:all:     -r requirements.txt -t python
"
```

Package the layer:

```bash
zip -r layer.zip python
```

---

## 2. Package the Application Code

Create a deployment ZIP excluding the Lambda layer and local artifacts:

```bash
zip -r deploy-package.zip . -x "python/*" "layer.zip" "*.git*"
```

---

## 3. AWS Lambda Deployment

### Step A: Create the Lambda Function

- **Runtime:** Python 3.11  
- **Architecture:** arm64  
- **Handler:** `lambda_function.lambda_handler`

### Step B: Upload Code and Layer

1. Upload `deploy-package.zip` under **Code → Upload from .zip file**
2. Create a new Lambda Layer using `layer.zip`
3. Attach the layer to the function

### Step C: Environment Variables

Set the following in **Configuration → Environment variables**:

```env
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
# or use GOOGLE_API_KEY as an alternative for Gemini
```

---

## 4. API Gateway Integration (HTTP API)

1. Create an **API Gateway HTTP API**
2. Add route: `POST /answer`
3. Integrate the route with this Lambda
4. Deploy and copy the Invoke URL

---

## 🧪 Testing (Postman / Curl)

### Request

```json
{
  "category_id": "1.1",
  "subject": "Food help",
  "description": "I need help finding a local food bank because I'm short on groceries this week."
}
```

### Response

```json
{
  "answer": "..."
}
```

---

## Testing the generate-answer flow

### Automated tests (no API keys)

From the project root:

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Tests in `tests/test_generate_answer.py` cover message building, prompt structure, and the full `generate_ai_answer` path with the LangChain LLM mocked so they run without `GROQ_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`.

### Manual end-to-end test (with API keys)

1. Set `GROQ_API_KEY` and/or `GEMINI_API_KEY` in `.env`.
2. Invoke the handler locally:

```python
from lambda_function import lambda_handler

event = {
    "body": '{"category_id": "1.1", "subject": "Food help", "description": "Where can I find a food bank in NYC?"}'
}
result = lambda_handler(event, None)
print(result)  # statusCode 200, body {"answer": "..."}
```

3. Or call the service directly:

```python
from utils.generate_answer_service import generate_ai_answer
answer = generate_ai_answer(category="FOOD_ASSISTANCE", subject="Food help", description="Where can I find a food bank?")
print(answer)
```

---

## Notes

- Docker is used **only** for building the Lambda layer  
- The Lambda function itself is deployed as a ZIP  
- API Gateway automatically wraps requests into `event.body`
