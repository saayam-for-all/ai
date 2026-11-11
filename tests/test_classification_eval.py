"""Scoring, gating, fingerprinting and reporting in evaluation/ (issue #197, stack 5).

Every test here stubs the classifier: the subject is the evaluation logic, not
the model. The question each test answers is "would the gate say the right
thing about this run?".
"""

import json

import pytest

import services.classification_service as cs
from evaluation import classification_eval as ev
from evaluation.golden_set import GoldenCase, GoldenSetError, load_golden_set
from utils import routing_for_categories

pytestmark = pytest.mark.unit


def _case(case_id="c1", expected="PLUMBING", tags=(), description="My sink leaks."):
    return GoldenCase(id=case_id, description=description, expected=expected, tags=tuple(tags))


def _answers(*category_numbers, tokens=10):
    """A stub classifier that always returns the given ranked ids."""
    def classify(_description):
        ranked = [{"category_number": cid} for cid in category_numbers]
        usage = {"total_tokens": tokens, "calls": [{"provider": "groq", "model": "m"}]}
        return ranked, usage
    return classify


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _write(tmp_path, *lines):
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


GOOD = '{"id": "a", "description": "sink leaks", "expected": "PLUMBING", "tags": []}'


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("not json", "not valid JSON"),
        ('["a list"]', "JSON object"),
        ('{"id": "", "description": "x", "expected": "PLUMBING"}', "'id'"),
        ('{"id": "b", "description": " ", "expected": "PLUMBING"}', "'description'"),
        ('{"id": "b", "description": "x", "expected": "PLUMBER"}', "not a category name"),
        ('{"id": "b", "description": "x", "expected": "PLUMBING", "tags": "x"}', "'tags'"),
        ('{"id": "b", "description": "x", "expected": "PLUMBING", "tags": ["known-gap"]}', "use null"),
    ],
)
def test_loader_rejects_a_malformed_case_and_names_the_line(tmp_path, line, message):
    """Each kind of bad line is refused with a message saying what and where.

    A label typo such as PLUMBER must be an error, not a case that silently
    can never pass.
    """
    with pytest.raises(GoldenSetError, match=message) as raised:
        load_golden_set(_write(tmp_path, GOOD, line))
    assert "line 2" in str(raised.value)


def test_loader_rejects_duplicate_ids(tmp_path):
    """Two cases with one id would make a report row ambiguous."""
    with pytest.raises(GoldenSetError, match="duplicate id 'a'"):
        load_golden_set(_write(tmp_path, GOOD, GOOD))


def test_loader_rejects_a_file_with_only_known_gaps(tmp_path):
    """A set with nothing to score would pass any gate with 0/0."""
    gap = '{"id": "g", "description": "taxes", "expected": null, "tags": ["known-gap"]}'
    with pytest.raises(GoldenSetError, match="no scored cases"):
        load_golden_set(_write(tmp_path, gap))


def test_loader_skips_blank_lines(tmp_path):
    """Blank lines are allowed so the file can be grouped by hand."""
    assert [c.id for c in load_golden_set(_write(tmp_path, "", GOOD, ""))] == ["a"]


# ---------------------------------------------------------------------------
# Scoring one case
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("category_id", "expected"),
    [("3.3.1", "3"), ("3", "3"), ("0.0.0.0.0", "0"), (None, None), ("", None)],
)
def test_top_level_of_reads_the_branch(category_id, expected):
    """The branch is the first id segment; the dotted general id is branch 0."""
    assert ev.top_level_of(category_id) == expected


def test_exact_answer_scores_on_both_measures():
    """The expected leaf ranked first is right on branch and on path."""
    result = ev.run_case(_case(), _answers("3.3.1", "3.3.2"))
    assert result.top_level_ok and result.path_ok
    assert result.predicted_names[0] == "PLUMBING"


def test_right_branch_wrong_leaf_is_a_detail_miss():
    """HANDYMAN for a plumbing case is the right branch but the wrong category."""
    result = ev.run_case(_case(), _answers("3.3.2", "3.3.4", "3.3.5"))
    assert result.top_level_ok and not result.path_ok


