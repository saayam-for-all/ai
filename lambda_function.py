import json
from utils.subject_generator import generate_subject_from_description
from services.classification_service import predict_categories
from utils.categories import help_categories
from utils.generate_answer_service import generate_ai_answer
from services.emergency import get_emergency_services
from utils.search_orgs import OrganizationSearchError, find_organizations

# -------------------------------------------------------------
# Common Utility Helpers
# -------------------------------------------------------------

def _parse_event_body(event: dict) -> dict:
    """Parse event body from different input formats"""
    raw_body = event.get("body")
    if isinstance(raw_body, str):
        return json.loads(raw_body)
    if isinstance(raw_body, dict):
        return raw_body
    return event


def get_client_ip(event):
    """Extract client IP from request event headers/context"""
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


def _lookup_request(user_id, req_id):
    """Read a request row from Postgres, importing the driver lazily.

    utils.request_db imports psycopg2, a compiled C extension. Importing it at
    module scope meant that any psycopg2 problem - most obviously a wheel built
    for a different Python minor version than the function's configured runtime
    - failed the whole module and took predict_category, generate_subject,
    emergency_contacts and search_orgs down with it, before a single line of
    handler code ran. generate_answer is the only service that needs the
    database, so it is the only one that should pay for it.
    """
    from utils.request_db import get_request_full_details

    return get_request_full_details(user_id, req_id)


# The web client posts the request object it already holds, and that object
# names its fields differently from our database columns: the Request Details
# page carries `id` for the request and the logged in user's `userDBid`, while
# the ml-api aggregator speaks `beneficiary_id`. Accepting the aliases costs
# nothing and stops a working payload being rejected over a naming difference.
_USER_ID_KEYS = (
    "user_id",
    "userId",
    "req_user_id",
    "beneficiary_id",
    "beneficiaryId",
    "userDBid",
)
_REQ_ID_KEYS = ("req_id", "request_id", "requestId", "id")

# Shown to the person when the request store cannot be read and there is no
# question we can answer without it. It says what is happening and what to do,
# and it names nothing about our infrastructure.
_STORE_FAILURE_MESSAGE = (
    "We could not load the details of this request just now, so there is "
    "nothing to summarise yet. Your request itself is safe and unchanged. "
    "Please try again in a few minutes."
)


def _first_present(body, keys):
    """Return the first non empty value among keys, or None."""
    for key in keys:
        value = body.get(key)
        if value not in (None, ""):
            return value
    return None


def _last_user_question(conversation_history):
    """The most recent thing the person actually asked, or None.

    The More Information chat appends the user's new question to
    `conversation_history` and sends nothing else, so on every turn after the
    first this is the real question and the request description is background.
    """
    if not isinstance(conversation_history, list):
        return None
    for message in reversed(conversation_history):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            return content
    return None


def _describe_additional_info(additional_info):
    """Flatten the request's additional-info answers into prompt context.

    The lookup has always joined `req_add_info` and its metadata, and the
    handler has always thrown the result away - the model was answering from
    the subject and description alone while the specifics the beneficiary
    actually filled in (household size, dates, documents held) sat unused in
    the row. Everything the request store gives us should reach the model.
    """
    if not isinstance(additional_info, list):
        return ""

    lines = []
    for entry in additional_info:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        answers = entry.get("answers")
        if not question or not isinstance(answers, list):
            continue
        values = [str(a).strip() for a in answers if str(a or "").strip()]
        if values:
            lines.append(f"- {question}: {', '.join(values)}")

    return "\n".join(lines)


def _parse_params(event):
    """Combine queryStringParameters and body parameter values.

    A body that is absent, malformed, or valid JSON that is not an object (a
    bare string or list) is ignored rather than raised: the query string alone
    is enough to answer, and an emergency lookup must not 500 because of a
    stray body.
    """
    params = dict(event.get("queryStringParameters") or {})
    body = event.get("body")
    if body and str(body).strip():
        try:
            parsed = json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            params.update(parsed)
    return params


