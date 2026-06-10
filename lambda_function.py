import json

from utils.categories import help_categories
from utils.generate_answer_service import generate_ai_answer
from utils.request_db import get_request_full_details


def _parse_event_body(event: dict) -> dict:
    raw_body = event.get("body")
    if isinstance(raw_body, str):
        return json.loads(raw_body)
    if isinstance(raw_body, dict):
        return raw_body
    return event


def lambda_handler(event, context):
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
        additional_info = data.get("additional_info") or []

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
                additional_info=additional_info,
                conversation_history=conversation_history,
            )
            if not answer:
                raise ValueError("Error: Empty response")
        except Exception:
            answer = "Error: Failed to generate answer"

        return _response(200, {"answer": answer})

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    payload = json.dumps(body) if isinstance(body, dict) else body
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }
