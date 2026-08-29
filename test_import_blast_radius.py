"""Cross-service blast radius at import time - issue #171.

All five services are packaged into one deployment and share one module. That
makes every module-scope import a shared failure: a dependency that only
``generate_answer`` needs, imported at the top of ``lambda_function``, runs
before any handler does, so when it breaks it takes down Emergency Contacts
and category prediction with it.

That is not hypothetical. ``utils/request_db`` imports ``psycopg2``, a compiled
C extension; when it was imported at module scope a packaging problem in that
one wheel broke every endpoint in the deployment (issue #169). These tests
pin the property that stopped it: the handler module must import, and every
service that does not need a dependency must keep working while that
dependency is unimportable.
"""
import builtins
import importlib
import json
import sys
from unittest import mock

import pytest

pytestmark = pytest.mark.integration


HEAVY_OPTIONAL_DEPENDENCIES = ["psycopg2", "psycopg2-binary"]


def test_importing_the_handler_module_does_not_import_the_database_driver():
    """psycopg2 must be imported lazily, inside the lookup that needs it."""
    for module in list(sys.modules):
        if module.startswith("psycopg2"):
            del sys.modules[module]
    sys.modules.pop("lambda_function", None)

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] == "psycopg2":
            raise AssertionError(
                "lambda_function imported psycopg2 at module scope. A packaging "
                "problem in that one compiled dependency then breaks every "
                "service in the deployment, not just generate_answer."
            )
        return real_import(name, *args, **kwargs)

    with mock.patch.object(builtins, "__import__", side_effect=guarded):
        importlib.import_module("lambda_function")


@pytest.mark.parametrize("dependency", HEAVY_OPTIONAL_DEPENDENCIES)
def test_services_that_do_not_need_a_dependency_survive_it_being_broken(dependency):
    """Emergency Contacts must answer while the database driver is unusable."""
    import lambda_function as LF

    broken = {name: None for name in list(sys.modules) if name.startswith(dependency)}
    with mock.patch.dict(sys.modules, broken):
        response = LF.emergency_contacts_handler(
            {"queryStringParameters": {"country": "IN"},
             "requestContext": {"identity": {"sourceIp": "8.8.8.8"}}},
            None,
        )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["services"], "emergency contacts returned nothing while psycopg2 was broken"


def test_the_module_imports_without_any_api_key_configured():
    """No key is present in CI, and import must not depend on one.

    The clients resolve to None and each service reports its own unavailability
    at call time. An ImportError here would fail the deploy instead.
    """
    sys.modules.pop("lambda_function", None)
    with mock.patch.dict("os.environ", {}, clear=True):
        module = importlib.import_module("lambda_function")
    for handler in ("predict_category_handler", "generate_subject_handler",
                    "generate_answer_handler", "emergency_contacts_handler",
                    "search_orgs_handler", "lambda_handler"):
        assert callable(getattr(module, handler)), f"{handler} missing after a keyless import"