def _response(status_code, body):
    """Format Lambda response as API Gateway compatible JSON payload"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        # The web client reads response.body.<field> directly, for example
        # body.categories and body.subject. These methods use non proxy
        # integration, so API Gateway returns this structure to the client as
        # is. Serialising body here turns it into a string and every one of
        # those reads becomes undefined.
        "body": body,
    }


def _proxy_response(status_code, body):
    """Response for methods that use Lambda PROXY integration.

    Proxy integration requires body to be a string; API Gateway returns that
    string to the client as the whole response. Emergency Contacts uses proxy
    because its page sends lat/lng from browser geolocation, and proxy is the
    only integration that passes query parameters and the caller IP through to
    the function. The other GenAI methods are non proxy and use _response.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else body,
    }


# -------------------------------------------------------------
# Dedicated AWS Lambda Entry Point Handlers
# -------------------------------------------------------------

# 1. Predict Category
def predict_category_handler(event, context):
    """AWS Lambda entry point for predict_category service"""
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

        ranked_categories, token_usage = predict_categories(description)

        # The client maps over body.categories reading category_name,
        # category_number, hierarchy and confidence, and derives its own display
        # label from category_name. Return the ranked objects unchanged.
        return _response(200, {"categories": ranked_categories, "token_usage": token_usage})

    except Exception as e:
        return _response(500, {"error": str(e)})


# 2. More Organizations (Search Orgs)
def search_orgs_handler(event, context):
    """AWS Lambda entry point for search_orgs service.

    Also the AI half of the Request Details Organizations tab: the data team's
    saayam-org-aggregator invokes this function directly behind
    v1/ml/orgAggregatorList and reads payload["body"]["organizations"], which
    is why the body stays an object and the field names are a contract. See
    issue #170.
    """
    try:
        raw_body = event.get("body")
        if isinstance(raw_body, str):
            # API Gateway -> body is a JSON string
            body = json.loads(raw_body)
        else:
            # Direct invoke / raw JSON -> event itself is the body
            body = event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        # The aggregator already resolves a category for its database half.
        # When it passes one through we use it to seed the causes column.
        category = body.get("category")

        if not description or not str(description).strip():
            return _response(400, {"error": "Description is required"})
        if not subject or not str(subject).strip():
            subject = ""
        if not location or not str(location).strip():
            location = "United States"
            print("No location provided, defaulting to United States")

        orgs = find_organizations(
            subject=subject,
            description=description,
            location=location,
            category=category,
        )

        return _response(200, orgs)

    except OrganizationSearchError as e:
        # Every provider failed. The caller needs to know this is a provider
        # outage rather than a bad request, and the detail belongs in
        # CloudWatch rather than in a response the aggregator forwards.
        print(f"ERROR: organization search failed on every provider: {e}")
        return _response(
            502,
            {"error": "Organization search failed", "code": "ORG_SEARCH_UNAVAILABLE",
             "organizations": []},
        )
    except Exception as e:
        print(f"ERROR: search_orgs failed: {type(e).__name__}: {e}")
        return _response(500, {"error": "Organization search failed", "organizations": []})


# 3. Emergency Contacts
def emergency_contacts_handler(event, context):
    """AWS Lambda entry point for emergency_contacts service"""
    try:
        # Proxy integration gives us the query string and the caller IP, so a
        # call with no parameters is resolved from the IP rather than guessed.
        client_ip = get_client_ip(event)
        params = _parse_params(event)
        result = get_emergency_services(params, client_ip)
        return _proxy_response(result["status"], result["body"])
    except Exception as e:
        # This method is on PROXY integration, so the error path has to use the
        # proxy shape too. Returning an object body here made API Gateway reject
        # the response and the page saw a 502 with no diagnosis - the failure
        # mode reported in issue #146. The detail goes to CloudWatch rather than
        # to the caller.
        print(f"ERROR: emergency_contacts failed: {type(e).__name__}: {e}")
        return _proxy_response(500, {"error": "Emergency services lookup failed"})


