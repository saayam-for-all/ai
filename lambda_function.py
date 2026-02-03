import json
from utils.subject_generator import generate_subject_from_description

# Generate Subject from description
def generate_subject_handler(event, context):
    print("DEBUG EVENT:", json.dumps(event))
    
    try:
        body = json.loads(event.get("body", "{}"))

        description = body.get("description")
        #max_length = body.get("max_length", 70)
        max_length = 70

        # Validate description
        if not description:
            return _response(400, {"error": "Description is required"})

        # Validate max_length
        # try:
        #     max_length = int(max_length)
        #     if max_length < 1 or max_length > 200:
        #         return _response(400, {"error": "max_length must be between 1 and 200"})
        # except (ValueError, TypeError):
        #     return _response(400, {"error": "max_length must be a valid integer"})

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
        "body": json.dumps(body)
    }
