import importlib
import sys
import types

import numpy as np
import pytest


@pytest.fixture
def fake_embeddings(monkeypatch):
    module = types.ModuleType("app.embeddings")
    module.get_embedding = lambda text: np.array([1.0])
    module.cosine_similarity = lambda a, b: 0.0

    # Temporarily replace the embeddings module.
    monkeypatch.setitem(sys.modules, "app.embeddings", module)

    # Force a fresh import using the fake embeddings.
    sys.modules.pop("app.matcher", None)
    matcher = importlib.import_module("app.matcher")

    yield matcher

    # Remove the fake matcher after the test.
    sys.modules.pop("app.matcher", None)
    app = sys.modules.get("app")
    if getattr(app, "matcher", None) is matcher:
        delattr(app, "matcher")