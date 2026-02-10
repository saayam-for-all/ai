import json
from utils.generate_answer_service import generate_ai_answer
from utils.categories import help_categories


def lambda_handler(event, context):
    try:

        # Identify the body from the event
        
        body = json.loads(raw_body) if isinstance(raw_body := event.get("body"), str) else event
        
        # Alt:
        # raw_body = event.get("body")
        # if isinstance(raw_body, str):
        #    body = json.loads(raw_body) # Body is a JSON string - API Gateway
        # else:
        #    body = event # Body is a dictionary - Direct invocation

        # Extract fields from the request body
        category_id = body.get("category_id")
        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        gender = body.get("gender")
        age = body.get("age")
        conversation_history = body.get("conversation_history")

        # Required fields validation: Description, Subject, Category ID
        required = {"description": description, "subject": subject, "category_id": category_id,}
        missing = [f"{k} missing" for k, v in required.items() if not v]
        if missing:
            return _response(400, {"error": ", ".join(missing)})

        # Map category id to category
        category = help_categories.get(category_id) or "General"

        # Generate the AI answer using params
        try:
            answer = generate_ai_answer(
            category=category,
            subject=subject,
            description=description,
            location=location,
            gender=gender,
            age=age,
            conversation_history=conversation_history,
            )
            if not answer:
                raise ValueError("Error: Empty response")
        except Exception:
            answer = "Error: Failed to generate answer"


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
        "body": body,
    }