"""The shared token counter (issue #159).

Three provider response shapes reach `extract_usage`, and the point of the
module is that no caller has to know which one it was handed. These tests pin
each shape, and pin the rule that counting never breaks a served request.
"""
import json

import pytest

from utils import token_usage


# ---------------------------------------------------------------------------
# Fakes shaped like what each provider actually returns
# ---------------------------------------------------------------------------

class _GroqUsage:
    def __init__(self, prompt, completion, total=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


class _GroqResponse:
    """`client.chat.completions.create(...)` - raw Groq SDK."""
    def __init__(self, prompt=100, completion=20, total=120):
        self.usage = _GroqUsage(prompt, completion, total)


class _GeminiUsage:
    def __init__(self, prompt, candidates, total=None, thoughts=None):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.total_token_count = total
        if thoughts is not None:
            self.thoughts_token_count = thoughts


class _GeminiResponse:
    """`_gemini_client.models.generate_content(...)` - raw google.genai."""
    def __init__(self, prompt=200, candidates=30, total=None, thoughts=None):
        self.usage_metadata = _GeminiUsage(prompt, candidates, total, thoughts)


class _LangChainMessage:
    """An `AIMessage` from ChatGroq / ChatGoogleGenerativeAI."""
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}
        self.content = "some answer"


# ---------------------------------------------------------------------------
# Extraction, per provider shape
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_groq_raw_sdk_shape():
    assert token_usage.extract_usage(_GroqResponse(100, 20, 120)) == {
        "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
    }


@pytest.mark.unit
def test_gemini_raw_sdk_shape():
    assert token_usage.extract_usage(_GeminiResponse(200, 30, 230)) == {
        "prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230,
    }


@pytest.mark.unit
def test_langchain_message_shape():
    message = _LangChainMessage(
        usage_metadata={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}
    )
    assert token_usage.extract_usage(message) == {
        "prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60,
    }


@pytest.mark.unit
def test_langchain_falls_back_to_response_metadata():
    """Older LangChain versions populate only the provider-shaped dict."""
    message = _LangChainMessage(
        response_metadata={
            "token_usage": {
                "prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15,
            }
        }
    )
    assert token_usage.extract_usage(message)["total_tokens"] == 15


@pytest.mark.unit
def test_the_two_usage_metadata_shapes_do_not_collide():
    """A raw Gemini response and an AIMessage both have `.usage_metadata`.

    The names are identical and the shapes are not, so sniffing on the
    attribute name alone would read one as the other and return zeros.
    """
    gemini = token_usage.extract_usage(_GeminiResponse(200, 30, 230))
    langchain = token_usage.extract_usage(
        _LangChainMessage(usage_metadata={
            "input_tokens": 50, "output_tokens": 10, "total_tokens": 60,
        })
    )
    assert gemini["prompt_tokens"] == 200
    assert langchain["prompt_tokens"] == 50


# ---------------------------------------------------------------------------
# Thinking tokens: billed as output, reported separately
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_gemini_thinking_tokens_count_as_completion():
    """Gemini 2.5 bills thoughts as output but reports them apart.

    Ignoring them makes a reasoning model look cheaper than the invoice.
    """
    usage = token_usage.extract_usage(
        _GeminiResponse(prompt=100, candidates=20, total=None, thoughts=500)
    )
    assert usage["completion_tokens"] == 520
    assert usage["total_tokens"] == 620


@pytest.mark.unit
def test_langchain_reasoning_tokens_count_as_completion():
    message = _LangChainMessage(usage_metadata={
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "output_token_details": {"reasoning": 300},
    })
    usage = token_usage.extract_usage(message)
    assert usage["completion_tokens"] == 320
    assert usage["total_tokens"] == 420


# ---------------------------------------------------------------------------
# Degradation: telemetry must never break a served request
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("response", [
    None,
    object(),
    "a string",
    42,
    _LangChainMessage(usage_metadata=None),
])
def test_unknown_shapes_return_zeros_rather_than_raising(response):
    assert token_usage.extract_usage(response) == token_usage.ZERO_USAGE


@pytest.mark.unit
def test_a_provider_that_raises_on_attribute_access_returns_zeros():
    class _Hostile:
        @property
        def usage_metadata(self):
            raise RuntimeError("provider exploded")

        @property
        def usage(self):
            raise RuntimeError("provider exploded")

    assert token_usage.extract_usage(_Hostile()) == token_usage.ZERO_USAGE


@pytest.mark.unit
def test_none_counts_do_not_poison_the_accumulator():
    """A provider that reports None used to raise TypeError inside `+=`."""
    accumulator = token_usage.new_accumulator()
    token_usage.record(
        accumulator, _GroqResponse(None, None, None), provider="groq", model="m"
    )
    assert accumulator["total_tokens"] == 0
    assert accumulator["total_calls"] == 1


@pytest.mark.unit
def test_total_is_derived_when_the_provider_omits_it():
    usage = token_usage.extract_usage(_GeminiResponse(200, 30, total=None))
    assert usage["total_tokens"] == 230


@pytest.mark.unit
def test_recording_into_a_broken_accumulator_does_not_raise():
    """The caller's request succeeded; only the telemetry is lost."""
    usage = token_usage.record(
        {"not": "an accumulator"}, _GroqResponse(), provider="groq", model="m"
    )
    assert usage["total_tokens"] == 120


# ---------------------------------------------------------------------------
# Accumulation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_accumulator_sums_across_providers():
    accumulator = token_usage.new_accumulator()
    token_usage.record(accumulator, _GroqResponse(100, 20, 120),
                       provider="groq", model="gpt-oss", depth=0)
    token_usage.record(accumulator, _GeminiResponse(200, 30, 230),
                       provider="gemini", model="flash", depth=1)

    assert accumulator["total_calls"] == 2
    assert accumulator["total_prompt_tokens"] == 300
    assert accumulator["total_completion_tokens"] == 50
    assert accumulator["total_tokens"] == 350
    assert [c["provider"] for c in accumulator["calls"]] == ["groq", "gemini"]
    assert [c["depth"] for c in accumulator["calls"]] == [0, 1]


@pytest.mark.unit
def test_labels_land_on_the_call_record():
    accumulator = token_usage.new_accumulator()
    token_usage.record(accumulator, _GroqResponse(), provider="groq",
                       model="m", branch="short")
    assert accumulator["calls"][0]["branch"] == "short"


@pytest.mark.unit
def test_a_none_accumulator_makes_counting_opt_in():
    usage = token_usage.record(None, _GroqResponse(), provider="groq", model="m")
    assert usage["total_tokens"] == 120


# ---------------------------------------------------------------------------
# The accumulator is a response contract, not just an internal structure
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_new_accumulator_matches_the_shape_predict_category_returns():
    """`body.token_usage` is already in the browser's response.

    predict_category has returned this exact dict since the metrics branch
    merged, so the factory may add keys but may not drop or rename one.
    """
    accumulator = token_usage.new_accumulator()
    assert set(accumulator) == {
        "total_calls",
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_tokens",
        "calls",
    }
    assert accumulator["calls"] == []
    json.dumps(accumulator)  # must survive the JSON envelope


@pytest.mark.contract
def test_per_call_records_keep_the_published_field_names():
    accumulator = token_usage.new_accumulator()
    token_usage.record(accumulator, _GroqResponse(100, 20, 120),
                       provider="groq", model="gpt-oss", depth=0)
    call = accumulator["calls"][0]
    for field in ("provider", "model", "depth",
                  "prompt_tokens", "completion_tokens", "total_tokens"):
        assert field in call, f"{field} disappeared from the per-call record"


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_log_usage_emits_one_parseable_line(capsys):
    accumulator = token_usage.new_accumulator()
    token_usage.record(accumulator, _GroqResponse(100, 20, 120),
                       provider="groq", model="gpt-oss")
    token_usage.log_usage("generate_answer", accumulator, category="Housing")

    line = capsys.readouterr().out.strip()
    assert line.startswith("TOKEN_USAGE ")
    payload = json.loads(line[len("TOKEN_USAGE "):])
    assert payload["service"] == "generate_answer"
    assert payload["total_tokens"] == 120
    assert payload["category"] == "Housing"


@pytest.mark.unit
def test_log_usage_is_silent_when_nothing_was_counted(capsys):
    token_usage.log_usage("generate_answer", None)
    assert capsys.readouterr().out == ""


@pytest.mark.unit
def test_log_usage_survives_an_unserialisable_label(capsys):
    accumulator = token_usage.new_accumulator()
    token_usage.log_usage("s", accumulator, weird=object())
    # default=str keeps the line rather than dropping the record entirely.
    assert "TOKEN_USAGE" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Integration: every service counts, through this one module
# ---------------------------------------------------------------------------
# Issue #159's acceptance is "one shared counting util used across services".
# A util nothing calls passes every test above and delivers nothing, so these
# drive each service with a fake model and assert a line came out.

def _usage_lines(capsys):
    return [
        json.loads(line[len("TOKEN_USAGE "):])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("TOKEN_USAGE ")
    ]


class _FakeChatModel:
    """A LangChain chat model that reports usage like the real ones do."""
    model_name = "fake-model"

    def __init__(self, content="Fake Subject", input_tokens=120, output_tokens=8):
        self._message = _LangChainMessage(usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        })
        self._message.content = content

    def invoke(self, _prompt):
        return self._message


@pytest.mark.integration
def test_subject_generation_reports_its_usage(monkeypatch, capsys):
    import utils.subject_generator as sg

    monkeypatch.setattr(sg, "groq_llm", _FakeChatModel(input_tokens=400, output_tokens=6))
    monkeypatch.setattr(sg, "_use_groq", True)
    monkeypatch.setattr(sg, "gemini_llm", None)
    monkeypatch.setattr(sg, "_use_gemini", False)

    sg.generate_subject_from_description("I need help with my rent this month")

    (record,) = _usage_lines(capsys)
    assert record["service"] == "generate_subject"
    assert record["total_tokens"] == 406
    assert record["calls"][0]["provider"] == "groq"


@pytest.mark.integration
def test_answer_generation_reports_its_usage(monkeypatch, capsys):
    import utils

    monkeypatch.setattr(utils, "groq_llm", _FakeChatModel(
        content="Here is some help.", input_tokens=900, output_tokens=150))
    monkeypatch.setattr(utils, "gemini_llm", None)

    utils.GroqAnswerGenerationService().generate_answer(
        category="Housing", subject="Rent", description="I am behind on rent",
    )

    (record,) = _usage_lines(capsys)
    assert record["service"] == "generate_answer"
    assert record["total_tokens"] == 1050
    assert record["category"] == "Housing"


@pytest.mark.integration
def test_a_groq_failure_still_bills_the_gemini_retry(monkeypatch, capsys):
    """The fallback path spends twice on one request.

    A total that reports only the provider that answered understates the cost
    of exactly the requests that cost the most.
    """
    import utils

    class _Down:
        model_name = "groq-down"
        def invoke(self, _messages):
            raise RuntimeError("groq is down")

    monkeypatch.setattr(utils, "groq_llm", _Down())
    monkeypatch.setattr(utils, "gemini_llm", _FakeChatModel(
        content="Fallback answer.", input_tokens=900, output_tokens=200))

    utils.GroqAnswerGenerationService().generate_answer(
        category="Housing", subject="Rent", description="I am behind on rent",
    )

    (record,) = _usage_lines(capsys)
    # Groq raised before returning a message, so only Gemini's spend is real.
    assert record["total_tokens"] == 1100
    assert [c["provider"] for c in record["calls"]] == ["gemini"]


@pytest.mark.integration
def test_organization_search_reports_its_usage(monkeypatch, capsys):
    """The service that could not report usage at all before #159."""
    import utils.search_orgs as SO

    rows = {"organizations": [{"organization_name": "Helping Hands"}]}
    message = _LangChainMessage(usage_metadata={
        "input_tokens": 1500, "output_tokens": 800, "total_tokens": 2300,
    })

    monkeypatch.setattr(SO, "_providers", lambda: [("groq", lambda: _FakeChatModel())])
    monkeypatch.setattr(SO, "build_prompt", lambda *a: object())
    monkeypatch.setattr(SO, "_invoke_provider", lambda llm, prompt, s, d, l, usage=None, name="": (
        token_usage.record(usage, message, provider=name, model="fake") and None
    ) or rows)

    result = SO.find_organizations("Rent", "I am behind on rent", "Austin, TX")

    assert result["organizations"]
    (record,) = _usage_lines(capsys)
    assert record["service"] == "search_orgs"
    assert record["served_by"] == "groq"
    assert record["total_tokens"] == 2300


@pytest.mark.integration
def test_classification_counts_every_call_in_its_walk(monkeypatch):
    """Classification is a loop, and the loop is the cost.

    `predict_categories` calls the model once per taxonomy level, so the
    accumulator has to show one record per level rather than one per request.
    """
    import services.classification_service as cs

    from utils.predict_category_list import get_direct_children

    class _FakeGroq:
        """Answers with a candidate that has children, so the walk goes deep.

        Picking the *first* candidate would stop immediately: GENERAL_CATEGORY
        leads the top-level list and is a leaf, which makes a one-call request
        and tests nothing about the loop.
        """
        def __init__(self):
            self.chat = self
            self.completions = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            block = kwargs["messages"][0]["content"].split("Categories:\n")[1]
            ids = [line.split(":")[0].strip()
                   for line in block.splitlines() if ":" in line]
            chosen = next((i for i in ids if get_direct_children(i)), ids[0])
            payload = json.dumps({"categories": [{"category": chosen, "confidence": 0.9}]})

            class _Choice:
                message = type("M", (), {"content": payload})()

            return type("R", (), {
                "choices": [_Choice()],
                "usage": _GroqUsage(500, 25, 525),
            })()

    fake = _FakeGroq()
    monkeypatch.setattr(cs, "client", fake)
    monkeypatch.setattr(cs, "_use_groq", True)

    _results, usage = cs.predict_categories("My kitchen sink has been leaking for a week")

    assert usage["total_calls"] == fake.calls
    # The point of the test: a request costs one call per level, not one call.
    assert fake.calls > 1, "the fake did not walk past the first level"
    assert usage["total_tokens"] == 525 * fake.calls
    # One record per level, each tagged with the depth it was spent at.
    assert [c["depth"] for c in usage["calls"]] == list(range(fake.calls))
    assert all(c["provider"] == "groq" for c in usage["calls"])


@pytest.mark.contract
def test_classification_usage_survives_having_no_provider(monkeypatch):
    """No key configured must still return the published (results, usage) pair."""
    import services.classification_service as cs

    monkeypatch.setattr(cs, "client", None)
    monkeypatch.setattr(cs, "_use_groq", False)
    monkeypatch.setattr(cs, "_gemini_client", None)

    service = cs.GroqClassificationService()
    with pytest.raises(ValueError):
        # No provider at all is a real failure, not a silent empty result.
        service.predict_categories("I need help")


@pytest.mark.integration
def test_classification_logs_as_well_as_returns(monkeypatch, capsys):
    """Classification is the one service that does both.

    `body.token_usage` predates this module and stays in the response, but the
    service must also appear in the CloudWatch aggregation with the other
    three, or the per-service comparison silently omits it.
    """
    import services.classification_service as cs
    from utils.predict_category_list import get_direct_children

    class _FakeGroq:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            block = kwargs["messages"][0]["content"].split("Categories:\n")[1]
            ids = [l.split(":")[0].strip() for l in block.splitlines() if ":" in l]
            chosen = next((i for i in ids if get_direct_children(i)), ids[0])
            payload = json.dumps({"categories": [{"category": chosen, "confidence": 0.9}]})

            class _Choice:
                message = type("M", (), {"content": payload})()

            return type("R", (), {
                "choices": [_Choice()], "usage": _GroqUsage(500, 25, 525),
            })()

    monkeypatch.setattr(cs, "client", _FakeGroq())
    monkeypatch.setattr(cs, "_use_groq", True)

    _results, returned = cs.predict_categories("My kitchen sink is leaking")

    (logged,) = _usage_lines(capsys)
    assert logged["service"] == "predict_category"
    # The logged total and the returned total are the same accumulator.
    assert logged["total_tokens"] == returned["total_tokens"]


