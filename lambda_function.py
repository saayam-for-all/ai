import json
from utils.subject_generator import generate_subject_from_description
from services.classification_service import predict_categories


def lambda_handler(event, context):
    """Main classification handler"""
    try:
        raw_body = event.get("body")
        if raw_body is None:
            body = event
        elif isinstance(raw_body, str):
            body = json.loads(raw_body)
        else:
            body = raw_body

        if isinstance(body, str):
            body = json.loads(body)

        description = body.get("description")

        if not description:
            return _response(400, {"error": "Description is required"})

        ranked_categories, token_usage = predict_categories(description)

        return _response(200, {"categories": ranked_categories, "token_usage": token_usage})

    except Exception as e:
        return _response(500, {"error": str(e)})


def generate_subject_handler(event, context):
    """Subject generation handler"""
    print("DEBUG EVENT:", json.dumps(event))

    try:
        raw_body = event.get("body")
        if raw_body is None:
            body = event
        elif isinstance(raw_body, str):
            body = json.loads(raw_body)
        else:
            body = raw_body

        description = body.get("description")
        max_length = 70

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


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": body
    }