# 4. Generate Answer
def generate_answer_handler(event, context):
    """AWS Lambda entry point for generate_answer service.

    The database is a source of the request text, not a precondition. A caller
    that already holds the subject and description - the Request Details page
    does - is answered without touching Postgres. The req_id lookup fills in
    only what the caller did not send.
    """
    # The description carries health, housing and financial detail and the
    # headers carry the caller's token, so log the shape of the payload and
    # never its content.
    try:
        body = _parse_event_body(event)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        print(f"ERROR: generate_answer could not parse the body: {type(e).__name__}")
        return _response(400, {"error": "Request body is not valid JSON"})

    if not isinstance(body, dict):
        return _response(400, {"error": "Request body must be a JSON object"})

    print("LOG: generate_answer invoked, body keys:", sorted(body.keys()))

    try:
        subject = str(body.get("subject") or "").strip()
        description = str(body.get("description") or "").strip()
        location = body.get("location")
        category = body.get("category")

        # Anything that is not a list of messages is dropped rather than passed
        # through to the model.
        conversation_history = body.get("conversation_history")
        if not isinstance(conversation_history, list):
            conversation_history = None

        user_id = _first_present(body, _USER_ID_KEYS)
        req_id = _first_present(body, _REQ_ID_KEYS)

        # The chat sends the person's newest question inside the history and
        # nothing else, so this is what they are actually waiting on an answer
        # to. It is also the one piece of context that survives a request store
        # that cannot be read.
        follow_up = _last_user_question(conversation_history)

        source = "request"
        degraded_from = None
        additional_info = ""

        if not subject or not description:
            if not user_id or not req_id:
                return _response(
                    400,
                    {
                        "error": (
                            "Provide either subject and description, or "
                            "user_id and req_id to look them up"
                        )
                    },
                )

            data = _lookup_request(str(user_id), str(req_id))
            if err := data.get("error"):
                if data.get("error_kind") == "not_found":
                    return _response(
                        404,
                        {"error": "No request found for the given user_id and req_id"},
                    )

                if data.get("error_kind") == "schema_mismatch":
                    # Our SQL no longer matches the database - a table or
                    # column was renamed underneath us. That is our defect, and
                    # no amount of retrying resolves it, so it must not be
                    # dressed up as a transient outage. This is the alarm that
                    # says a schema change landed without us.
                    print(
                        "ERROR: generate_answer request lookup does not match "
                        f"the database schema: {err}"
                    )
                    failure = (
                        500,
                        "Request store schema mismatch",
                        "REQUEST_STORE_SCHEMA_MISMATCH",
                        False,
                    )
                else:
                    # The driver's message names the host, database, user and
                    # sslmode. It belongs in CloudWatch, not in the browser. A
                    # store that is down is retryable, which 502 does not say.
                    print(f"ERROR: generate_answer request lookup failed: {err}")
                    failure = (
                        503,
                        "Request store is unavailable, please retry",
                        "REQUEST_STORE_UNAVAILABLE",
                        True,
                    )

                if follow_up:
                    # Degraded, not broken. The person asked a question we can
                    # answer on its own merits; losing the request row costs us
                    # the tailoring, not the reply. The failure is still logged
                    # above and still named in the response, so this never
                    # hides an outage from whoever is triaging one - it only
                    # stops the outage reaching the beneficiary as a dead end.
                    subject = subject or follow_up[:120]
                    description = follow_up
                    source = "conversation"
                    degraded_from = failure[2]
                else:
                    status, message, code, retryable = failure
                    return _response(
                        status,
                        {
                            "error": message,
                            "code": code,
                            "retryable": retryable,
                            # Presentable text for clients that surface
                            # something to the person rather than a raw status.
                            # Deliberately not called `answer`: it is never
                            # advice and must never be rendered as any.
                            "message": _STORE_FAILURE_MESSAGE,
                        },
                    )
            else:
                source = "database"
                subject = subject or str(data.get("req_subj") or "").strip()
                description = description or str(data.get("req_desc") or "").strip()
                location = location or data.get("req_loc")
                if not category:
                    category = help_categories.get(str(data.get("req_cat_id")))
                additional_info = _describe_additional_info(data.get("additional_info"))

        if not description:
            return _response(400, {"error": "description is required and was empty"})
        if not subject:
            return _response(400, {"error": "subject is required and was empty"})

        category = str(category).strip() if category else "General"

        # Everything the request store gave us goes to the model. The
        # additional-info join has been running on every lookup since this
        # endpoint was written and its result was never read.
        if additional_info:
            description = (
                f"{description}\n\n"
                f"Additional details provided with this request:\n{additional_info}"
            )

        try:
            answer = generate_ai_answer(
                category=category,
                subject=subject,
                description=description,
                location=location,
                gender=body.get("gender"),
                age=body.get("age"),
                conversation_history=conversation_history,
            )
        except Exception as e:
            # Reporting a model failure as a 200 whose answer is the string
            # "Error: Failed to generate answer" hid Groq outages and retired
            # model ids from every metric and rendered the error to the
            # beneficiary as if it were advice.
            print(f"ERROR: generate_answer generation failed: {type(e).__name__}: {e}")
            return _response(
                502,
                {"error": "Answer generation failed", "code": "ANSWER_GENERATION_FAILED"},
            )

        if not answer or not str(answer).strip():
            print("ERROR: generate_answer generation returned an empty answer")
            return _response(
                502,
                {"error": "Answer generation returned no content", "code": "ANSWER_EMPTY"},
            )

        # source tells the caller whether the text came from the request row or
        # from the payload, which is what makes a degraded run legible.
        payload = {"answer": answer, "source": source}
        if degraded_from:
            # Named, not hidden: a dashboard can count these, and a client can
            # tell the person the reply is general rather than tailored to
            # their request. The key is absent on a healthy call, so nothing
            # that does not care about it has to change.
            payload["degraded"] = degraded_from
        return _response(200, payload)

    except Exception as e:
        print(f"ERROR: generate_answer failed: {type(e).__name__}: {e}")
        return _response(500, {"error": "Answer generation failed"})


