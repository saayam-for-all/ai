import json
from services.search_orgs import find_nonprofits

def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        if isinstance(raw_body, str):
            # API Gateway → body is a JSON string
            body = json.loads(raw_body)
        else:
            # Direct invoke / raw JSON → event itself is the body
            body = event
        subject = body.get("subject")
        description = body.get("description")
        location=body.get("location")

        if not description or not description.strip():
            return _response(400, {"error": "Description is required"})

        if not subject or not subject.strip():
            subject = ""

        if not location or not location.strip():
            location="United States"
            print("No location provided, defaulting to United States")
            
        orgs=find_nonprofits(subject=subject,description=description,location=location)
        
        return _response(200,orgs)

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