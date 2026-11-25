"""Drill complete provider failure at the four GenAI Lambda entry points."""
import logging
from unittest.mock import Mock

import httpx
import pytest
from google.genai.errors import ClientError
from groq import APITimeoutError, AuthenticationError, NotFoundError, RateLimitError
from langchain_core.runnables import RunnableLambda

import lambda_function as handlers
import services.classification_service as classification
import utils
from utils import client as provider_clients
from utils import model_fallback, search_orgs, subject_generator


pytestmark = pytest.mark.unit

_OPERATIONS = (
    ("predict_category", "CATEGORY_PREDICTION_UNAVAILABLE"),
    ("generate_answer", "ANSWER_GENERATION_FAILED"),
    ("generate_subject", None),
    ("search_orgs", "ORG_SEARCH_UNAVAILABLE"),
)
_LOG_GAPS = {
    "generate_subject": "Subject generator still prints unstructured provider errors",
    "search_orgs": "Organization search warnings name providers only and lack error_class",
}


def _provider_error(provider, status):
    request = httpx.Request("POST", "https://example.invalid/model")
    if status is None:
        if provider == "groq":
            return APITimeoutError(request=request)
        return httpx.ReadTimeout("Provider request timed out", request=request)

    if provider == "gemini":
        return ClientError(status, {"error": {"message": "Simulated provider failure"}})

    error_type = {404: NotFoundError, 401: AuthenticationError, 429: RateLimitError}[status]
    response = httpx.Response(status, request=request)
    return error_type("Simulated provider failure", response=response, body=None)


@pytest.fixture(
    params=[
        (404, "model_not_found"),
        (401, "auth_or_entitlement"),
        (429, "rate_limited"),
        (None, "timeout_or_unavailable"),
    ],
    ids=["model-not-found", "auth", "rate-limit", "timeout"],
)
def failure(request):
    return request.param


@pytest.fixture
def drill(monkeypatch, failure):
    def run(operation):
        status, _ = failure
        attempted = []

        def fail(provider, model):
            attempted.append((provider, model))
            raise _provider_error(provider, status)

        if operation == "predict_category":
            groq_client = Mock()
            gemini_client = Mock()
            groq_client.chat.completions.create.side_effect = (
                lambda **args: fail("groq", args["model"])
            )
            gemini_client.models.generate_content.side_effect = (
                lambda **args: fail("gemini", args["model"])
            )
            monkeypatch.setattr(classification, "client", groq_client)
            monkeypatch.setattr(classification, "_use_groq", True)
            monkeypatch.setattr(classification, "_gemini_client", gemini_client)
        elif operation == "generate_answer":
            def create_model(target, **kwargs):
                model = Mock()
                model.invoke.side_effect = lambda _: fail(target.provider, target.model)
                return model

            monkeypatch.setattr(utils, "create_chat_model", create_model)
        elif operation == "generate_subject":
            for provider, model_name in (
                ("groq", subject_generator.GROQ_MODEL),
                ("gemini", subject_generator.GEMINI_MODEL),
            ):
                model = Mock()
                model.invoke.side_effect = (
                    lambda _, p=provider, m=model_name: fail(p, m)
                )
                monkeypatch.setattr(subject_generator, f"{provider}_llm", model)
                monkeypatch.setattr(subject_generator, f"_use_{provider}", True)
        else:
            monkeypatch.setattr(
                search_orgs, "load_llm",
                lambda: RunnableLambda(lambda _: fail("groq", provider_clients.GROQ_MODEL)),
            )
            monkeypatch.setattr(
                search_orgs, "load_fallback_llm",
                lambda: RunnableLambda(
                    lambda _: fail("gemini", provider_clients.GEMINI_MODEL)
                ),
            )

        event = {
            "subject": "Math tutoring",
            "description": "I need help studying for a math exam.",
            "location": "United States",
        }
        response = getattr(handlers, f"{operation}_handler")(event, None)
        if operation in ("predict_category", "generate_answer"):
            expected = [
                (target.provider, target.model)
                for target in model_fallback._DEFAULT_MODEL_CHAIN
            ]
        elif operation == "generate_subject":
            expected = [
                ("groq", subject_generator.GROQ_MODEL),
                ("gemini", subject_generator.GEMINI_MODEL),
            ]
        else:
            expected = [
                ("groq", provider_clients.GROQ_MODEL),
                ("gemini", provider_clients.GEMINI_MODEL),
            ]
        if attempted != expected:
            pytest.fail(f"Expected provider attempts {expected}, got {attempted}")
        return response, expected

    return run


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        pytest.param(
            operation, code, id=operation,
            marks=pytest.mark.xfail(
                strict=True, raises=AssertionError,
                reason="Subject generation returns a successful truncated description",
            ),
        ) if code is None else pytest.param(operation, code, id=operation)
        for operation, code in _OPERATIONS
    ],
)
def test_total_provider_failure_returns_service_error(drill, operation, expected_code):
    """Provider outages must be distinguishable from successful responses."""
    response, _ = drill(operation)

    if expected_code is None:
        # The team still needs to agree on the exact Subject error code.
        assert 500 <= response["statusCode"] < 600
        return
    assert response["statusCode"] == 502
    assert response["body"] != []
    assert response["body"]["code"] == expected_code
    if operation == "predict_category":
        assert "categories" not in response["body"]


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            operation, id=operation,
            marks=pytest.mark.xfail(
                strict=True, raises=AssertionError, reason=_LOG_GAPS[operation]
            ),
        ) if operation in _LOG_GAPS else pytest.param(operation, id=operation)
        for operation, _ in _OPERATIONS
    ],
)
def test_total_provider_failure_logs_each_model(drill, operation, failure, caplog):
    """A provider warning identifies each model and its failure class."""
    with caplog.at_level(logging.WARNING):
        _, targets = drill(operation)

    _, expected_class = failure
    warnings = [
        record.getMessage() for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    for provider, model in targets:
        matches = [
            line for line in warnings
            if line.startswith("MODEL_FAILOVER ")
            and f"provider={provider} model={model} " in line
        ]
        assert len(matches) == 1, (provider, model, warnings)
        # On test without #241, model attribution is still required. Once
        # the classifier is present, the same drill also requires its label.
        if hasattr(model_fallback, "classify_provider_error"):
            assert f"error_class={expected_class} " in matches[0]
