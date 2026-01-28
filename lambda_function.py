import json
from services.classification_service import predict_categories
from utils.subject_generator import generate_subject_from_description


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        
        # Handle API Gateway variations
        if isinstance(body, str):
            body = json.loads(body)

        subject = body.get("subject")
        description = body.get("description")

        if not description:
            return _response(400, {"error": "Description is required"})

        if not subject or not subject.strip():
            subject = generate_subject_from_description(description, max_length=70)

        ranked_categories = predict_categories(subject, description)

        # Return ranked categories with numbers
        return _response(200, {
            "categories": ranked_categories,
            "top_category": ranked_categories[0] if ranked_categories else None
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
        "body": json.dumps(body)
    }