# 5. Generate Subject
def generate_subject_handler(event, context):
    """AWS Lambda entry point for generate_subject service"""
    # The event carries the user's free text description and the request headers.
    # Help request descriptions routinely contain health, housing and financial
    # details, and the headers carry the caller's authorization token, so the
    # event is never logged. Log only the shape of the payload.
    print("LOG: generate_subject invoked, event keys:", sorted(event.keys()))

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

        description = body.get("description")
        max_length = 70

        # Validate description
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


# -------------------------------------------------------------
# Unified Entry Point (Fallback routing)
# -------------------------------------------------------------

def lambda_handler(event, context):
    """
    Unified Lambda handler that routes requests to appropriate service.
    Supports: predict_category, generate_subject, generate_answer, emergency_contacts, search_orgs
    """
    service = None
    try:
        # Check if service is specified in query parameters or body
        q_params = event.get("queryStringParameters") or {}
        service = q_params.get("service")

        # A body that will not parse must not become a 500. The router reads the
        # body only to discover which service was asked for, so a malformed one
        # is a client error - and when the query string already named the
        # service, the body is not the router's problem at all: the routed
        # handler reports it in its own, more specific error contract.
        try:
            body = _parse_event_body(event)
        except (json.JSONDecodeError, TypeError, ValueError):
            if not service:
                return _response(400, {"error": "Request body is not valid JSON"})
            body = None

        if not service:
            service = body.get("service", "predict_category") if isinstance(body, dict) else "predict_category"

        service = str(service).lower().strip()

        # Route to appropriate handler
        if service == "predict_category":
            return predict_category_handler(event, context)
        elif service == "generate_subject":
            return generate_subject_handler(event, context)
        elif service == "generate_answer":
            return generate_answer_handler(event, context)
        elif service == "emergency_contacts":
            return emergency_contacts_handler(event, context)
        elif service in ["search_orgs", "search_org", "find_nonprofits"]:
            return search_orgs_handler(event, context)
        else:
            return _response(400, {"error": f"Unknown service: {service}. Supported: predict_category, generate_subject, generate_answer, emergency_contacts, search_orgs"})

    except Exception as e:
        # str(e) put the raw exception text in the response. Provider and driver
        # messages quote the API key, the host and the connection string, so
        # this path could hand a caller a credential. The detail belongs in
        # CloudWatch; the caller gets a status and nothing it could not have
        # worked out for itself.
        print(f"ERROR: routing failed for service {service!r}: {type(e).__name__}: {e}")
        # emergency_contacts is the one service behind PROXY integration, and a
        # proxy method rejects an object body with a 502, which is the failure
        # reported in issue #146. Match the shape the routed service would have
        # used.
        if service == "emergency_contacts":
            return _proxy_response(500, {"error": "Emergency services lookup failed"})
        return _response(500, {"error": "Request failed"})
