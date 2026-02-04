import json
from services.classification_service import predict_categories


def lambda_handler(event, context):
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

        ranked_categories = predict_categories(description)

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
