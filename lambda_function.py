import json
from utils.subject_generator import generate_subject_from_description
from services.classification_service import predict_categories
from utils.categories import help_categories
from utils.generate_answer_service import generate_ai_answer
from utils.request_db import get_request_full_details


def _parse_event_body(event: dict) -> dict:
    """Parse event body from different input formats"""
    raw_body = event.get("body")
    if isinstance(raw_body, str):
        return json.loads(raw_body)
    if isinstance(raw_body, dict):
        return raw_body
    return event


def lambda_handler(event, context):
    """
    Unified Lambda handler that routes requests to appropriate service.
    Supports: predict_category, generate_subject, generate_answer, emergency_contacts
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
            return _handle_predict_category(body, context)
        elif service == "generate_subject":
            return _handle_generate_subject(body, context)
        elif service == "generate_answer":
            return _handle_generate_answer(body, context)
        elif service == "emergency_contacts":
            return _handle_emergency_contacts(event, body, context)
        else:
            return _response(400, {"error": f"Unknown service: {service}. Supported: predict_category, generate_subject, generate_answer, emergency_contacts"})

    except Exception as e:
        return _response(500, {"error": str(e)})


def _handle_predict_category(body, context):
    """Handle category prediction service"""
    try:
        description = body.get("description")

        if not description:
            return _response(400, {"error": "description is required"})

        ranked_categories, token_usage = predict_categories(description)

        return _response(200, {
            "service": "predict_category",
            "categories": ranked_categories,
            "token_usage": token_usage
        })

    except Exception as e:
        return _response(500, {"error": f"Category prediction failed: {str(e)}"})


def _handle_generate_subject(body, context):
    """Handle subject generation service"""
    try:
        description = body.get("description")
        max_length = body.get("max_length", 70)

        if not description:
            return _response(400, {"error": "description is required"})

        subject = generate_subject_from_description(
            description=description,
            max_length=max_length
        )

        return _response(200, {
            "service": "generate_subject",
            "subject": subject,
            "max_length": max_length,
            "description_length": len(description)
        })

    except Exception as e:
        return _response(500, {"error": f"Subject generation failed: {str(e)}"})


def _handle_generate_answer(body, context):
    """Handle answer generation service"""
    try:
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
                raise ValueError("Empty response")
        except Exception as e:
            answer = f"Error: Failed to generate answer - {str(e)}"

        return _response(200, {
            "service": "generate_answer",
            "answer": answer,
            "category": category,
            "user_id": user_id,
            "request_id": req_id
        })

    except Exception as e:
        return _response(500, {"error": f"Answer generation failed: {str(e)}"})


def _handle_emergency_contacts(event, body, context):
    """Handle emergency contacts retrieval service"""
    try:
        from services.emergency import get_emergency_services

        client_ip = _get_client_ip(event)

        # Combine queryStringParameters and body params
        params = dict(event.get("queryStringParameters") or {})
        if isinstance(body, dict):
            # Exclude structural API Gateway event fields if body is the event itself
            if body is event:
                for key in ["lat", "lng", "zip", "city", "state", "country", "service", "language"]:
                    if key in body:
                        params[key] = body[key]
            else:
                params.update(body)

        result = get_emergency_services(params, client_ip)
        return _response(result["status"], result["body"])

    except Exception as e:
        return _response(500, {"error": f"Emergency contacts service failed: {str(e)}"})


def _get_client_ip(event):
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


def _response(status_code, body):
    """Format Lambda response"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }
