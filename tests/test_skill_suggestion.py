"""
Volunteer skill suggestions: predict_category_api with mode "volunteer_skills"
(issue #216).

The guarantees under test are the ones the web app builds on:

* every suggested category_number is a leaf the Skills picker can select,
  never General, never a duplicate, at most six, sorted by confidence;
* a volunteer's description may yield skills from several unrelated areas,
  and the elderly keyword shortcut does not apply to it;
* "nothing matched" is a 200 with an empty list, while a total model outage
  is a 502 SKILL_SUGGESTION_UNAVAILABLE;
* a request without `mode` is answered exactly as before;
* the volunteer's text never reaches a log line.

No network calls and no API keys: the Groq and Gemini clients are stubbed on
the new module, and each test asserts on what the fakes received so that an
unmocked call cannot pass by accident.
"""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from groq import GroqError

import lambda_function as LF
import services.classification_service as cs
import services.skill_suggestion_service as ss
from utils.predict_category_list import help_categories
from utils.routing_for_categories import is_elderly_context


pytestmark = pytest.mark.unit


_ROUTING_CONFIG = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "model_routing.json")
    .read_text(encoding="utf-8")
)
_CONFIGURED_GROQ_MODELS = [
    entry["model"]
    for entry in _ROUTING_CONFIG["model_chain"]
    if entry["provider"] == "groq"
]
_CONFIGURED_GEMINI_MODEL = next(
    entry["model"]
    for entry in _ROUTING_CONFIG["model_chain"]
    if entry["provider"] == "gemini"
)

_USAGE = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)


def _groq_response(payload):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=_USAGE,
    )


class _FakeGroq:
    """Fake raw Groq client.

    `outcomes` maps a model id to a response or an exception. `sequence`, if
    given instead, is consumed one call at a time, whatever the model.
    """

    def __init__(self, outcomes=None, sequence=None):
        self.outcomes = outcomes or {}
        self.sequence = list(sequence or [])
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer.sequence:
                    outcome = outer.sequence.pop(0)
                else:
                    outcome = outer.outcomes[kwargs["model"]]
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class _FakeGemini:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []
        outer = self

        class _Models:
            def generate_content(self, **kwargs):
                outer.calls.append(kwargs)
                if outer.error is not None:
                    raise outer.error
                return SimpleNamespace(text=json.dumps(outer.payload))

        self.models = _Models()


def _install(monkeypatch, groq=None, gemini=None):
    """Stub the providers the skill suggestion service talks to."""
    monkeypatch.setattr(ss, "client", groq)
    monkeypatch.setattr(ss, "_use_groq", groq is not None)
    monkeypatch.setattr(ss, "_gemini_client", gemini)


def _primary_returns(monkeypatch, payload):
    """The first configured Groq model answers with `payload`."""
    groq = _FakeGroq({_CONFIGURED_GROQ_MODELS[0]: _groq_response(payload)})
    gemini = _FakeGemini(error=AssertionError("Gemini must not be called"))
    _install(monkeypatch, groq, gemini)
    return groq


def _skill(category, confidence, evidence=None):
    item = {"category": category, "confidence": confidence}
    if evidence is not None:
        item["evidence"] = evidence
    return item


def _volunteer_event(description, **extra):
    return {"body": json.dumps({"description": description, "mode": "volunteer_skills", **extra})}


# ---------------------------------------------------------------------------
# The leaf set and the prompt
# ---------------------------------------------------------------------------

def test_leaf_set_is_exactly_the_selectable_categories():
    """Every leaf, and nothing else: no General, no parent."""
    ids = list(help_categories)
    expected = {
        category_id
        for category_id in ids
        if category_id != "0.0.0.0.0"
        and not any(other.startswith(category_id + ".") for other in ids)
    }

    assert set(ss.LEAF_CATEGORY_IDS) == expected
    assert len(ss.LEAF_CATEGORY_IDS) == len(set(ss.LEAF_CATEGORY_IDS))
    assert "0.0.0.0.0" not in ss.LEAF_CATEGORY_IDS
    for parent in ("1", "1.3", "3.3", "4.3", "5.1", "6"):
        assert parent not in ss.LEAF_CATEGORY_IDS


