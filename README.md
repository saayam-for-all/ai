# Saayam Universal Search — GenAI Backend

Flask-based backend for the Saayam platform's universal search feature. Handles **Confident Search** (exact ID matching with auto-redirect) as part of a hybrid search system.

## How It Works

```
User types in search bar
        ↓
GET /api/search?q=<query>
        ↓
Phase 1 — Confident Search (this repo)
  Exact ID match found → auto_navigate: true → frontend redirects
  No match → fall through
        ↓
Phase 2 — Fuzzy Search (DB team: pg_trgm)
  Returns ranked similarity results
```

## Supported ID Formats

| Entity       | Format Example          | Redirects To          |
|--------------|-------------------------|-----------------------|
| User         | `SID-00-000-000-058`    | `/users/<id>`         |
| Help Request | `REQ-00-000-000-0018`   | `/help-requests/<id>` |
| Category     | `1`, `1.1`, `0.0.0.0.0` | `/categories/<id>`   |
| Email        | `user@example.com`      | `/users/<id>`         |

## API

### `GET /api/search?q=<query>`

**Query Parameters:**
- `q` — search query (2–200 characters, required)
- `page` — page number (default: 1)
- `limit` — results per page (default: 10, max: 20)

**Response — Exact match (auto-redirect):**
```json
{
  "success": true,
  "message": "Exact match found",
  "query": "SID-00-000-000-058",
  "auto_navigate": true,
  "target": {
    "entity_type": "user",
    "entity_id": "SID-00-000-000-058",
    "title": "John Doe",
    "subtitle": "Email: john@example.com",
    "score": 100,
    "url": "/users/SID-00-000-000-058",
    "match_type": "confident"
  },
  "results": [...]
}
```

**Response — No exact match (fuzzy results):**
```json
{
  "success": true,
  "message": "Search completed",
  "query": "Arun",
  "auto_navigate": false,
  "target": null,
  "results": []
}
```

## Setup

### 1. Clone and create virtual environment
```bash
git clone https://github.com/saayam-for-all/ai.git
cd ai
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Mac/Linux
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set environment variables
```bash
# Windows PowerShell
$env:DATABASE_URL = "postgresql+psycopg2://<user>:<password>@<host>:5432/virginia_dev_saayam_rdbms?sslmode=require"
$env:FLASK_ENV = "development"
$env:FLASK_APP = "app"
```

### 4. Run locally
```bash
flask run
```

Test it:
```
http://127.0.0.1:5000/api/search?q=SID-00-000-000-058
```

## Running Tests
```bash
python test_confident_search.py
```
Expected: 13/13 passed.

## Project Structure

```
ai/
├── app/
│   ├── __init__.py                          # App factory
│   ├── auth/current_user.py                 # Auth context
│   ├── extensions.py                        # SQLAlchemy instance
│   ├── models/                              # DB models (virginia_dev_saayam_rdbms schema)
│   │   ├── user.py                          # users table
│   │   ├── help_request.py                  # request table
│   │   ├── organization.py                  # organizations table
│   │   ├── category.py                      # help_categories table
│   │   └── company.py                       # companies table (no data yet)
│   ├── repositories/
│   │   ├── confident_search_repo.py         # Exact ID matching (GenAI team)
│   │   ├── user_search_repo.py              # Fuzzy stub (DB team)
│   │   ├── help_request_search_repo.py      # Fuzzy stub (DB team)
│   │   ├── organization_search_repo.py      # Fuzzy stub (DB team)
│   │   └── category_search_repo.py          # Fuzzy stub (DB team)
│   ├── routes/search.py                     # GET /api/search
│   ├── services/universal_search_service.py # Orchestrates Phase 1 + Phase 2
│   └── utils/search_utils.py                # Helpers
├── lambda_handler.py                        # AWS Lambda entry point
├── config.py                                # Reads DATABASE_URL from env
├── requirements.txt
└── test_confident_search.py                 # Integration tests
```

## AWS Lambda Deployment

**Handler:** `lambda_handler.handler`
**Runtime:** Python 3.13
**Required environment variable:**
```
DATABASE_URL = postgresql+psycopg2://<user>:<password>@<host>:5432/virginia_dev_saayam_rdbms?sslmode=require
```

## Team Split

| Team    | Responsibility                                      |
|---------|-----------------------------------------------------|
| GenAI   | Confident search (this repo) — done                 |
| DB      | Fuzzy search repos (pg_trgm) — stubs ready for them |
| DevOps  | Lambda deployment + API Gateway URL                 |
| Frontend| Calls `/api/search?q=<query>`, reads `auto_navigate`|
