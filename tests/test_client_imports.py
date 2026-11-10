"""
Guard against the utils/client.py import regression that broke dev.

utils/client.py must export every name its consumers import
(utils/__init__.py, services/classification_service.py, utils/subject_generator.py,
utils/search_orgs.py), and the top-level modules must import cleanly.

No network or API keys required: client.py reads SSM on first use, not at
import (issue #237).
"""

import pytest

# utils/client.py must export every name its consumers import, and the
# top-level modules must import cleanly without keys or network.
pytestmark = pytest.mark.integration
import importlib

REQUIRED_CLIENT_EXPORTS = [
    "GROQ_MODEL", "GROQ_TEMPERATURE", "GEMINI_MODEL", "GEMINI_TEMPERATURE",
    "get_groq_client", "get_gemini_client",  # raw SDK clients (classification_service)
    "get_groq_llm", "get_gemini_llm",        # LangChain models (subject, org search)
    "has_groq", "create_chat_model",
]

# Removed in #237: these were bound at import time, which meant fetching keys
# at import time. A consumer still importing one would silently get nothing.
REMOVED_CLIENT_NAMES = [
    "GROQ_API_KEY", "GEMINI_API_KEY", "client", "_gemini_client",
    "groq_llm", "gemini_llm", "_use_groq", "_use_gemini", "has_any_llm",
]


def test_client_exports_all_required_names():
    c = importlib.import_module("utils.client")
    missing = [n for n in REQUIRED_CLIENT_EXPORTS if not hasattr(c, n)]
    assert not missing, f"utils.client is missing: {missing}"


def test_client_no_longer_exports_import_time_names():
    c = importlib.import_module("utils.client")
    present = [n for n in REMOVED_CLIENT_NAMES if hasattr(c, n)]
    assert not present, f"utils.client still exports import-time names: {present}"


def test_core_modules_import():
    for mod in ("utils", "services.classification_service", "lambda_function"):
        importlib.import_module(mod)


if __name__ == "__main__":
    test_client_exports_all_required_names()
    test_client_no_longer_exports_import_time_names()
    test_core_modules_import()
    print("PASS")