def test_prompt_offers_every_leaf_and_no_parent_or_general():
    listed = {
        line.split(" | ", 1)[0]
        for line in ss.SYSTEM_PROMPT.splitlines()
        if " | " in line and not line.startswith("Categories")
    }
    assert listed == set(ss.LEAF_CATEGORY_IDS)
    assert "GENERAL_CATEGORY" not in ss.SYSTEM_PROMPT


def test_category_list_is_a_fixed_system_message(monkeypatch):
    """The category list never changes between requests, so it can be cached;
    only the user message carries the volunteer's text."""
    groq = _FakeGroq(sequence=[
        _groq_response({"skills": []}),
        _groq_response({"skills": []}),
    ])
    _install(monkeypatch, groq, _FakeGemini(error=AssertionError("unused")))

    ss.suggest_skills("I can fix bikes")
    ss.suggest_skills("I knit scarves")

    first, second = (call["messages"] for call in groq.calls)
    assert first[0] == second[0] == {"role": "system", "content": ss.SYSTEM_PROMPT}
    assert "I can fix bikes" in first[1]["content"]
    assert "I knit scarves" in second[1]["content"]
    assert "I can fix bikes" not in ss.SYSTEM_PROMPT
    assert groq.calls[0]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------

def test_skills_from_several_areas_are_all_returned(monkeypatch):
    """The case the help-request walk cannot serve: one volunteer, three areas."""
    _primary_returns(monkeypatch, {
        "skills": [
            _skill("4.3.1", 0.93, "math teacher"),
            _skill("3.3.5", 0.88, "gardening"),
            _skill("5.3", 0.81, "listen to people who are struggling"),
        ],
        "unmatched_skills": [],
    })

    categories, unmatched, usage = ss.suggest_skills(
        "Math teacher, I love gardening and I listen to people who are struggling."
    )

    assert categories == [
        {
            "category_number": "4.3.1",
            "category_name": "MATH",
            "confidence": 0.93,
            "hierarchy": "Education Career Support > Tutoring > Math",
            "evidence": "math teacher",
        },
        {
            "category_number": "3.3.5",
            "category_name": "GARDEN",
            "confidence": 0.88,
            "hierarchy": "Housing Assistance > Repair Maintenance Support > Garden",
            "evidence": "gardening",
        },
        {
            "category_number": "5.3",
            "category_name": "MENTAL_WELLBEING_SUPPORT",
            "confidence": 0.81,
            "hierarchy": "Healthcare And Wellness > Mental Wellbeing Support",
            "evidence": "listen to people who are struggling",
        },
    ]
    assert unmatched == []
    assert usage["total_calls"] == 1
    assert usage["total_tokens"] == 120


def test_general_parents_and_unknown_ids_are_dropped(monkeypatch):
    _primary_returns(monkeypatch, {
        "skills": [
            _skill("0.0.0.0.0", 0.99),   # General
            _skill("GENERAL_CATEGORY", 0.99),
            _skill("4.3", 0.95),         # parent: not selectable
            _skill("3", 0.95),           # top level: not selectable
            _skill("9.9.9", 0.95),       # does not exist
            _skill(None, 0.95),
            "3.3.3",                     # not an object
            _skill("3.3.1", 0.9),
        ],
    })

    categories, _, _ = ss.suggest_skills("I do plumbing")

    assert [c["category_number"] for c in categories] == ["3.3.1"]


def test_a_category_name_is_mapped_to_its_leaf_id(monkeypatch):
    _primary_returns(monkeypatch, {"skills": [_skill("ELECTRICIAN", 0.9)]})

    categories, _, _ = ss.suggest_skills("licensed electrician")

    assert [c["category_number"] for c in categories] == ["3.3.3"]


def test_duplicates_keep_the_highest_confidence(monkeypatch):
    _primary_returns(monkeypatch, {
        "skills": [
            _skill("3.3.1", 0.6, "pipes"),
            _skill("3.3.1", 0.9, "plumbing"),
            _skill("PLUMBING", 0.7),
        ],
    })

    categories, _, _ = ss.suggest_skills("I do plumbing and fix pipes")

    assert len(categories) == 1
    assert categories[0]["confidence"] == 0.9
    assert categories[0]["evidence"] == "plumbing"


