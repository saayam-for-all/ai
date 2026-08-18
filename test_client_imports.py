"""
Guard against the utils/client.py import regression that broke dev.

utils/client.py must export every name its consumers import
(utils/__init__.py, services/classification_service.py, utils/subject_generator.py,
utils/search_orgs.py), and the top-level modules must import cleanly.

No network or API keys required: the SSM lookup in client.py fails gracefully and
leaves the clients as None, which is fine for import.
"""
import importlib

REQUIRED_CLIENT_EXPORTS = [
    "GROQ_API_KEY", "GEMINI_API_KEY",
    "GROQ_MODEL", "GROQ_TEMPERATURE", "GEMINI_MODEL", "GEMINI_TEMPERATURE",
    "client", "_gemini_client",          # raw SDK clients (classification_service)
    "groq_llm", "gemini_llm",            # LangChain models (answer generation, subject)
    "_use_groq", "_use_gemini", "has_any_llm",
]


def test_client_exports_all_required_names():
    c = importlib.import_module("utils.client")
    missing = [n for n in REQUIRED_CLIENT_EXPORTS if not hasattr(c, n)]
    assert not missing, f"utils.client is missing: {missing}"


def test_core_modules_import():
    for mod in ("utils", "services.classification_service", "lambda_function"):
        importlib.import_module(mod)


if __name__ == "__main__":
    test_client_exports_all_required_names()
    test_core_modules_import()
    print("PASS")
