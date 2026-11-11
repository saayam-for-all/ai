
"""
Guard against eager AI initialization during Lambda cold start.

utils/client.py must export every name its consumers import.

Importing lambda_function must not import AI-backed modules or trigger
AWS SSM credential retrieval. AI initialization should happen only when
an AI-backed handler actually needs it.
"""

import importlib
import subprocess
import sys
import textwrap

import pytest


pytestmark = pytest.mark.integration


REQUIRED_CLIENT_EXPORTS = [
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_MODEL",
    "GROQ_TEMPERATURE",
    "GEMINI_MODEL",
    "GEMINI_TEMPERATURE",
    "client",
    "_gemini_client",
    "groq_llm",
    "gemini_llm",
    "_use_groq",
    "_use_gemini",
    "has_any_llm",
    "create_chat_model",
]


def test_client_exports_all_required_names():
    client_module = importlib.import_module("utils.client")

    missing = [
        name
        for name in REQUIRED_CLIENT_EXPORTS
        if not hasattr(client_module, name)
    ]

    assert not missing, f"utils.client is missing: {missing}"


def test_core_modules_import():
    for module_name in (
        "utils",
        "services.classification_service",
        "utils.subject_generator",
        "utils.search_orgs",
        "lambda_function",
    ):
        importlib.import_module(module_name)


def test_lambda_import_does_not_initialize_ai_or_fetch_credentials():
    script = textwrap.dedent(
        """
        import sys
        import types

        # Any attempt to create an AWS client during this test is a failure.
        boto3_stub = types.ModuleType("boto3")

        def unexpected_aws_client(*args, **kwargs):
            raise AssertionError(
                "AWS client was created during Lambda module import"
            )

        boto3_stub.client = unexpected_aws_client
        sys.modules["boto3"] = boto3_stub

        import lambda_function

        # Lambda module import must not load AI-backed services.
        forbidden_modules = (
            "utils.subject_generator",
            "services.classification_service",
            "utils.categories",
            "utils.generate_answer_service",
            "utils.model_fallback",
            "utils.search_orgs",
        )

        loaded = [
            name
            for name in forbidden_modules
            if name in sys.modules
        ]

        assert not loaded, (
            "AI modules were imported during Lambda cold start: "
            f"{loaded}"
        )

        # Importing the client module itself must not retrieve credentials.
        import utils.client as client_module

        assert client_module._credentials_loaded is False, (
            "AI credentials were loaded during module import"
        )

        assert client_module.GROQ_API_KEY is None
        assert client_module.GEMINI_API_KEY is None
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "Cold-start isolation test failed.\\n"
        f"STDOUT:\\n{result.stdout}\\n"
        f"STDERR:\\n{result.stderr}"
    )


if __name__ == "__main__":
    test_client_exports_all_required_names()
    test_core_modules_import()
    test_lambda_import_does_not_initialize_ai_or_fetch_credentials()
    print("PASS")
