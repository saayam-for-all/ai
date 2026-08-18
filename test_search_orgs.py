"""
Unit tests for the More Organizations (search_orgs) service.

These tests make no network calls and do not touch AWS. Constructing a ChatGroq
instance with a dummy key does not call the Groq API, so we can assert on its
configuration safely.
"""
import pytest

import utils.search_orgs as so

# The model Groq decommissioned (returned 404 model_not_found), which broke the
# Organizations feature. Guard against reintroducing it.
DECOMMISSIONED_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def test_load_llm_uses_supported_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm = so.load_llm()
    assert llm.model_name == "llama-3.3-70b-versatile"
    assert llm.model_name != DECOMMISSIONED_MODEL


def test_load_llm_requires_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError):
        so.load_llm()


def test_build_prompt_exposes_expected_variables():
    prompt = so.build_prompt("shelter", "need a place to stay", "Tampa")
    assert {"subject", "description", "location", "format_instructions"} <= set(prompt.input_variables)


def test_parser_targets_organization_list():
    fmt = so.parser.get_format_instructions()
    assert "organizations" in fmt.lower()