def test_confidence_is_clamped_and_unparseable_values_are_dropped(monkeypatch):
    _primary_returns(monkeypatch, {
        "skills": [
            _skill("3.3.1", 1.7),
            _skill("3.3.2", "high"),
            _skill("3.3.3", None),
            _skill("3.3.4", -2),
        ],
    })

    categories, _, _ = ss.suggest_skills("I fix things")

    assert categories == [
        {
            "category_number": "3.3.1",
            "category_name": "PLUMBING",
            "confidence": 1.0,
            "hierarchy": "Housing Assistance > Repair Maintenance Support > Plumbing",
        }
    ]


def test_nan_confidence_is_treated_as_zero():
    assert ss.SkillSuggestionService._normalize_confidence(float("nan")) == 0.0


def test_threshold_is_inclusive_at_the_default(monkeypatch):
    _primary_returns(monkeypatch, {
        "skills": [_skill("3.3.1", 0.5), _skill("3.3.2", 0.49)],
    })

    categories, _, _ = ss.suggest_skills("plumbing, maybe odd jobs")

    assert [c["category_number"] for c in categories] == ["3.3.1"]


def test_results_are_capped_at_six_highest_first(monkeypatch):
    leaves = ["3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.3.5", "3.3.6", "3.3.7", "3.3.8"]
    confidences = [0.55, 0.95, 0.6, 0.9, 0.65, 0.85, 0.7, 0.8]
    _primary_returns(monkeypatch, {
        "skills": [_skill(c, p) for c, p in zip(leaves, confidences)],
    })

    categories, _, _ = ss.suggest_skills("I can fix almost anything in a house")

    assert len(categories) == 6
    assert [c["confidence"] for c in categories] == [0.95, 0.9, 0.85, 0.8, 0.7, 0.65]


def test_threshold_and_cap_are_configurable(monkeypatch):
    monkeypatch.setenv("SKILL_SUGGESTION_MIN_CONFIDENCE", "0.8")
    monkeypatch.setenv("SKILL_SUGGESTION_MAX_RESULTS", "1")
    _primary_returns(monkeypatch, {
        "skills": [_skill("3.3.1", 0.85), _skill("3.3.2", 0.95), _skill("3.3.3", 0.7)],
    })

    categories, _, _ = ss.suggest_skills("I fix things")

    assert [c["category_number"] for c in categories] == ["3.3.2"]


def test_bad_configuration_falls_back_to_the_defaults(monkeypatch):
    monkeypatch.setenv("SKILL_SUGGESTION_MIN_CONFIDENCE", "not a number")
    monkeypatch.setenv("SKILL_SUGGESTION_MAX_RESULTS", "0")

    service = ss.SkillSuggestionService()

    assert service.min_confidence == ss.DEFAULT_MIN_CONFIDENCE
    assert service.max_results == ss.DEFAULT_MAX_RESULTS


def test_unmatched_skills_are_cleaned(monkeypatch):
    _primary_returns(monkeypatch, {
        "skills": [],
        "unmatched_skills": [
            "  accounting ",
            "Accounting",
            "",
            42,
            "Spanish   translation",
            "x" * 200,
            "a", "b", "c", "d",
        ],
    })

    _, unmatched, _ = ss.suggest_skills("I do accounting and Spanish translation")

    assert unmatched[:3] == ["accounting", "Spanish translation", "x" * 60]
    assert len(unmatched) == 6


def test_missing_unmatched_skills_is_an_empty_list(monkeypatch):
    _primary_returns(monkeypatch, {"skills": [_skill("3.3.1", 0.9)]})

    _, unmatched, _ = ss.suggest_skills("plumbing")

    assert unmatched == []


def test_description_is_capped_before_it_reaches_the_model(monkeypatch):
    groq = _primary_returns(monkeypatch, {"skills": []})

    ss.suggest_skills("  " + "a" * 5000 + "  ")

    user_message = groq.calls[0]["messages"][1]["content"]
    assert user_message.count("a") <= ss.MAX_DESCRIPTION_CHARS + 5
    assert "a" * ss.MAX_DESCRIPTION_CHARS in user_message


# ---------------------------------------------------------------------------
# The elderly shortcut does not apply
# ---------------------------------------------------------------------------

def test_retired_volunteer_is_not_routed_to_elderly_care(monkeypatch):
    description = "I'm a retired senior math teacher and I help with algebra and SAT prep."
    # The precondition that makes this test mean something: the help-request
    # classifier WOULD force category 6 for this text.
    assert is_elderly_context(description)

    groq = _primary_returns(monkeypatch, {
        "skills": [_skill("4.3.1", 0.95, "math teacher"), _skill("4.3.5", 0.9, "SAT prep")],
    })

    categories, _, _ = ss.suggest_skills(description)

    assert [c["category_number"] for c in categories] == ["4.3.1", "4.3.5"]
    system_prompt = groq.calls[0]["messages"][0]["content"]
    # The model was offered the whole tree, not just the children of 6.
    for leaf in ("1.3.1", "3.3.1", "4.3.1", "5.3", "6.2"):
        assert f"\n{leaf} | " in system_prompt


# ---------------------------------------------------------------------------
# Model fallback
# ---------------------------------------------------------------------------

def test_no_match_is_a_valid_answer_and_does_not_fail_over(monkeypatch):
    groq = _primary_returns(monkeypatch, {"skills": [], "unmatched_skills": ["accounting"]})

    categories, unmatched, _ = ss.suggest_skills("I am an accountant")

    assert categories == []
    assert unmatched == ["accounting"]
    assert len(groq.calls) == 1


def test_only_filtered_out_results_is_still_a_valid_answer(monkeypatch):
    """General-only output is filtered to nothing; that is 'no match', not an outage."""
    groq = _primary_returns(monkeypatch, {"skills": [_skill("0.0.0.0.0", 0.99)]})

    categories, _, _ = ss.suggest_skills("I like helping")

    assert categories == []
    assert len(groq.calls) == 1


@pytest.mark.parametrize(
    "bad_outcome",
    [
        GroqError("Error code: 404 - model does not exist"),
        _groq_response("not json at all"),
        _groq_response({"categories": [{"category": "3.3.1"}]}),  # wrong key
        _groq_response(["3.3.1"]),
        _groq_response(""),
    ],
)
def test_errors_and_malformed_output_fail_over_to_the_next_model(monkeypatch, bad_outcome):
    primary, secondary = _CONFIGURED_GROQ_MODELS[:2]
    groq = _FakeGroq({
        primary: bad_outcome,
        secondary: _groq_response({"skills": [_skill("3.3.1", 0.9)]}),
    })
    _install(monkeypatch, groq, _FakeGemini(error=AssertionError("unused")))

    categories, _, _ = ss.suggest_skills("I do plumbing")

    assert [c["category_number"] for c in categories] == ["3.3.1"]
    assert [call["model"] for call in groq.calls] == [primary, secondary]
    assert groq.calls[0]["messages"] == groq.calls[1]["messages"]


def test_all_groq_failures_reach_gemini_with_the_same_instructions(monkeypatch):
    groq = _FakeGroq({m: GroqError(f"{m} unavailable") for m in _CONFIGURED_GROQ_MODELS})
    gemini = _FakeGemini(payload={"skills": [_skill("5.1.3", 0.9, "dentist")]})
    _install(monkeypatch, groq, gemini)

    categories, _, usage = ss.suggest_skills("I'm a dentist.")

    assert [c["category_number"] for c in categories] == ["5.1.3"]
    assert [call["model"] for call in groq.calls] == _CONFIGURED_GROQ_MODELS
    assert [call["model"] for call in gemini.calls] == [_CONFIGURED_GEMINI_MODEL]
    config = gemini.calls[0]["config"]
    assert config["system_instruction"] == ss.SYSTEM_PROMPT
    assert config["response_mime_type"] == "application/json"
    assert "I'm a dentist." in gemini.calls[0]["contents"]
    assert usage["calls"][-1]["provider"] == "gemini"


def test_total_outage_is_a_502_through_the_handler(monkeypatch):
    groq = _FakeGroq({m: GroqError(f"{m} unavailable") for m in _CONFIGURED_GROQ_MODELS})
    gemini = _FakeGemini(error=RuntimeError("gemini unavailable"))
    _install(monkeypatch, groq, gemini)

    response = LF.predict_category_handler(_volunteer_event("I can drive people"), None)

    assert response["statusCode"] == 502
    assert response["body"] == {
        "error": "Skill suggestion failed",
        "code": "SKILL_SUGGESTION_UNAVAILABLE",
    }
    # Every provider was really tried: the 502 is not a missing-client accident.
    assert [call["model"] for call in groq.calls] == _CONFIGURED_GROQ_MODELS
    assert len(gemini.calls) == 1


# ---------------------------------------------------------------------------
# The handler contract
# ---------------------------------------------------------------------------

def test_volunteer_mode_response_envelope(monkeypatch):
    _primary_returns(monkeypatch, {
        "skills": [_skill("3.3.3", 0.95, "licensed electrician"), _skill("3.3.1", 0.9, "plumbing")],
        "unmatched_skills": [],
    })

    response = LF.predict_category_handler(
        _volunteer_event("I'm a licensed electrician and I also do some plumbing on weekends."),
        None,
    )

    assert response["statusCode"] == 200
    body = response["body"]
    assert set(body) == {"categories", "unmatched_skills", "token_usage"}
    assert [c["category_number"] for c in body["categories"]] == ["3.3.3", "3.3.1"]
    for item in body["categories"]:
        assert {"category_number", "category_name", "confidence", "hierarchy"} <= set(item)
    assert body["unmatched_skills"] == []
    assert body["token_usage"]["total_calls"] == 1


@pytest.mark.parametrize("mode", ["volunteer_skills", "VOLUNTEER_SKILLS", " volunteer_skills "])
def test_mode_value_is_matched_leniently(mode):
    with mock.patch.object(LF, "suggest_skills", return_value=([], [], {})) as service, \
         mock.patch.object(LF, "predict_categories", side_effect=AssertionError("wrong path")):
        response = LF.predict_category_handler(
            {"body": json.dumps({"description": "I sew", "mode": mode})}, None
        )

    assert response["statusCode"] == 200
    service.assert_called_once_with("I sew")


@pytest.mark.parametrize("description", [None, "", "   ", 42])
def test_volunteer_mode_requires_a_description(description):
    with mock.patch.object(LF, "suggest_skills", side_effect=AssertionError("must not be called")):
        response = LF.predict_category_handler(
            {"body": json.dumps({"description": description, "mode": "volunteer_skills"})}, None
        )

    assert response["statusCode"] == 400
    assert response["body"] == {"error": "Description is required"}


@pytest.mark.parametrize("mode", ["volunteer", "help_request", 1, True, ["volunteer_skills"]])
def test_unknown_mode_is_rejected_rather_than_guessed(mode):
    with mock.patch.object(LF, "suggest_skills", side_effect=AssertionError("wrong path")), \
         mock.patch.object(LF, "predict_categories", side_effect=AssertionError("wrong path")):
        response = LF.predict_category_handler(
            {"body": json.dumps({"description": "I sew", "mode": mode})}, None
        )

    assert response["statusCode"] == 400
    assert response["body"]["error"] == "Unsupported mode"
    assert response["body"]["supported_modes"] == ["volunteer_skills"]


def test_handler_trims_and_caps_the_description():
    with mock.patch.object(LF, "suggest_skills", return_value=([], [], {})) as service:
        LF.predict_category_handler(_volunteer_event("  " + "b" * 3000 + "  "), None)

    sent = service.call_args.args[0]
    assert sent == "b" * ss.MAX_DESCRIPTION_CHARS


def test_unexpected_failure_is_a_generic_500():
    with mock.patch.object(
        LF, "suggest_skills", side_effect=RuntimeError("leaked: I'm a nurse in Austin")
    ):
        response = LF.predict_category_handler(_volunteer_event("I'm a nurse in Austin"), None)

    assert response["statusCode"] == 500
    assert response["body"] == {"error": "Skill suggestion failed"}


def test_router_reaches_suggest_skills_by_service_name(monkeypatch):
    _primary_returns(monkeypatch, {"skills": [_skill("2.4", 0.9, "alterations")]})

    response = LF.lambda_handler(
        {"body": json.dumps({"service": "suggest_skills", "description": "I do alterations"})},
        None,
    )

    assert response["statusCode"] == 200
    assert [c["category_number"] for c in response["body"]["categories"]] == ["2.4"]


def test_suggest_skills_handler_rejects_a_malformed_body():
    response = LF.suggest_skills_handler({"body": "{not json"}, None)

    assert response["statusCode"] == 400


