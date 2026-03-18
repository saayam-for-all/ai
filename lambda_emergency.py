import json
from services.emergency import get_emergency_services


def get_client_ip(event):
    try:
        return event["requestContext"]["http"]["sourceIp"]
    except (KeyError, TypeError):
        pass
    try:
        return event["requestContext"]["identity"]["sourceIp"]
    except (KeyError, TypeError):
        pass
    headers = event.get("headers") or {}
    xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return None


def _parse_params(event):
    params = dict(event.get("queryStringParameters") or {})
    body = event.get("body")
    if body and str(body).strip():
        try:
            params.update(json.loads(body))
        except (json.JSONDecodeError, TypeError):
            pass
    return params


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, ensure_ascii=False)
    }


def lambda_handler(event, context):
    try:
        client_ip = get_client_ip(event)
        params = _parse_params(event)
        result = get_emergency_services(params, client_ip)
        return _response(result["status"], result["body"])
    except Exception as e:
        return _response(500, {"error": str(e)})
