"""
Pin the response contract the deployed web client depends on.

Every GenAI endpoint is read by the client as response.body.<field>:

    predict   ->  response.body.categories   (objects with category_name,
                  category_number, hierarchy, confidence)
    subject   ->  response.body.subject
    answer    ->  response.body.answer
    emergency ->  handled separately, see the proxy test below

These methods use NON PROXY integration, so API Gateway returns the Lambda's
return value to the client unchanged. body must therefore stay a JSON object.
Serialising it makes body a string and every one of those reads becomes
undefined, which is what broke category prediction and subject generation.

No network or keys required.
"""

import pytest

# The API Gateway envelope every service returns - proxy vs non-proxy - which
# is what the web client actually parses.
pytestmark = pytest.mark.contract
import json
from unittest import mock

import lambda_function as LF


def test_response_body_stays_an_object():
    res = LF._response(200, {"categories": [{"category_name": "MATH"}]})
    assert isinstance(res["body"], dict), "body must not be serialised to a string"
    assert res["body"]["categories"][0]["category_name"] == "MATH"


def test_predict_returns_ranked_objects_under_categories():
    ranked = [
        {"category_number": "4.3.1", "category_name": "MATH",
         "confidence": 0.97, "hierarchy": "Education Career Support > Tutoring > Math"},
    ]
    with mock.patch.object(LF, "predict_categories", return_value=(ranked, {})):
        res = LF.predict_category_handler({"body": json.dumps({"description": "x"})}, None)

    assert res["statusCode"] == 200
    cats = res["body"]["categories"]
    # the client maps over these four fields
    for field in ("category_name", "category_number", "confidence", "hierarchy"):
        assert field in cats[0], f"client reads {field} and it is missing"


def test_subject_is_readable_at_body_subject():
    with mock.patch.object(LF, "generate_subject_from_description", return_value="Help with Math"):
        res = LF.generate_subject_handler({"body": json.dumps({"description": "math"})}, None)
    assert res["body"]["subject"] == "Help with Math"


def test_emergency_uses_the_proxy_contract_instead():
    """Emergency Contacts is the one endpoint on PROXY integration.

    Its page sends lat/lng from browser geolocation, and proxy is the only
    integration that passes query parameters and the caller IP to the function.
    Proxy requires a serialised body, and API Gateway returns that string to the
    client as the entire response, which is the shape the page parses.
    """
    res = LF.emergency_contacts_handler({"queryStringParameters": {"country": "India"}}, None)
    assert isinstance(res["body"], str), "proxy integration requires a string body"
    payload = json.loads(res["body"])
    assert payload["services"]["police"]["dial_number"] == "112"


def test_emergency_returns_indian_numbers_not_us_ones():
    # The original P0: non US users were shown 911.
    payload = json.loads(
        LF.emergency_contacts_handler({"queryStringParameters": {"country": "India"}}, None)["body"]
    )
    dialled = {k: v["dial_number"] for k, v in payload["services"].items()}
    assert dialled["police"] == "112", dialled
    assert "911" not in dialled.values(), f"US number leaked into an India response: {dialled}"


def test_error_bodies_are_objects_too():
    res = LF.predict_category_handler({"body": json.dumps({})}, None)
    assert res["statusCode"] == 400
    assert isinstance(res["body"], dict) and "error" in res["body"]
