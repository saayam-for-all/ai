import json
from utils.subject_generator import generate_subject_from_description
from services.classification_service import predict_categories
from utils.categories import help_categories
from utils.generate_answer_service import generate_ai_answer
from utils.request_db import get_request_full_details
from services.emergency import get_emergency_services
from utils.search_orgs import find_organizations

# -------------------------------------------------------------
# Common Utility Helpers
# -------------------------------------------------------------

def _parse_event_body(event: dict) -> dict:
    """Parse event body from different input formats"""
    raw_body = event.get("body")
    if isinstance(raw_body, str):
        return json.loads(raw_body)
    if isinstance(raw_body, dict):
        return raw_body
    return event


def get_client_ip(event):
    """Extract client IP from request event headers/context"""
    try:
        return event["requestContext"]["http"]["sourceIp"]
    except (KeyError, TypeError):
        pass
    try:
        return event["requestContext"]["identity"]["sourceIp"]
    except (KeyError, TypeError):
        pass
    headers = event.get("headers") or {}
    xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return None


def _parse_params(event):
    """Combine queryStringParameters and body parameter values"""
    params = dict(event.get("queryStringParameters") or {})
    body = event.get("body")
    if body and str(body).strip():
        try:
            params.update(json.loads(body))
        except (json.JSONDecodeError, TypeError):
            pass
    return params


