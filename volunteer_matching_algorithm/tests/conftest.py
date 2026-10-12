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

    # Import matcher only while fake embeddings are active.
    matcher = importlib.import_module("app.matcher")

    yield matcher

    # Remove the matcher loaded for this test.
    monkeypatch.delitem(sys.modules, "app.matcher", raising=False)
    monkeypatch.delattr("app.matcher", raising=False)