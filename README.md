# AI Category Classifier (AWS Lambda)

This service is a serverless application designed to classify user support requests into a specific taxonomy using LLMs. It features a primary classification path via **Groq (Llama-3.1)** and a fallback to **Gemini-2.0-flash**.

---

## Project Overview

The application accepts a `description` and an optional `subject`. If the subject is missing, the system uses AI to generate a concise subject line (max 70 characters). It then predicts the most relevant category from a predefined taxonomy including Food, Clothing, Housing, Education, Healthcare, and Elderly support.

### Core Files

- `lambda_function.py` – Lambda entry point handling request/response formatting  
- `services/classification_service.py` – Zero-shot classification logic with Groq → Gemini fallback  
- `utils/client.py` – Groq and Gemini client initialization via environment variables  
- `utils/categories_with_description.py` – Defines the category taxonomy  
- `requirements.txt` – Python dependencies (`groq`, `google-genai`, `python-dotenv`)  

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
```

---

## 4. API Gateway Integration (HTTP API)

1. Create an **API Gateway HTTP API**
2. Add route: `POST /classify`
3. Integrate the route with this Lambda
4. Deploy and copy the Invoke URL

---

## 🧪 Testing (Postman / Curl)

### Request

```json
{
  "description": "I need help finding a local food bank because I'm short on groceries this week."
}
```

### Response

```json
{
  "category": "FOOD_ASSISTANCE"
}
```

---

## Notes

- Docker is used **only** for building the Lambda layer  
- The Lambda function itself is deployed as a ZIP  
- API Gateway automatically wraps requests into `event.body`