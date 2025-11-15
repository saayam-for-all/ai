import serverless_wsgi
from app import app

def lambda_handler(event, context):   

    # Extract path to determine which API is calling
    #path1 = event.get('resource', event.get('path', ''))
    #print("Received event path:", path1)
    #body = json.loads(event.get('body', '{}'))
    #print("Received event body:", body)

    if "path" in event:
        event["path"] = event["path"].replace("/dev/genai/v0.0.1", "")

    return serverless_wsgi.handle_request(app, event, context)