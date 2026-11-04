"""The exact payloads AI Chat sends, replayed against generate_answer - issue #219.

The chat on Request Details sends two different payloads. The first answer comes
from `RequestButton.jsx`, which falls back to the logged-in user's id. Follow-ups
come from `MoreInfoChatModal.jsx`, which has no fallback, so `user_id` is left out
whenever the request data holds no requester id. The handler answered the first
and refused the second with a 400 inside an HTTP 200. The chat read `body.answer`,
found nothing, and rendered an empty grey bubble.

These tests pin both shapes to what the webapp `test` branch sends, so neither
side can drift from the other quietly. Nothing here calls a provider or a
database: the model is replaced with a recorder and the request store is patched,
so a test can assert both what the browser reads and what the model was asked.
"""
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import lambda_function as LF
import utils

pytestmark = pytest.mark.contract


OWNER_ID = "SID-1"
REQ_ID = "REQ-00-000-000-0788"
SUBJECT = "Need a plumber for a leaking pipe"
DESCRIPTION = "The pipe under my kitchen sink has been leaking since last night."

# Five, because the chat allows five. Each one leans on the turn before it,
# which is what the conversation history is there to make possible.
QUESTIONS = (
    "Can you suggest some local plumbers near my location?",
    "Which of those work on weekends?",
    "What should I ask them about pricing?",
    "What if the leak gets worse before they arrive?",
    "How do I shut off the water until then?",
)

# The follow-up the chat sends today gets a 400 until the conversation fallback
# for #219 merges. strict makes the suite fail the moment this starts passing,
# so the PR that adds the fallback has to delete this marker. raises stops a
# broken test hiding behind it: only a failed assertion is the expected failure.
NEEDS_CONVERSATION_FALLBACK = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="No fallback yet for a follow-up without user_id. Remove with the #219 fix.",
)


def _first_answer_payload():
    """What `RequestButton.jsx` sends when AI Chat opens."""
    return {"user_id": OWNER_ID, "req_id": REQ_ID, "conversation_history": []}


def _follow_up_without_user_id(history):
    """What `MoreInfoChatModal.jsx` sends today, with no fallback for `user_id`."""
    return {"req_id": REQ_ID, "conversation_history": history}


def _follow_up_with_owner(history):
    """What `MoreInfoChatModal.jsx` sends once the webapp fix lands."""
    return {"user_id": OWNER_ID, "req_id": REQ_ID, "conversation_history": history}


def _send(payload):
    """Call the handler as the browser reaches it, through non-proxy integration."""
    return LF.generate_answer_handler(payload, None)


def _assert_answered(response):
    """Return `body.answer`, the one field the chat renders.

    Anything other than non-empty text in a 200 is an empty bubble in the browser.
    """
    assert response["statusCode"] == 200, response["body"]
    answer = response["body"].get("answer")
    assert answer and answer.strip(), response["body"]
    return answer


def _user(content):
    return {"role": "user", "content": content}


def _assistant(content):
    return {"role": "assistant", "content": content}


def _turns_sent_to_model(messages):
    """The turns the model was given, in the shape the chat sent them."""
    system, *turns = messages
    assert isinstance(system, SystemMessage)
    roles = {HumanMessage: "user", AIMessage: "assistant"}
    return [{"role": roles[type(turn)], "content": turn.content} for turn in turns]


class _Recorder:
    """Stands in for the model. Each reply differs, so a stale turn cannot pass."""

    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        return SimpleNamespace(content=f"Answer {len(self.calls)}.")

    @property
    def messages(self):
        assert self.calls, "the model was never called"
        return self.calls[-1]


@pytest.fixture
def model(monkeypatch):
    """A recording model factory, patched below the handler and the service."""
    recorder = _Recorder()

    def fake_create_chat_model(target, *, temperature):
        if target.provider == "groq":
            return recorder
        raise ValueError("Unexpected fallback to Gemini")

    monkeypatch.setattr(utils, "create_chat_model", fake_create_chat_model)
    return recorder


@pytest.fixture
def request_store(fake_request_row):
    """The owner's request, as the lookup would return it."""
    with fake_request_row(subject=SUBJECT, description=DESCRIPTION) as lookup:
        yield lookup


# -------------------------------------------------------------------
# One turn of each shape
# -------------------------------------------------------------------

def test_the_first_answer_is_generated_from_the_owners_request(model, request_store):
    """Opening AI Chat sends the owner's id and an empty history."""
    response = _send(_first_answer_payload())

    _assert_answered(response)
    assert response["body"]["source"] == "database"
    request_store.assert_called_once_with(OWNER_ID, REQ_ID)
    assert DESCRIPTION in model.messages[-1].content


@NEEDS_CONVERSATION_FALLBACK
def test_a_follow_up_without_user_id_is_answered(model, request_store):
    """The payload the chat sends today, and the empty bubble reported in #219."""
    history = [_assistant("Look for a local plumber."), _user(QUESTIONS[0])]

    response = _send(_follow_up_without_user_id(history))

    _assert_answered(response)
    assert model.messages[-1].content == QUESTIONS[0]


def test_a_follow_up_with_the_owners_user_id_is_answered(model, request_store):
    """The payload the chat sends once the webapp fix lands."""
    history = [_assistant("Look for a local plumber."), _user(QUESTIONS[0])]

    response = _send(_follow_up_with_owner(history))

    _assert_answered(response)
    assert response["body"]["source"] == "database"
    request_store.assert_called_once_with(OWNER_ID, REQ_ID)
    assert model.messages[-1].content == QUESTIONS[0]


# -------------------------------------------------------------------
# A whole conversation
# -------------------------------------------------------------------

@pytest.mark.parametrize(
    "follow_up",
    [
        pytest.param(_follow_up_with_owner, id="with-owner-user-id"),
        pytest.param(
            _follow_up_without_user_id,
            id="without-user-id",
            marks=NEEDS_CONVERSATION_FALLBACK,
        ),
    ],
)
def test_five_follow_ups_are_each_answered_with_the_earlier_turns(model, request_store, follow_up):
    """Every question the chat allows gets an answer that can draw on the turns before it.

    This drives the conversation the way `handleSend` does: each request carries
    the transcript so far plus the new question, and the reply joins the transcript.
    """
    transcript = [_assistant(_assert_answered(_send(_first_answer_payload())))]

    for question in QUESTIONS:
        transcript.append(_user(question))

        answer = _assert_answered(_send(follow_up(transcript)))

        assert _turns_sent_to_model(model.messages) == transcript
        transcript.append(_assistant(answer))

    assert len(model.calls) == 1 + len(QUESTIONS)
