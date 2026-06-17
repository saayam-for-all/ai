import json

from utils.categories import help_categories
from utils.generate_answer_service import generate_ai_answer
from utils.request_db import get_request_full_details


def _parse_event_body(event: dict) -> dict:
    raw_body = event.get("body")
    if isinstance(raw_body, str):
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw_body, dict):
        merged = dict(event)
        merged.update(raw_body)
        return merged
    return event if isinstance(event, dict) else {}


def _first_non_empty(body: dict, *keys: str) -> str:
    for key in keys:
        value = body.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
    return ""


def _format_additional_info(data: dict) -> str:
    details = data.get("additional_info") or []
    if not isinstance(details, list):
        return ""
    lines = []
    for item in details:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        answers = item.get("answers")
        if not question or not isinstance(answers, list):
            continue
        cleaned = [str(a) for a in answers if a not in (None, "")]
        if cleaned:
            lines.append(f"- {question}: {', '.join(cleaned)}")
    return "\n".join(lines)


def lambda_handler(event, context):
    try:
        if isinstance(event, dict):
            method = (
                event.get("httpMethod")
                or event.get("requestContext", {})
                .get("http", {})
                .get("method")
            )
            if method == "OPTIONS":
                return _response(200, {})

        body = _parse_event_body(event)

        category_id = _first_non_empty(body, "category_id", "category")
        subject = _first_non_empty(body, "subject")
        description = _first_non_empty(body, "description", "question")
        location = _first_non_empty(body, "location")
        gender = _first_non_empty(body, "gender")
        age = _first_non_empty(body, "age")

        user_id = _first_non_empty(body, "user_id", "req_user_id")
        req_id = _first_non_empty(body, "req_id", "request_id", "id")
        conversation_history = body.get("conversation_history")

        if user_id and req_id and (not category_id or not subject or not description):
            data = get_request_full_details(str(user_id), str(req_id))
            if err := data.get("error"):
                return _response(
                    400,
                    {
                        "error": (
                            "category/category_id, subject, and description/question are required. "
                            f"DB lookup error: {err}"
                        )
                    },
                )

            category_id = category_id or str(data.get("req_cat_id") or "")
            subject = subject or str(data.get("req_subj") or "")
            description = description or str(data.get("req_desc") or "")
            location = location or _first_non_empty(data, "req_loc")

            if description:
                context = _format_additional_info(data)
                if context:
                    description = f"{description}\n\nAdditional details:\n{context}"

        if not category_id or not subject or not description:
            return _response(
                400,
                {"error": "category/category_id, subject, and description/question are required"},
            )

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

        # UI reads `body.answer`; keep top-level `answer` for compatibility.
        return _response(200, {"answer": answer, "body": {"answer": answer}})

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Methods": "GET, OPTIONS, POST",
        },
        "body": body,
    }
