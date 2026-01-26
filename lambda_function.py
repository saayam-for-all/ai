import json
from utils.generate_answer_service import generate_ai_answer
from utils.categories import help_categories


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))

        # Extract fields from the request body
        category_code = body.get("category")
        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        gender = body.get("gender")
        age = body.get("age")
        conversation_history = body.get("conversation_history")

        # Required fields validation: Description, Subject, Category Code
        required = {"description": description, "subject": subject, "category_code": category_code,}
        missing = [f"{k} missing" for k, v in required.items() if not v]
        if missing:
            return _response(400, {"error": ", ".join(missing)})

        # Map category code to category string
        category = help_categories.get(category_code) or "General"

        # Generate the AI answer using params
        answer = generate_ai_answer(
            category=category,
            subject=subject,
            description=description,
            location=location,
            gender=gender,
            age=age,
            conversation_history=conversation_history,
        ) or "Error: Failed to generate answer"

        # Return the generated answer
        return _response(
            200,
            {"answer": answer,},
        )

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }