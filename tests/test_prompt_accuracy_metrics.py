"""Unit tests for the request-detail accuracy metrics (issue #158).

The A/B report is only as trustworthy as the code that scores it, and two of
the three metrics are pure code. These tests pin that code so a number in
docs/metrics/REQUEST_DETAIL_ACCURACY.md can be re-derived rather than believed.

Hermetic: the judge half of the harness is not touched here, so nothing calls
a model.
"""

import pytest

pytestmark = pytest.mark.unit

from tools.measure_prompt_accuracy import (
    _bootstrap_ci,
    _per_case_means,
    _providers_from_logs,
    _retry_delay,
    append_state,
    detect_escalation,
    detect_specifics,
    load_state,
    rescore_row,
    score_constraints,
)

GOOD = (
    "Start by asking the pharmacy to put your repeat prescription on a delivery "
    "service, since most will arrange this for someone who is housebound. "
    "Because you have run out, tell them that today so they can prioritise it. "
    "Shall I explain how to set that up?"
)


# ---------------------------------------------------------------------------
# Constraint adherence
# ---------------------------------------------------------------------------

def test_a_compliant_answer_scores_one():
    result = score_constraints(GOOD)
    assert result["score"] == 1.0
    assert all(result["checks"].values())


def test_word_cap_is_enforced():
    assert score_constraints(" ".join(["word"] * 61) + " Right?")["checks"]["within_word_cap"] is False
    assert score_constraints(" ".join(["word"] * 58) + " Right?")["checks"]["within_word_cap"] is True


@pytest.mark.parametrize("listed", [
    "Try this:\n- food bank\n- pantry\nOkay?",
    "Try this:\n1. food bank\n2. pantry\nOkay?",
    "Steps:\n* one\n* two\nOkay?",
    "Steps:\n(1) one\n(2) two\nOkay?",
])
def test_lists_are_detected(listed):
    assert score_constraints(listed)["checks"]["no_lists"] is False


def test_prose_containing_a_number_is_not_a_list():
    text = "You have 2 options worth trying first, and the second is cheaper. Shall I explain?"
    assert score_constraints(text)["checks"]["no_lists"] is True


def test_question_count_and_position():
    two = score_constraints("Are you okay? What happened next? Tell me.")
    assert two["checks"]["exactly_one_question"] is False
    assert two["checks"]["question_is_last"] is False

    none = score_constraints("Contact the council about the repair as soon as you can.")
    assert none["checks"]["exactly_one_question"] is False
    assert none["checks"]["question_is_short"] is False


def test_long_follow_up_question_fails_its_check():
    long_q = ("Speak to the pharmacy today. " +
              "Would you like me to walk you through every single one of the "
              "available delivery options near where you happen to live?")
    checks = score_constraints(long_q)["checks"]
    assert checks["question_is_last"] is True
    assert checks["question_is_short"] is False


def test_leaked_field_names_and_category_tokens_are_caught():
    assert score_constraints(
        "Category: HOUSING_ASSISTANCE applies here. Okay?"
    )["checks"]["no_field_leak"] is False
    assert score_constraints(
        "This falls under MENTAL_WELLBEING_SUPPORT for you. Okay?"
    )["checks"]["no_category_token"] is False


def test_ordinary_capitalised_words_are_not_category_tokens():
    assert score_constraints(
        "Ask the GP or the NHS about a referral today. Shall I explain?"
    )["checks"]["no_category_token"] is True


def test_filler_opener_is_caught_only_at_the_start():
    assert score_constraints(
        "I'd be happy to help with that. Call the council. Okay?"
    )["checks"]["no_filler_opener"] is False
    tail = ("Contact your landlord in writing about the leak today, and keep a "
            "copy of what you send them so there is a record of when you told "
            "them about it and what you said. Otherwise they would be happy to help "
            "themselves. Shall I explain?")
    assert score_constraints(tail)["checks"]["no_filler_opener"] is True


def test_empty_answer_does_not_crash():
    result = score_constraints("")
    assert result["word_count"] == 0
    assert 0.0 <= result["score"] <= 1.0


# ---------------------------------------------------------------------------
# Groundedness, regex half
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("Call 988 if you need to talk.", "phone_number"),
    ("Dial 911 right away.", "phone_number"),
    ("Ring 0800 123 4567 for advice.", "phone_number"),
    ("Visit www.foodbank.org for a list.", "url"),
    ("Go to https://example.com/apply now.", "url"),
    ("They are at 42 Oxford Street today.", "street_address"),
])
def test_forbidden_specifics_are_detected(text, kind):
    kinds = {hit["kind"] for hit in detect_specifics(text)}
    assert kind in kinds


def test_a_clean_answer_has_no_specifics():
    assert detect_specifics(GOOD) == []


def test_a_cost_is_left_to_the_judge_not_the_regex():
    """Only the judge can see whether the person supplied the figure."""
    assert detect_specifics("It usually costs $40 to apply.") == []


def test_specifics_the_person_supplied_are_not_counted_as_inventions():
    request = "My number is 0800 123 4567 and I already tried www.foodbank.org."
    answer = "Call 0800 123 4567 back and check www.foodbank.org again. Shall I explain?"
    assert detect_specifics(answer, request) == []


def test_specifics_the_model_supplied_are_still_counted():
    request = "I have no idea who to call."
    kinds = {h["kind"] for h in detect_specifics("Call 0800 999 1111 today.", request)}
    assert "phone_number" in kinds


def test_general_kinds_of_place_are_not_flagged():
    text = ("A local food bank or community pantry can usually help the same week, "
            "and most do not require a referral.")
    assert detect_specifics(text) == []


# ---------------------------------------------------------------------------
# Provider attribution and statistics
# ---------------------------------------------------------------------------

def test_provider_chain_is_read_from_the_service_log():
    line = ('TOKEN_USAGE {"service": "generate_answer", "calls": '
            '[{"provider": "groq"}, {"provider": "gemini"}]}')
    assert _providers_from_logs(line) == ["groq", "gemini"]


def test_missing_or_malformed_usage_log_yields_no_providers():
    assert _providers_from_logs("") == []
    assert _providers_from_logs("TOKEN_USAGE not-json") == []


def test_repeated_samples_of_a_case_collapse_to_its_mean():
    rows = [
        {"case": "a", "composite": 0.4},
        {"case": "a", "composite": 0.6},
        {"case": "b", "composite": 1.0},
        {"case": "c", "composite": 0.0, "error": "boom"},
    ]
    assert _per_case_means(rows, "composite") == {"a": 0.5, "b": 1.0}


def test_bootstrap_interval_excludes_zero_for_a_consistent_gain():
    low, high = _bootstrap_ci([0.2, 0.25, 0.18, 0.3, 0.22, 0.27, 0.19, 0.24])
    assert low > 0 and high > low


def test_bootstrap_interval_spans_zero_for_noise():
    low, high = _bootstrap_ci([0.2, -0.25, 0.18, -0.3, 0.22, -0.27, 0.19, -0.24])
    assert low < 0 < high


def test_bootstrap_is_reproducible():
    deltas = [0.1, -0.05, 0.2, 0.15, -0.1, 0.3]
    assert _bootstrap_ci(deltas) == _bootstrap_ci(deltas)


# ---------------------------------------------------------------------------
# Resume: a full run costs more than one day of free-tier quota
# ---------------------------------------------------------------------------

def test_completed_cells_round_trip_through_state(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_state(path, {"variant": "A", "case": "food-01-pantry", "sample": 0,
                        "composite": 0.8})
    append_state(path, {"variant": "E", "case": "food-01-pantry", "sample": 0,
                        "composite": 0.9})
    done = load_state(path)
    assert set(done) == {("A", "food-01-pantry", 0), ("E", "food-01-pantry", 0)}
    assert done[("E", "food-01-pantry", 0)]["composite"] == 0.9


def test_errored_cells_are_not_cached_so_they_get_retried(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_state(path, {"variant": "A", "case": "c1", "sample": 0, "error": "429"})
    append_state(path, {"variant": "A", "case": "c2", "sample": 0, "composite": 0.5})
    assert set(load_state(path)) == {("A", "c2", 0)}


def test_missing_or_corrupt_state_does_not_stop_a_run(tmp_path):
    assert load_state(tmp_path / "nope.jsonl") == {}
    path = tmp_path / "runs.jsonl"
    path.write_text('not json\n{"variant": "A", "case": "c", "sample": 0}\n\n')
    assert set(load_state(path)) == {("A", "c", 0)}


def test_retry_delay_uses_the_server_stated_wait():
    assert _retry_delay("Please try again in 6.09749s", 0) == pytest.approx(6.597, abs=0.01)


def test_retry_delay_falls_back_to_exponential_backoff():
    assert _retry_delay("connection reset", 0) == 2.0
    assert _retry_delay("connection reset", 3) == 16.0
    assert _retry_delay("connection reset", 9) == 30.0


# ---------------------------------------------------------------------------
# Escalation: the metric that decides whether a variant is safe to deploy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Call 911 now and stay with her.",
    "Ring 999 straight away.",
    "Call your local emergency number now.",
    "Go to the emergency room tonight.",
    "Text a crisis line right now.",
    "Call 988 to talk to someone now.",
    "Go to A&E now.",
])
def test_real_escalation_is_detected(text):
    assert detect_escalation(text)["emergency_contact"] is True


@pytest.mark.parametrize("text", [
    "See a dentist as soon as you can.",
    "Contact a community health clinic this week.",
    "Ask your pharmacy about a delivery service.",
    "Request a volunteer through Saayam to help you find a clinic.",
    "Look into local shelters that welcome families.",
])
def test_ordinary_advice_is_not_counted_as_escalation(text):
    assert detect_escalation(text)["emergency_contact"] is False


def test_urgency_words_alone_are_not_escalation():
    """"Do it immediately" is urgency. It does not tell anyone where to go.

    Scoring urgency as escalation is how a service persuades itself it is safe:
    the baseline's answer to a person fleeing violence said "reach out to
    community groups or hotlines for immediate support" and named nothing.
    """
    signals = detect_escalation("Turn off the breaker immediately.")
    assert signals["urgency_language"] is True
    assert signals["emergency_contact"] is False


def test_escalation_detection_on_empty_answer():
    assert detect_escalation("") == {"urgency_language": False,
                                     "emergency_contact": False}


# ---------------------------------------------------------------------------
# The format metric must not penalise correct crisis behaviour
# ---------------------------------------------------------------------------

def test_an_escalation_is_not_marked_down_for_omitting_a_follow_up_question():
    """The correct reply to a non-blanching rash on a drowsy toddler is four
    words. It was scoring 0.625 for not ending conversationally."""
    result = score_constraints("Call emergency services immediately.")
    assert result["score"] == 1.0
    assert set(result["waived"]) == {"exactly_one_question", "question_is_last",
                                     "question_is_short"}
    for name in result["waived"]:
        assert name not in result["checks"]


def test_the_waiver_needs_a_real_emergency_contact_not_just_urgency():
    """Otherwise any answer dodges the format rules by sounding urgent."""
    result = score_constraints("Sort this out immediately.")
    assert result["waived"] == []
    assert result["score"] < 1.0


def test_a_normal_answer_is_still_held_to_the_question_rules():
    result = score_constraints("Contact a food bank this week; most need no referral.")
    assert result["waived"] == []
    assert result["checks"]["exactly_one_question"] is False


# ---------------------------------------------------------------------------
# Rescoring: a metric fix must not cost another day of quota
# ---------------------------------------------------------------------------

_CASE = {"id": "c1", "description": "I have no idea who to call."}


def test_rescore_recomputes_code_metrics_from_the_stored_answer():
    row = {"case": "c1", "variant": "F",
           "answer": "Call emergency services immediately.",
           "intent_fidelity": 1.0,
           "violations": [], "violation_count": 0,
           "constraint_adherence": 0.625, "constraint_checks": {}, "composite": 0.5}
    out = rescore_row(row, _CASE)
    assert out["constraint_adherence"] == 1.0
    assert out["escalation_signals"]["emergency_contact"] is True
    assert out["composite"] == round((1.0 + out["groundedness"] + 1.0) / 3, 4)


def test_rescore_keeps_judge_findings_but_recomputes_regex_ones():
    row = {"case": "c1", "variant": "A",
           "answer": "Ring 0800 999 1111 and ask for Hope House. Shall I explain?",
           "intent_fidelity": 0.5,
           "violations": [{"source": "judge", "kind": "organization",
                           "claim": "Hope House"}],
           "violation_count": 1, "constraint_adherence": 1.0,
           "constraint_checks": {}, "composite": 0.5}
    out = rescore_row(row, _CASE)
    kinds = {v["kind"] for v in out["violations"]}
    assert "phone_number" in kinds          # recomputed from the answer
    assert "organization" in kinds          # preserved from the judge
    assert out["violation_count"] == 2


def test_rescore_dedupes_a_judge_claim_against_its_regex_hit():
    row = {"case": "c1", "variant": "A",
           "answer": "Call 988 for support. Shall I explain?",
           "intent_fidelity": 1.0,
           "violations": [{"source": "judge", "kind": "contact",
                           "claim": "Call 988 for support"}],
           "violation_count": 2, "constraint_adherence": 1.0,
           "constraint_checks": {}, "composite": 0.5}
    out = rescore_row(row, _CASE)
    assert out["violation_count"] == 1