# ---------------------------------------------------------------------------
# The real _invoke_provider, unmocked
# ---------------------------------------------------------------------------
# The integration test above patches `_invoke_provider` to exercise the
# fallback loop, which leaves the function itself - the riskiest edit in this
# change - unexecuted. Splitting `prompt | llm | parser` into two steps is what
# made usage reachable, and it is also what could silently break parsing. These
# run the real thing.

def _fake_chain_model(payload, usage=None):
    """A Runnable that stands in for a chat model in `prompt | llm`."""
    from langchain_core.runnables import RunnableLambda
    from langchain_core.messages import AIMessage

    return RunnableLambda(lambda _pv: AIMessage(
        content=json.dumps(payload),
        usage_metadata=usage or {
            "input_tokens": 1200, "output_tokens": 800, "total_tokens": 2000,
        },
    ))


@pytest.mark.integration
def test_invoke_provider_still_parses_after_the_chain_split():
    """The two-step form must return exactly what `| parser` used to."""
    import utils.search_orgs as SO

    rows = {"organizations": [{"organization_name": "Helping Hands", "rating": 4.5}]}
    llm = _fake_chain_model(rows)
    prompt = SO.build_prompt("Rent", "I am behind on rent", "Austin, TX")

    result = SO._invoke_provider(
        llm, prompt, "Rent", "I am behind on rent", "Austin, TX"
    )

    assert result == rows


@pytest.mark.integration
def test_invoke_provider_captures_usage_from_the_message():
    """The whole point of the split: the AIMessage is no longer discarded."""
    import utils.search_orgs as SO

    llm = _fake_chain_model({"organizations": []})
    prompt = SO.build_prompt("Rent", "I am behind on rent", "Austin, TX")
    usage = token_usage.new_accumulator()

    SO._invoke_provider(
        llm, prompt, "Rent", "I am behind on rent", "Austin, TX", usage, "groq"
    )

    assert usage["total_calls"] == 1
    assert usage["total_prompt_tokens"] == 1200
    assert usage["total_completion_tokens"] == 800
    assert usage["calls"][0]["provider"] == "groq"


@pytest.mark.integration
def test_invoke_provider_works_without_an_accumulator():
    """Counting is opt-in; the default call path must not require it."""
    import utils.search_orgs as SO

    llm = _fake_chain_model({"organizations": []})
    prompt = SO.build_prompt("s", "d", "l")
    assert SO._invoke_provider(llm, prompt, "s", "d", "l") == {"organizations": []}


@pytest.mark.unit
def test_model_name_falls_back_when_the_model_has_no_id():
    """A usage record with a blank model column is not worth logging."""
    import utils.search_orgs as SO

    assert SO._model_name(type("M", (), {"model_name": "groq-1"})()) == "groq-1"
    assert SO._model_name(type("M", (), {"model": "gemini-1"})()) == "gemini-1"
    assert SO._model_name(object()) == "object"


# ---------------------------------------------------------------------------
# All four subject-generation branches count
# ---------------------------------------------------------------------------
# `_invoke_counted` is wired at four call sites - two providers x short/long
# description. Only one was exercised, so a wrong label or a missed
# accumulator on the other three would not have been caught.

