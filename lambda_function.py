import json
from utils.generate_answer_service import generate_answer


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))

        subject = body.get("subject")
        description = body.get("description")
        category = body.get("category")

        if not description or not subject or not category:
            return _response(400, {"error": "Description, subject, and category are required"})

        answer = generate_answer(category, subject, description) or "Error: Failed to generate answer"

        return _response(200, {"answer": answer})

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }
