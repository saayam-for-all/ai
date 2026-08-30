"""
Tests for the generate_answer endpoint - issue #169.

The More Information button on Request Details calls this endpoint. It was
failing for several independent reasons at once, and these tests pin each of
them so they cannot come back one at a time:

  * the database is a source of the request text, not a precondition. A caller
    that already has the subject and description is answered without Postgres.
  * a request that does not exist is a 404; a database that is down is a 503,
    and its driver message goes to CloudWatch rather than to the browser.
  * a model failure is a 5xx, not a 200 whose answer reads
    "Error: Failed to generate answer".
  * the identifiers the web client actually holds are accepted.

No network, no database and no API keys required: both the request lookup and
the model call are patched.
"""
import json
from unittest import mock

import lambda_function as LF


def _event(payload, envelope="direct"):
    """Build the three shapes the function is invoked with in production."""
    if envelope == "direct":
        # boto3 lambda.invoke, and the ml-api aggregator.
        return dict(payload)
    if envelope == "string":
        # API Gateway with a stringified body.
        return {"body": json.dumps(payload)}
    return {"body": dict(payload)}


def _generation(answer="Here is what you can do."):
    return mock.patch.object(LF, "generate_ai_answer", return_value=answer)


def _lookup(result):
    return mock.patch.object(LF, "_lookup_request", return_value=result)


ROW = {
    "req_subj": "Need winter coats",
    "req_desc": "Two children, no warm clothing, snow next week.",
    "req_loc": "Chicago",
    "req_cat_id": "1",
}


# -------------------------------------------------------------------
# The database is optional
# -------------------------------------------------------------------

def test_subject_and_description_answer_without_touching_the_database():
    """The whole point of the fix: no Postgres call when the caller has the text."""
    lookup = mock.Mock(side_effect=AssertionError("the database must not be read"))
    with mock.patch.object(LF, "_lookup_request", lookup), _generation() as gen:
        res = LF.generate_answer_handler(
            _event({"subject": "Need winter coats", "description": "Two children, no coats."}),
            None,
        )

    assert res["statusCode"] == 200
    assert res["body"]["answer"] == "Here is what you can do."
    assert res["body"]["source"] == "request"
    lookup.assert_not_called()
    assert gen.call_args.kwargs["subject"] == "Need winter coats"


def test_database_is_still_used_when_only_identifiers_are_supplied():
    with _lookup(dict(ROW)), _generation() as gen:
        res = LF.generate_answer_handler(
            _event({"user_id": "SID-1", "req_id": "REQ-1"}), None
        )

    assert res["statusCode"] == 200
    assert res["body"]["source"] == "database"
    assert gen.call_args.kwargs["description"] == ROW["req_desc"]
    assert gen.call_args.kwargs["location"] == "Chicago"


def test_lookup_fills_only_what_the_caller_did_not_send():
    with _lookup(dict(ROW)), _generation() as gen:
        LF.generate_answer_handler(
            _event({"user_id": "SID-1", "req_id": "REQ-1", "subject": "Caller subject"}),
            None,
        )

    assert gen.call_args.kwargs["subject"] == "Caller subject"
    assert gen.call_args.kwargs["description"] == ROW["req_desc"]


def test_neither_text_nor_identifiers_is_a_400_that_names_both_options():
    res = LF.generate_answer_handler(_event({"conversation_history": []}), None)

    assert res["statusCode"] == 400
    message = res["body"]["error"]
    assert "subject and description" in message
    assert "user_id and req_id" in message


# -------------------------------------------------------------------
# Identifier aliases - what the web client and the aggregator actually send
# -------------------------------------------------------------------

def test_request_details_page_payload_is_accepted():
    """RequestDetails.jsx holds `id`, not `req_id`, and `userDBid`, not `user_id`."""
    with _lookup(dict(ROW)), _generation():
        res = LF.generate_answer_handler(
            _event({"id": "REQ-1", "userDBid": "SID-1"}), None
        )

    assert res["statusCode"] == 200


def test_beneficiary_id_alias_is_accepted():
    with _lookup(dict(ROW)), _generation():
        res = LF.generate_answer_handler(
            _event({"request_id": "REQ-1", "beneficiary_id": "SID-1"}), None
        )

    assert res["statusCode"] == 200


def test_canonical_names_still_win_over_aliases():
    with _lookup(dict(ROW)) as lookup, _generation():
        LF.generate_answer_handler(
            _event({"req_id": "REQ-canonical", "id": "REQ-alias", "user_id": "SID-1"}),
            None,
        )

    lookup.assert_called_once_with("SID-1", "REQ-canonical")


# -------------------------------------------------------------------
# Error classification
# -------------------------------------------------------------------

def test_missing_request_is_404():
    absent = {"error": "No data found for given user_id and req_id",
              "error_kind": "not_found"}
    with _lookup(absent):
        res = LF.generate_answer_handler(
            _event({"user_id": "SID-1", "req_id": "REQ-nope"}), None
        )

    assert res["statusCode"] == 404


def test_database_down_is_a_retryable_503_and_leaks_no_connection_detail(capsys):
    driver_error = (
        "OperationalError: connection to server at "
        "saayam-dev.abc123.us-east-1.rds.amazonaws.com port 5432 failed: "
        "FATAL: password authentication failed for user \"genai_user\""
    )
    with _lookup({"error": driver_error, "error_kind": "unavailable"}):
        res = LF.generate_answer_handler(
            _event({"user_id": "SID-1", "req_id": "REQ-1"}), None
        )

    assert res["statusCode"] == 503
    assert res["body"]["retryable"] is True
    assert res["body"]["code"] == "REQUEST_STORE_UNAVAILABLE"

    returned = json.dumps(res["body"])
    for secret in ("rds.amazonaws.com", "genai_user", "password", "5432"):
        assert secret not in returned, f"{secret} must not reach the client"

    # It does have to reach CloudWatch, or nobody can triage the outage.
    assert "rds.amazonaws.com" in capsys.readouterr().out


def test_an_empty_rebuilt_database_is_not_reported_as_an_outage():
    """During the rebuild the tables exist but hold no rows: that is a 404."""
    with _lookup({"error": "No data found for given user_id and req_id",
                  "error_kind": "not_found"}):
        res = LF.generate_answer_handler(
            _event({"user_id": "SID-1", "req_id": "REQ-1"}), None
        )

    assert res["statusCode"] == 404


def test_row_with_empty_description_is_400_not_a_generated_answer():
    row = dict(ROW, req_desc="   ")
    with _lookup(row), _generation():
        res = LF.generate_answer_handler(
            _event({"user_id": "SID-1", "req_id": "REQ-1"}), None
        )

    assert res["statusCode"] == 400
    assert "description" in res["body"]["error"]


# -------------------------------------------------------------------
# Model failures are failures
# -------------------------------------------------------------------

def test_model_exception_is_a_502_not_a_200(capsys):
    with mock.patch.object(
        LF, "generate_ai_answer", side_effect=RuntimeError("model_decommissioned")
    ):
        res = LF.generate_answer_handler(
            _event({"subject": "s", "description": "d"}), None
        )

    assert res["statusCode"] == 502
    assert res["body"]["code"] == "ANSWER_GENERATION_FAILED"
    assert "model_decommissioned" in capsys.readouterr().out


def test_empty_answer_is_a_502_not_a_200_with_an_empty_string():
    with _generation(""):
        res = LF.generate_answer_handler(
            _event({"subject": "s", "description": "d"}), None
        )

    assert res["statusCode"] == 502
    assert res["body"]["code"] == "ANSWER_EMPTY"


def test_no_success_response_ever_carries_an_error_string_as_the_answer():
    """The old handler returned 200 with answer='Error: Failed to generate answer'."""
    for outcome in (RuntimeError("groq down"), "", None, "   "):
        patch = (
            mock.patch.object(LF, "generate_ai_answer", side_effect=outcome)
            if isinstance(outcome, Exception)
            else mock.patch.object(LF, "generate_ai_answer", return_value=outcome)
        )
        with patch:
            res = LF.generate_answer_handler(
                _event({"subject": "s", "description": "d"}), None
            )
        assert res["statusCode"] != 200, f"{outcome!r} must not be reported as success"


# -------------------------------------------------------------------
# Envelopes and payload hygiene
# -------------------------------------------------------------------

def test_all_three_invocation_envelopes_work():
    for envelope in ("direct", "string", "dict"):
        with _generation():
            res = LF.generate_answer_handler(
                _event({"subject": "s", "description": "d"}, envelope), None
            )
        assert res["statusCode"] == 200, envelope


def test_malformed_json_body_is_400_not_500():
    res = LF.generate_answer_handler({"body": "{not json"}, None)
    assert res["statusCode"] == 400


def test_non_object_body_is_400_not_500():
    res = LF.generate_answer_handler({"body": json.dumps(["a", "list"])}, None)
    assert res["statusCode"] == 400


def test_conversation_history_that_is_not_a_list_is_dropped():
    with _generation() as gen:
        LF.generate_answer_handler(
            _event({"subject": "s", "description": "d",
                    "conversation_history": "not a list"}),
            None,
        )

    assert gen.call_args.kwargs["conversation_history"] is None


def test_conversation_history_list_is_passed_through():
    history = [{"role": "user", "content": "hello"}]
    with _generation() as gen:
        LF.generate_answer_handler(
            _event({"subject": "s", "description": "d",
                    "conversation_history": history}),
            None,
        )

    assert gen.call_args.kwargs["conversation_history"] == history


def test_category_id_from_the_row_is_mapped_to_a_category_name():
    with _lookup(dict(ROW)), _generation() as gen:
        LF.generate_answer_handler(_event({"user_id": "S", "req_id": "R"}), None)

    category = gen.call_args.kwargs["category"]
    assert category and category != "1", "the numeric id must not reach the prompt"


def test_unknown_category_id_falls_back_to_general():
    with _lookup(dict(ROW, req_cat_id="999999")), _generation() as gen:
        LF.generate_answer_handler(_event({"user_id": "S", "req_id": "R"}), None)

    assert gen.call_args.kwargs["category"] == "General"


def test_caller_supplied_category_is_used_as_is():
    with _generation() as gen:
        LF.generate_answer_handler(
            _event({"subject": "s", "description": "d", "category": "Housing"}), None
        )

    assert gen.call_args.kwargs["category"] == "Housing"


def test_logging_records_the_shape_but_never_the_description(capsys):
    secret = "I have been diagnosed with a serious illness and cannot pay rent"
    with _generation():
        LF.generate_answer_handler(_event({"subject": "s", "description": secret}), None)

    out = capsys.readouterr().out
    assert "generate_answer invoked" in out
    assert "description" in out, "the key name is fine to log"
    assert secret not in out, "the description content must never be logged"


# -------------------------------------------------------------------
# Blast radius: the psycopg2 import must not be at module scope
# -------------------------------------------------------------------

def test_request_db_is_not_imported_at_module_scope():
    """A driver built for the wrong Python minor version used to fail the whole
    module, taking predict_category, generate_subject, emergency_contacts and
    search_orgs down with generate_answer. Only generate_answer needs it."""
    import inspect

    source = inspect.getsource(LF)
    header = source.split("def _parse_event_body")[0]
    assert "from utils.request_db import" not in header, (
        "the request database import must stay inside _lookup_request"
    )
    assert "from utils.request_db import" in inspect.getsource(LF._lookup_request)


def test_other_services_survive_a_broken_request_database():
    """A psycopg2 failure must not reach the four services that never use it."""
    with mock.patch.object(
        LF, "_lookup_request",
        side_effect=ImportError("Runtime.ImportModuleError: no module named psycopg2"),
    ):
        with mock.patch.object(LF, "predict_categories", return_value=([], {})):
            res = LF.predict_category_handler(_event({"description": "d"}), None)
        assert res["statusCode"] == 200

        with mock.patch.object(LF, "generate_subject_from_description", return_value="s"):
            res = LF.generate_subject_handler(_event({"description": "d"}), None)
        assert res["statusCode"] == 200


def test_an_unexpected_lookup_exception_is_a_500_with_no_internals():
    with mock.patch.object(
        LF, "_lookup_request", side_effect=ImportError("no module named psycopg2")
    ):
        res = LF.generate_answer_handler(
            _event({"user_id": "S", "req_id": "R"}), None
        )

    assert res["statusCode"] == 500
    assert "psycopg2" not in json.dumps(res["body"])


# -------------------------------------------------------------------
# Routing
# -------------------------------------------------------------------

def test_unified_router_reaches_generate_answer():
    with _generation():
        res = LF.lambda_handler(
            {"body": json.dumps(
                {"service": "generate_answer", "subject": "s", "description": "d"}
            )},
            None,
        )

    assert res["statusCode"] == 200
    assert res["body"]["answer"]