def _response(status_code, body):
    """Format Lambda response as API Gateway compatible JSON payload"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        # The web client reads response.body.<field> directly, for example
        # body.categories and body.subject. These methods use non proxy
        # integration, so API Gateway returns this structure to the client as
        # is. Serialising body here turns it into a string and every one of
        # those reads becomes undefined.
        "body": body,
    }


# -------------------------------------------------------------
# Dedicated AWS Lambda Entry Point Handlers
# -------------------------------------------------------------

# 1. Predict Category
def predict_category_handler(event, context):
    """AWS Lambda entry point for predict_category service"""
    try:
        raw_body = event.get("body")
        if raw_body is None:
            # Scenario: No 'body' key exists at all. The event IS the data.
            body = event
        elif isinstance(raw_body, str):
            # Scenario: 'body' exists and is a stringified JSON
            body = json.loads(raw_body)
        else:
            # Scenario: 'body' exists and is already a dictionary
            body = raw_body

        # Handle API Gateway variations
        if isinstance(body, str):
            body = json.loads(body)

        description = body.get("description")

        if not description:
            return _response(400, {"error": "Description is required"})

        ranked_categories, token_usage = predict_categories(description)

        # The client maps over body.categories reading category_name,
        # category_number, hierarchy and confidence, and derives its own display
        # label from category_name. Return the ranked objects unchanged.
        return _response(200, {"categories": ranked_categories, "token_usage": token_usage})

    except Exception as e:
        return _response(500, {"error": str(e)})


# 2. More Organizations (Search Orgs)
def search_orgs_handler(event, context):
    """AWS Lambda entry point for search_orgs service"""
    try:
        raw_body = event.get("body")
        if isinstance(raw_body, str):
            # API Gateway -> body is a JSON string
            body = json.loads(raw_body)
        else:
            # Direct invoke / raw JSON -> event itself is the body
            body = event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")

        if not description or not description.strip():
            return _response(400, {"error": "Description is required"})
        if not subject or not subject.strip():
            subject = ""
        if not location or not location.strip():
            location = "United States"
            print("No location provided, defaulting to United States")

        orgs = find_organizations(
            subject=subject, description=description, location=location
        )

        return _response(200, orgs)
    except Exception as e:
        return _response(500, {"error": str(e)})


# 3. Emergency Contacts
def emergency_contacts_handler(event, context):
    """AWS Lambda entry point for emergency_contacts service"""
    try:
        client_ip = get_client_ip(event)
        params = _parse_params(event)
        result = get_emergency_services(params, client_ip)
        return _response(result["status"], result["body"])
    except Exception as e:
        return _response(500, {"error": str(e)})


# 4. Generate Answer
def generate_answer_handler(event, context):
    """AWS Lambda entry point for generate_answer service"""
    try:
        body = _parse_event_body(event)
        user_id = body.get("user_id")
        req_id = body.get("req_id") or body.get("request_id")
        conversation_history = body.get("conversation_history")

        if not user_id or not req_id:
            return _response(
                400,
                {"error": "user_id and req_id (or request_id) are required"},
            )

        data = get_request_full_details(str(user_id), str(req_id))
        if err := data.get("error"):
            status = 404 if "No data found" in str(err) else 502
            return _response(status, {"error": err})

        category_id = data.get("req_cat_id")
        subject = (data.get("req_subj") or "").strip()
        description = (data.get("req_desc") or "").strip()
        location = data.get("req_loc")

        if not description:
            return _response(400, {"error": "description missing (req_desc empty)"})
        if not subject:
            return _response(400, {"error": "subject missing (req_subj empty)"})

        category = help_categories.get(str(category_id)) or "General"

        try:
            answer = generate_ai_answer(
                category=category,
                subject=subject,
                description=description,
                location=location,
                conversation_history=conversation_history,
            )
            if not answer:
                raise ValueError("Error: Empty response")
        except Exception:
            answer = "Error: Failed to generate answer"

        return _response(200, {"answer": answer})

    except Exception as e:
        return _response(500, {"error": str(e)})


# 5. Generate Subject
def generate_subject_handler(event, context):
    """AWS Lambda entry point for generate_subject service"""
    # The event carries the user's free text description and the request headers.
    # Help request descriptions routinely contain health, housing and financial
    # details, and the headers carry the caller's authorization token, so the
    # event is never logged. Log only the shape of the payload.
    print("LOG: generate_subject invoked, event keys:", sorted(event.keys()))

    try:
        raw_body = event.get("body")
        if raw_body is None:
            # Scenario: No 'body' key exists at all. The event IS the data.
            body = event
        elif isinstance(raw_body, str):
            # Scenario: 'body' exists and is a stringified JSON
            body = json.loads(raw_body)
        else:
            # Scenario: 'body' exists and is already a dictionary
            body = raw_body

        description = body.get("description")
        max_length = 70

        # Validate description
        if not description:
            return _response(400, {"error": "Description is required"})

        subject = generate_subject_from_description(
            description=description,
            max_length=max_length
        )

        return _response(200, {
            "subject": subject,
            "max_length": max_length,
            "description_length": len(description)
        })

    except Exception as e:
        return _response(500, {"error": str(e)})


# -------------------------------------------------------------
# Unified Entry Point (Fallback routing)
# -------------------------------------------------------------

def lambda_handler(event, context):
    """
    Unified Lambda handler that routes requests to appropriate service.
    Supports: predict_category, generate_subject, generate_answer, emergency_contacts, search_orgs
    """
    try:
        # Check if service is specified in query parameters or body
        q_params = event.get("queryStringParameters") or {}
        service = q_params.get("service")

        body = _parse_event_body(event)
        if not service:
            service = body.get("service", "predict_category") if isinstance(body, dict) else "predict_category"

        service = str(service).lower().strip()

        # Route to appropriate handler
        if service == "predict_category":
            return predict_category_handler(event, context)
        elif service == "generate_subject":
            return generate_subject_handler(event, context)
        elif service == "generate_answer":
            return generate_answer_handler(event, context)
        elif service == "emergency_contacts":
            return emergency_contacts_handler(event, context)
        elif service in ["search_orgs", "search_org", "find_nonprofits"]:
            return search_orgs_handler(event, context)
        else:
            return _response(400, {"error": f"Unknown service: {service}. Supported: predict_category, generate_subject, generate_answer, emergency_contacts, search_orgs"})

    except Exception as e:
        return _response(500, {"error": str(e)})