# ---------------------------------------------------------------------------
# Requests without `mode` are unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode_field", [{}, {"mode": None}, {"mode": ""}])
def test_request_without_mode_returns_exactly_what_it_did_before(monkeypatch, mode_field):
    """Create Help Request must not notice that volunteer mode exists.

    This drives the real help-request walk (top level -> 4 -> 4.3 -> leaves)
    against a stubbed model and pins the whole response, token usage included.
    """
    groq = _FakeGroq(sequence=[
        _groq_response({"categories": [{"category": "4", "confidence": 0.9}]}),
        _groq_response({"categories": [{"category": "4.3", "confidence": 0.85}]}),
        _groq_response({"categories": [
            {"category": "4.3.1", "confidence": 0.95},
            {"category": "4.3.5", "confidence": 0.6},
            {"category": "4.3.3", "confidence": 0.4},
            {"category": "4.3.2", "confidence": 0.2},
        ]}),
    ])
    monkeypatch.setattr(cs, "client", groq)
    monkeypatch.setattr(cs, "_use_groq", True)
    monkeypatch.setattr(cs, "_gemini_client", None)
    monkeypatch.setattr(LF, "suggest_skills", mock.Mock(side_effect=AssertionError("volunteer path taken")))

    response = LF.predict_category_handler(
        {"body": json.dumps({"description": "I need help with my algebra homework", **mode_field})},
        None,
    )

    call = {
        "provider": "groq",
        "model": _CONFIGURED_GROQ_MODELS[0],
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert response == {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": {
            "categories": [
                {
                    "category_number": "4.3.1",
                    "category_name": "MATH",
                    "confidence": 0.95,
                    "hierarchy": "Education Career Support > Tutoring > Math",
                },
                {
                    "category_number": "4.3.5",
                    "category_name": "TEST_PREP",
                    "confidence": 0.6,
                    "hierarchy": "Education Career Support > Tutoring > Test Prep",
                },
                {
                    "category_number": "4.3.3",
                    "category_name": "SCIENCE",
                    "confidence": 0.4,
                    "hierarchy": "Education Career Support > Tutoring > Science",
                },
            ],
            "token_usage": {
                "total_calls": 3,
                "total_prompt_tokens": 300,
                "total_completion_tokens": 60,
                "total_tokens": 360,
                "calls": [{**call, "depth": 0}, {**call, "depth": 1}, {**call, "depth": 2}],
            },
        },
    }
    # The help-request prompt, not the volunteer one.
    assert all(len(c["messages"]) == 1 for c in groq.calls)
    assert "zero-shot classifier" in groq.calls[0]["messages"][0]["content"]


def test_request_without_mode_still_reports_its_own_errors():
    with mock.patch.object(LF, "suggest_skills", side_effect=AssertionError("wrong path")):
        response = LF.predict_category_handler({"body": json.dumps({"description": ""})}, None)

    assert response["statusCode"] == 400
    assert response["body"] == {"error": "Description is required"}


# ---------------------------------------------------------------------------
# Privacy: the volunteer's words never reach a log
# ---------------------------------------------------------------------------

_SECRET = "Zanzibar-7731 knitting for my neighbour Mrs Okafor"


def _assert_not_logged(capsys, caplog):
    captured = capsys.readouterr()
    logged = captured.out + captured.err + caplog.text
    assert "Zanzibar" not in logged
    assert "Okafor" not in logged


def test_description_and_evidence_are_not_logged_on_success(monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    _primary_returns(monkeypatch, {
        "skills": [_skill("2.4", 0.9, "knitting for my neighbour Mrs Okafor")],
        "unmatched_skills": ["Zanzibar-7731"],
    })

    response = LF.predict_category_handler(_volunteer_event(_SECRET), None)

    assert response["statusCode"] == 200
    _assert_not_logged(capsys, caplog)


def test_description_is_not_logged_when_models_fail(monkeypatch, capsys, caplog):
    """Failover warnings quote the exception; ours must not quote the text."""
    caplog.set_level(logging.DEBUG)
    groq = _FakeGroq({
        _CONFIGURED_GROQ_MODELS[0]: _groq_response(_SECRET),  # not JSON
        _CONFIGURED_GROQ_MODELS[1]: _groq_response({"evidence": _SECRET}),  # no skills
        _CONFIGURED_GROQ_MODELS[2]: GroqError("rate limited"),
    })
    gemini = _FakeGemini(error=RuntimeError("gemini unavailable"))
    _install(monkeypatch, groq, gemini)

    response = LF.predict_category_handler(_volunteer_event(_SECRET), None)

    assert response["statusCode"] == 502
    assert "MODEL_FAILOVER" in caplog.text  # the failures were logged, just not the text
    _assert_not_logged(capsys, caplog)