def test_expected_category_lower_in_the_top_three_still_counts_for_path():
    """Path accuracy looks at the top three, the branch only at the first answer."""
    result = ev.run_case(_case(), _answers("5.1.1", "3.3.1"))
    assert not result.top_level_ok and result.path_ok


def test_a_parent_label_accepts_any_of_its_children():
    """MEDICAL_CONSULTATION passes for CARDIAC_OR_BLOOD_PRESSURE (5.1.5)."""
    result = ev.run_case(_case(expected="MEDICAL_CONSULTATION"), _answers("5.1.5"))
    assert result.top_level_ok and result.path_ok


def test_a_sibling_with_a_shared_prefix_is_not_a_child():
    """3.3.10 is not inside 3.3.1: prefix matching must respect the dot."""
    result = ev.run_case(_case(), _answers("3.3.10"))
    assert result.top_level_ok and not result.path_ok


def test_empty_answer_is_wrong_not_an_error():
    """No categories back is a wrong answer; the run itself did not fail."""
    result = ev.run_case(_case(), _answers())
    assert not result.top_level_ok and result.error is None


def test_classifier_exception_is_recorded_not_raised():
    """One failing case must not abort a paid run; the error is kept on the result."""
    def explode(_description):
        raise RuntimeError("rate limited")
    result = ev.run_case(_case(), explode)
    assert result.error == "RuntimeError: rate limited"


def test_models_and_tokens_are_taken_from_the_usage_record():
    """The report says which model answered and what the case cost."""
    result = ev.run_case(_case(), _answers("3.3.1", tokens=42))
    assert result.models == ["groq/m"] and result.total_tokens == 42


def test_elderly_routing_is_recorded_per_case():
    """The router decision is recorded, so a miss can be attributed to it."""
    result = ev.run_case(_case(description="Our aging roof leaks."), _answers("6.5"))
    assert result.elderly_routed


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def _scripted(*category_numbers):
    """A stub classifier that returns the next scripted id on each call."""
    answers = iter(category_numbers)
    return lambda _description: ([{"category_number": next(answers)}], {})


def test_gate_passes_at_the_mark_and_fails_below_it():
    """9/10 passes a 90% mark; 8/10 does not."""
    cases = [_case(case_id=f"c{i}") for i in range(10)]
    nine = ev.evaluate(cases, _scripted(*["3.3.1"] * 9, "1.1"), pass_mark=0.9)
    eight = ev.evaluate(cases, _scripted(*["3.3.1"] * 8, "1.1", "1.1"), pass_mark=0.9)
    assert nine.passed and nine.top_level_accuracy == 0.9
    assert not eight.passed


def test_any_error_fails_the_gate_even_above_the_mark():
    """An unanswered case is not a correct case, whatever the rest scored."""
    outcomes = iter([None, RuntimeError("down")])
    def classify(_description):
        outcome = next(outcomes)
        if outcome:
            raise outcome
        return [{"category_number": "3.3.1"}], {}
    report = ev.evaluate([_case("a"), _case("b")], classify, pass_mark=0.5)
    assert report.top_level_accuracy == 0.5 and report.errors and not report.passed


def test_known_gaps_are_run_but_never_scored():
    """A gap case changes neither the score nor the gate."""
    cases = [_case(), _case("gap", expected=None, tags=["known-gap"])]
    report = ev.evaluate(cases, _answers("3.3.1"))
    assert len(report.results) == 2 and len(report.scored) == 1 and report.passed


def test_by_branch_counts_correct_and_total_per_expected_branch():
    """The per-branch table counts by the label's branch, not the answer's."""
    report = ev.evaluate([_case("a"), _case("b", expected="FOOD_ASSISTANCE")], _answers("3.3.1"))
    assert report.by_branch() == {"HOUSING_ASSISTANCE": (1, 1), "FOOD_AND_ESSENTIALS": (0, 1)}


def test_by_branch_names_the_general_branch():
    """General's id is 0.0.0.0.0, so its branch must not be reported as "?"."""
    report = ev.evaluate([_case(expected="GENERAL_CATEGORY")], _answers("0.0.0.0.0"))
    assert report.by_branch() == {"GENERAL_CATEGORY": (1, 1)}


def test_report_serialises_to_json_with_its_summary():
    """A report's JSON form carries the summary that check_results reads."""
    data = json.loads(json.dumps(ev.evaluate([_case()], _answers("3.3.1")).to_dict()))
    assert data["passed"] is True and data["scored_cases"] == 1
    assert data["fingerprint"] == ev.fingerprint() and data["models"] == {"groq/m": 1}


def test_markdown_lists_misses_and_gaps():
    """The human report names each miss, why it missed, and where gaps landed."""
    cases = [_case(), _case("gap", expected=None, tags=["known-gap"])]
    text = ev.render_markdown(ev.evaluate(cases, _answers("1.1")))
    assert "FAILED" in text
    assert "| `c1` | PLUMBING | FOOD_ASSISTANCE | branch |" in text
    assert "| `gap` | FOOD_ASSISTANCE |" in text


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_is_stable_between_calls():
    """Same code, same fingerprint; otherwise every run would look stale."""
    assert ev.fingerprint() == ev.fingerprint()


def test_any_prompt_edit_changes_the_fingerprint(monkeypatch):
    """A one-character change to the prompt the walk sends changes the fingerprint.

    #197's example was dropping "electrician" from the routing hint: the rest
    of the suite passes with that edit. The fingerprint changes, which is what
    makes the committed live result stale and fails the gate test. The edit
    here is an appended character, so this test does not depend on the hint's
    current wording.
    """
    before = ev.fingerprint()
    original = cs.GroqClassificationService._build_ranked_prompt_for_candidates
    def edited(self, description, candidates):
        return original(self, description, candidates) + "."
    monkeypatch.setattr(cs.GroqClassificationService, "_build_ranked_prompt_for_candidates", edited)
    assert ev.fingerprint() != before


def test_answer_shaping_code_is_part_of_the_fingerprint(monkeypatch):
    """Changing how a model reply becomes the ranked answer needs a fresh run.

    De-duplicating categories changed live answers without touching any
    prompt; before this was fingerprinted, the old score would still have
    been accepted.
    """
    before = ev.fingerprint()
    def reparsed(self, response_data, candidate_set):
        return []
    monkeypatch.setattr(cs.GroqClassificationService, "_parse_ranked_categories", reparsed)
    assert ev.fingerprint() != before


def test_router_word_lists_are_part_of_the_fingerprint(monkeypatch):
    """Changing where the walk starts changes answers, so it needs a fresh run."""
    before = ev.fingerprint()
    monkeypatch.setattr(
        routing_for_categories, "STRONG_ELDERLY_TRIGGERS",
        tuple(w for w in routing_for_categories.STRONG_ELDERLY_TRIGGERS if w != "aging"),
    )
    assert ev.fingerprint() != before


def test_relabelling_the_golden_set_changes_the_fingerprint(monkeypatch, tmp_path):
    """A score measured against old labels does not describe the new ones."""
    before = ev.fingerprint()
    relabelled = tmp_path / "golden.jsonl"
    relabelled.write_text(
        ev.GOLDEN_SET_PATH.read_text(encoding="utf-8").replace('"PLUMBING"', '"HANDYMAN"'),
        encoding="utf-8",
    )
    monkeypatch.setattr(ev, "GOLDEN_SET_PATH", relabelled)
    assert ev.fingerprint() != before


def test_check_results_reports_a_missing_result(tmp_path):
    """No committed result is itself a failure, with the command to fix it."""
    problems = ev.check_results(tmp_path / "absent.json")
    assert len(problems) == 1 and "tools/run_golden_set.py" in problems[0]


def test_check_results_reports_a_stale_and_a_failed_result(tmp_path):
    """A result measured elsewhere, that also failed, yields both problems."""
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"fingerprint": "000000000000", "passed": False}), encoding="utf-8")
    problems = ev.check_results(path)
    assert len(problems) == 2
    assert "changed since the last live evaluation" in problems[0]
    assert "did not pass" in problems[1]