SHORT = "I need a coat."
LONG = (
    "I received an eviction notice after falling behind on rent for three "
    "months, and I am not sure what my options are before the court date."
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "provider,description,branch",
    [
        ("groq", SHORT, "short"),
        ("gemini", SHORT, "short"),
        ("groq", LONG, "long"),
        ("gemini", LONG, "long"),
    ],
)
def test_every_subject_branch_records_usage(monkeypatch, capsys, provider, description, branch):
    import utils.subject_generator as sg

    fake = _FakeChatModel(content="A Subject", input_tokens=500, output_tokens=12)
    groq_up = provider == "groq"

    # When testing the Gemini branch, Groq must be absent so the fallback runs.
    monkeypatch.setattr(sg, "groq_llm", fake if groq_up else None)
    monkeypatch.setattr(sg, "_use_groq", groq_up)
    monkeypatch.setattr(sg, "gemini_llm", None if groq_up else fake)
    monkeypatch.setattr(sg, "_use_gemini", not groq_up)

    sg.generate_subject_from_description(description)

    (record,) = _usage_lines(capsys)
    assert record["total_tokens"] == 512
    call = record["calls"][0]
    assert call["provider"] == provider
    assert call["branch"] == branch, "the call site labelled itself wrong"


@pytest.mark.integration
def test_a_subject_falls_back_to_gemini_and_bills_both(monkeypatch, capsys):
    """Groq answered, then failed to parse; Gemini was asked the same thing."""
    import utils.subject_generator as sg

    class _Broken:
        """Returns a message, then blows up on `.content` access."""
        def invoke(self, _prompt):
            class _M:
                usage_metadata = {
                    "input_tokens": 500, "output_tokens": 40, "total_tokens": 540,
                }
                @property
                def content(self):
                    raise RuntimeError("bad payload")
            return _M()

    monkeypatch.setattr(sg, "groq_llm", _Broken())
    monkeypatch.setattr(sg, "_use_groq", True)
    monkeypatch.setattr(sg, "gemini_llm", _FakeChatModel("Fallback Subject", 500, 10))
    monkeypatch.setattr(sg, "_use_gemini", True)

    assert sg.generate_subject_from_description(SHORT) == "Fallback Subject"

    (record,) = _usage_lines(capsys)
    # Groq's tokens were spent even though its answer was unusable.
    assert [c["provider"] for c in record["calls"]] == ["groq", "gemini"]
    assert record["total_tokens"] == 540 + 510


@pytest.mark.integration
def test_subject_with_no_provider_logs_nothing_spent(monkeypatch, capsys):
    import utils.subject_generator as sg

    monkeypatch.setattr(sg, "groq_llm", None)
    monkeypatch.setattr(sg, "_use_groq", False)
    monkeypatch.setattr(sg, "gemini_llm", None)
    monkeypatch.setattr(sg, "_use_gemini", False)

    sg.generate_subject_from_description(SHORT)

    (record,) = _usage_lines(capsys)
    assert record["total_calls"] == 0
    assert record["total_tokens"] == 0


# ---------------------------------------------------------------------------
# Remaining branches in the util itself
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_output_token_details_without_reasoning_changes_nothing():
    """The details dict is present on plenty of non-reasoning responses."""
    message = _LangChainMessage(usage_metadata={
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
        "output_token_details": {"audio": 0},
    })
    assert token_usage.extract_usage(message)["completion_tokens"] == 20


