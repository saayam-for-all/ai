<!--# This is a lambda function for the issue #76 more organizations

### deployed  using git workflows on saayam aws lambda with secrets set at repo level-->
# AI More Organization Endpoint Documentation

---

## Overview

The **AI More Organization Endpoint** is a serverless API built on AWS Lambda that helps users discover **reputable nonprofit organizations** based on their needs.

It takes a user’s situation (description), optional subject, and location, and returns a **structured list of verified nonprofits** that can provide relevant support.

### Why this API?

Many users in urgent or uncertain situations struggle to find:
- trustworthy organizations  
- location specific help  
- verified contact information  

This API solves that by using an AI model to:
- filter **reliable nonprofit sources**
- tailor results to **user needs + location**
- return **clean, structured data** ready for applications

---

## Key Features

- Finds **2–3 relevant nonprofit organizations**
- Location aware recommendations
- Focus on **verified and trustworthy sources**
- Structured JSON output (easy to consume)
- Serverless (AWS Lambda)
- Powered by **LLM (Groq + LangChain)**

---

## What the API Does

### Input
- subject
- description (User need)
- Location

### Output
A structured JSON response containing:
- Organization name
- Location
- Contact
- Email
- Source verification link
- Website
- Mission summary
- Description
- Relevance to request

---

## Endpoint Details

### Endpoint
POST /find-nonprofits

### Headers
Content-Type: application/json

---

## Request Parameters

| Field        | Type   | Required | Description |
|-------------|--------|----------|-------------|
| description | string |    Yes   | User’s situation or need |
| subject     | string |    Yes    | Category (e.g., shelter, food, legal help) |
| location    | string |    Yes    | City, address, or region |

---

## Example Request

```json
{
  "subject": "shelter",
  "description": "i am on the streets now i dont have a place to stay please help",
  "location": "tampa"
}
```

---

## Example Response

```json
{
  "organizations": [
    {
      "organization_name": "The Salvation Army Tampa",
      "location": "Tampa, FL",
      "contact": "(813) 287-0800",
      "email": "tampa@salvationarmy.org",
      "source": "https://www.salvationarmy.org/usn/salvation-army-tampa",
      "web_url": "https://www.salvationarmy.org/usn/salvation-army-tampa",
      "mission": "The Salvation Army, an international movement, is an evangelical part of the universal Christian church. It is an organization that accepts all people regardless of their background or beliefs. The Salvation Army's mission is to meet human needs.",
      "description": "The Salvation Army provides shelter, food, and other essential services to people in need. They operate a variety of programs, including emergency shelters, food banks, and rehabilitation centers.",
      "relevance": "The Salvation Army Tampa provides emergency shelter and services to people in need, making it a relevant organization for someone looking for a place to stay. Their shelter services include emergency housing, food, and clothing. They also offer counseling and case management to help individuals get back on their feet."
    },
    {
      "organization_name": "Catholic Charities Diocese of Tampa",
      "location": "Tampa, FL",
      "contact": "(813) 223-0800",
      "email": "info@catholiccharitiestampa.org",
      "source": "https://www.catholiccharitiestampa.org/",
      "web_url": "https://www.catholiccharitiestampa.org/",
      "mission": "Catholic Charities is a ministry of the Diocese of Tampa that provides a range of social services to those in need. Our mission is to serve the poor and vulnerable in our community.",
      "description": "Catholic Charities provides a range of services, including emergency shelter, food assistance, and housing support. They also offer counseling, job training, and other forms of support to help individuals achieve stability and independence.",
      "relevance": "Catholic Charities Diocese of Tampa provides emergency shelter and supportive services to people in need, making it a relevant organization for someone looking for a place to stay. Their shelter services include emergency housing, food, and clothing. They also offer counseling and case management to help individuals get back on their feet."
    },
    {
      "organization_name": "Hillsborough County Coalition for the Homeless",
      "location": "Tampa, FL",
      "contact": "(813) 299-1515",
      "email": "info@hccf.org",
      "source": "https://www.hccf.org/",
      "web_url": "https://www.hccf.org/",
      "mission": "The Hillsborough County Coalition for the Homeless is a nonprofit organization that works to prevent and end homelessness in Hillsborough County. Our mission is to provide a comprehensive range of services to people experiencing homelessness.",
      "description": "The Hillsborough County Coalition for the Homeless provides a range of services, including emergency shelter, housing support, and job training. They also offer counseling, health services, and other forms of support to help individuals achieve stability and independence.",
      "relevance": "The Hillsborough County Coalition for the Homeless provides emergency shelter and supportive services to people experiencing homelessness, making it a relevant organization for someone looking for a place to stay. Their shelter services include emergency housing, food, and clothing. They also offer counseling and case management to help individuals get back on their feet."
    }
  ]
}
```

---

## Installation & Setup

### Prerequisites
- Python 3.12+
- AWS account (for deployment)
- Groq API key

---

### 1. Clone the Repository
```bash
git clone <repo-url>
cd ai
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Variables

Create a `.env` file:

```env
GROQ_API_KEY=your_api_key_here
```

---

## Deployment (GitHub Actions)

Deployment is automated using GitHub Actions when pushing to:

more-org-aws-lambda

### Required Secrets

- MORE_ORG_AWS_ACCESS_KEY_ID
- MORE_ORG_AWS_SECRET_ACCESS_KEY
- MORE_ORG_AWS_REGION
- MORE_ORG_LAMBDA_ARN

---

## Project Structure

```text
ai/
├── .github/workflows/
│   └── deploy_aws_lambda.yml
├── services/
│   └── search_orgs.py
├── lambda_function.py
├── requirements.txt
├── README.md
└── .gitignore
```

---

## File Overview

### lambda_function.py
- Entry point for AWS Lambda
- Parses request
- Validates inputs
- Calls nonprofit search service
- Returns response with CORS support

---

### services/search_orgs.py
- Core logic of the application
- Defines structured schema (Pydantic)
- Builds prompt for AI model
- Calls Groq LLM via LangChain
- Parses response into JSON format

---

### deploy_aws_lambda.yml
- CI/CD pipeline
- Installs dependencies
- Packages code
- Deploys to AWS Lambda

---

### requirements.txt
- Lists all Python dependencies

---

## Tech Stack

- Python
- AWS Lambda
- LangChain
- Groq (LLM)
- GitHub Actions

---

## How It Works (High-Level)

1. Client sends request → Lambda
2. Lambda validates input
3. Prompt is created using user data
4. LLM (Groq) generates nonprofit recommendations
5. Response is parsed into structured JSON
6. Lambda returns result to client

### Flow

Client → API Gateway → Lambda → LLM → Structured JSON → Client

---

## Notes

- Results depend on LLM output and available public data
- API prioritizes trusted and verified organizations
- Designed for integration into applications needing real-world assistance data

---

## Summary

This API provides a simple, scalable way to connect users with relevant nonprofit organizations using AI. It transforms unstructured user needs into actionable, verified resources in a clean and developer-friendly format.
