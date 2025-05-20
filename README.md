# Saayam GroqAPI Lambda Service Documentation

This document offers a complete overview of the Saayam GroqAPI service, detailing its purpose, architecture, and usage. It covers the project's aims and goals, completed work, code explanations, AWS access, test events, and future enhancements.

-----

## 1\. Project Aim and Goals

**Aim:** To build a serverless REST API that:

  * **Classifies** user questions into predefined categories.
  * **Generates** expert answers based on category, subject, and description.
  * **Exposes** endpoints via AWS Lambda using Flask and Serverless WSGI.

**Goals:**

  * Provide a **zero-shot text classification** endpoint (`/predict_categories`).
  * Provide a **context-aware answer generation** endpoint (`/generate_answer`).
  * Securely integrate with the **Groq LLM service**.
  * Enable easy deployment and maintenance via **AWS Lambda**.

-----

## 2\. What Has Been Done So Far

  * Defined a list of **50+ categories** spanning finance, education, health, sports, and more.
  * Implemented **two Flask routes**:
      * `/predict_categories` for category classification.
      * `/generate_answer` for answer generation.
  * Integrated the **Groq LLM client** (`llama-3.1-8b-instant`) for model inference.
  * Packaged the Flask application for AWS Lambda with **`serverless_wsgi`**.
  * Deployed the function to the `us-east-1` region under the Lambda name **`groqapi`**.

-----

## 3\. Code Explanation

```python
import os
import json
from flask import Flask, jsonify, request, make_response
from groq import Groq
import serverless_wsgi

# Initialize Flask app and Groq client
os.environ["GROQ_API_KEY"] = "*************************"
client = Groq()
app = Flask(__name__)
```

  * **`Flask`** handles routing.
  * **`Groq`** is the LLM client; the API key is set via an environment variable.
  * **`serverless_wsgi`** adapts Flask for Lambda.

### 3.1 `/predict_categories` Endpoint

```python
@app.route('/predict_categories', methods=['POST'])
def predict_categories_api():
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")

    if not subject or not description:
        return jsonify({"error": "Subject and description are required"}), 400

    try:
        predicted_categories = predict_categories(subject, description)
        response = jsonify(predicted_categories)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

  * **Validates** input.
  * Calls helper `predict_categories` to get up to three valid categories.
  * Returns a JSON array of category strings.

### 3.2 `/generate_answer` Endpoint

```python
@app.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    data = request.get_json()
    category = data.get("category")
    subject = data.get("subject")
    question = data.get("description")

    if not category or not subject or not question:
        return jsonify({"error": "Category, subject, and description are required"}), 400

    try:
        answer = chat_with_llama(category, subject, question)
        response = jsonify(answer)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

  * **Validates** category, subject, and question.
  * Uses `chat_with_llama` helper to build the prompt and fetch the answer.

### 3.3 Helper Functions

```python
def predict_categories(subject, description):
    prompt = f"""
    You are a zero-shot text classifier that classifies user input into exactly three categories from the predefined list below. Respond ONLY with a comma-separated list of categories. Do not include any additional text or explanations.

    Categories: {", ".join(categories)}

    User Input:
    Subject: {subject}
    Description: {description}

    Output (comma-separated categories):
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        top_p=0.3
    )

    raw_output = response.choices[0].message.content.strip()
    parts = [c.strip() for c in raw_output.split(",")]
    valid_categories = [c for c in parts if c in categories]
    return valid_categories[:3]
```

  * Builds a **zero-shot prompt**.
  * Parses output and filters to valid categories.

<!-- end list -->

```python
category_prompts = { ... }  # Mapping of category to role-specific system prompts

def chat_with_llama(category, subject, description):
    role_prompt = category_prompts.get(category, "You are a helpful expert from Saayam. Answer clearly.")
    full_prompt = f"{role_prompt}\n\nSubject: {subject}\nQuestion: {description}"
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": full_prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()
```

  * `category_prompts` defines **tailored role prompts** per category.
  * `chat_with_llama` constructs the final prompt and returns the LLM response.

### 3.4 AWS Lambda Handler

```python
def lambda_handler(event, context):
    if "path" in event:
        event["path"] = event["path"].replace("/dev/genai/v0.0.1", "")
    return serverless_wsgi.handle_request(app, event, context)
```

  * **Normalizes** the incoming API Gateway path.
  * **Delegates** to `serverless_wsgi` for routing.

-----

## 4\. Accessing the Code in AWS

  * **Region:** `us-east-1` (N. Virginia)
  * **Lambda Function Name:** `groqapi`
  * **Console URL:** [https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1\#/functions/groqapi?tab=code](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/groqapi?tab=code)
  * **Main File:** `app.py`

-----

## 5\. Test Events

Use these events in the AWS Lambda **Test** tab to validate behavior.

### 5.1 `predict_categories` Test

```json
{
  "resource": "/predict_categories",
  "path": "/predict_categories",
  "httpMethod": "POST",
  "headers": { "Content-Type": "application/json" },
  "body": "{\"subject\": \"Help with opening a savings account\", \"description\": \"I want to understand how to open a savings account and what documents are needed.\"}",
  "isBase64Encoded": false
}
```

### 5.2 `generate_answer` Test

```json
{
  "resource": "/generate_answer",
  "path": "/generate_answer",
  "httpMethod": "POST",
  "headers": { "Content-Type": "application/json" },
  "body": "{\"category\": \"Gardening\", \"subject\": \"Compost problem\", \"description\": \"My compost pile smells really bad. What should I do?\"}",
  "isBase64Encoded": false
}
```

-----

## 6\. Future Enhancements & To-Do

  * Move Hardcoded Configs to Separate Files
  * Add Code Comments and Documentation
  * Add Unit and Integration Test Cases
  * Improve Code Coverage