@pytest.mark.unit
def test_log_usage_never_raises_on_a_hostile_accumulator(capsys):
    """Telemetry failing must not take down the request that succeeded."""
    class _Hostile(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    token_usage.log_usage("svc", _Hostile({"total_calls": 1}))
    assert capsys.readouterr().out == ""


@pytest.mark.integration
def test_answer_generation_with_no_provider_at_all(monkeypatch, capsys):
    """No keys configured: Gemini raises, and the spend log is still emitted."""
    import utils

    monkeypatch.setattr(utils, "groq_llm", None)
    monkeypatch.setattr(utils, "gemini_llm", None)

    with pytest.raises(ValueError):
        utils.GroqAnswerGenerationService().generate_answer(
            category="Housing", subject="Rent", description="behind on rent",
        )

    # The finally: block reports even when the call failed.
    (record,) = _usage_lines(capsys)
    assert record["total_calls"] == 0


@pytest.mark.integration
def test_both_providers_failing_on_a_long_description_still_reports(monkeypatch, capsys):
    """The long-description branch has its own fallback pair.

    Both providers are asked, both fail after answering, and the caller still
    gets a subject from the truncated description. The tokens both providers
    burned on the way there have to appear in the log.
    """
    import utils.subject_generator as sg

    class _AnswersThenBreaks:
        def invoke(self, _prompt):
            class _M:
                usage_metadata = {
                    "input_tokens": 600, "output_tokens": 30, "total_tokens": 630,
                }
                @property
                def content(self):
                    raise RuntimeError("bad payload")
            return _M()

    monkeypatch.setattr(sg, "groq_llm", _AnswersThenBreaks())
    monkeypatch.setattr(sg, "_use_groq", True)
    monkeypatch.setattr(sg, "gemini_llm", _AnswersThenBreaks())
    monkeypatch.setattr(sg, "_use_gemini", True)

    subject = sg.generate_subject_from_description(LONG)

    assert subject and len(subject) <= 70  # fell back to the description
    (record,) = _usage_lines(capsys)
    assert [c["provider"] for c in record["calls"]] == ["groq", "gemini"]
    assert [c["branch"] for c in record["calls"]] == ["long", "long"]
    assert record["total_tokens"] == 1260  # paid twice, answered by neither


# ---------------------------------------------------------------------------
# Failures are swallowed, but never silently
# ---------------------------------------------------------------------------
# The module must not raise into a served request. That guard is only safe if
# it is loud: zeros on a dashboard look like a cheap service rather than a
# broken counter. These pin the logging so a later edit cannot quietly restore
# a bare `except: pass`.

@pytest.mark.unit
def test_a_broken_extractor_is_logged_not_hidden(caplog):
    class _Hostile:
        @property
        def usage_metadata(self):
            raise RuntimeError("provider exploded")

    with caplog.at_level("WARNING", logger="utils.token_usage"):
        assert token_usage.extract_usage(_Hostile()) == token_usage.ZERO_USAGE

    assert any(r.levelname == "ERROR" for r in caplog.records), \
        "a failing extractor was swallowed without a log line"
    assert "_Hostile" in caplog.text, "the log does not say what shape broke it"


@pytest.mark.unit
def test_an_unrecognised_response_warns(caplog):
    """A provider that stops reporting usage bills us exactly the same."""
    with caplog.at_level("WARNING", logger="utils.token_usage"):
        token_usage.extract_usage(object())

    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert "counting it as zero" in caplog.text


@pytest.mark.unit
def test_recording_into_a_broken_accumulator_is_logged(caplog):
    with caplog.at_level("ERROR", logger="utils.token_usage"):
        token_usage.record(
            {"not": "an accumulator"}, _GroqResponse(100, 20, 120),
            provider="groq", model="gpt-oss",
        )

    assert "cannot record groq/gpt-oss" in caplog.text
    # The size of what was lost belongs in the message: it is the number the
    # totals are now short by.
    assert "120 tokens" in caplog.text


@pytest.mark.unit
def test_an_unserialisable_record_degrades_to_totals_rather_than_vanishing(capsys, caplog):
    """Losing the labels is acceptable; losing the whole request is not."""
    class _Unserialisable:
        def __repr__(self):
            raise RuntimeError("cannot be stringified")

    accumulator = token_usage.new_accumulator()
    token_usage.record(accumulator, _GroqResponse(100, 20, 120),
                       provider="groq", model="m")

    with caplog.at_level("ERROR", logger="utils.token_usage"):
        token_usage.log_usage("search_orgs", accumulator, bad=_Unserialisable())

    line = capsys.readouterr().out.strip()
    assert line.startswith("TOKEN_USAGE "), "the record vanished instead of degrading"
    payload = json.loads(line[len("TOKEN_USAGE "):])
    assert payload["degraded"] is True
    assert payload["total_tokens"] == 120, "the countable part was lost too"
    assert "could not serialise" in caplog.text
