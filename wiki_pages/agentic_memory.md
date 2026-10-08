# Stack 1 – Agentic Memory

## 1. Definition

Agentic memory allows an AI system to retain useful information from earlier interactions instead of relying only on messages currently available in its conversation window.

Applications often limit conversation history because longer prompts increase token usage, cost, and context size. When older messages are removed, however, useful information in them may also disappear.

Agentic memory separates **recent conversation history** from **older useful context**.

A memory system may contain:

- **Recent/session context:** the latest conversation messages.
- **Working memory:** information currently relevant to the task.
- **Longer-term memory:** useful information retained after the original messages leave the recent conversation.

One approach is **rolling summarization**. As older messages leave the recent window, they are summarized into compact memory. Later batches can update that existing memory.

The goal is not to permanently store every message. It is to preserve useful context while keeping the active conversation bounded.

This is relevant to Saayam because conversation history is currently limited to the 20 most recent messages.

---

## 2. Mechanism

Saayam defines the conversation-history limit in:

```text
utils/__init__.py:35
```

```python
MAX_HISTORY_MESSAGES = 20
```

History normalization eventually performs:

```text
utils/__init__.py:119
```

```python
return out[-MAX_HISTORY_MESSAGES:]
```

Therefore:

```text
Messages 1–25
      ↓
Keep latest 20
      ↓
Messages 1–5 removed
Messages 6–25 retained
```

This prevents conversation history from growing without bounds, but useful information in older messages can disappear.

### Rolling-memory experiment

The experiment separates conversation state into:

```text
recent
    Latest 20 messages

pending
    Messages outside the recent window
    waiting to be summarized

memory
    Summary of older messages
```

Messages arrive one at a time. When message 21 arrives, message 1 moves from `recent` to `pending`.

Once five messages are pending:

```text
previous memory
       +
5 pending messages
       ↓
   summarizer
       ↓
updated memory
```

The pending buffer is then cleared. When another five messages expire, they are summarized together with the existing memory, creating rolling memory.

If fewer than five messages are pending, they remain available as part of the current context until summarization occurs.

The experiment uses a **mocked summarizer** rather than a live LLM. This keeps it deterministic, offline, and consistent with the no-network testing approach in `tests/conftest.py`.

The important boundary is:

```python
summarizer(previous_memory, expired_messages)
```

A future implementation could replace the mock with a real summarizer without changing the basic memory-management mechanism.

---

## 3. Worked Example

The following local experiment uses Saayam's existing history limit:

```python
"""Rolling-memory experiment for issue #197."""

from utils import MAX_HISTORY_MESSAGES

MEMORY_BATCH_SIZE = 5


class ConversationMemory:
    def __init__(self, summarizer):
        self.summarizer = summarizer
        self.memory = ""
        self.pending = []
        self.recent = []

    def add(self, message):
        self.recent.append(message)

        if len(self.recent) > MAX_HISTORY_MESSAGES:
            self.pending.append(self.recent.pop(0))

        if len(self.pending) >= MEMORY_BATCH_SIZE:
            self.memory = self.summarizer(self.memory, self.pending)
            self.pending = []

    def context(self):
        return self.memory, self.pending + self.recent
```

The example is under 50 lines and requires no API key, AWS credentials, database, or network connection.

The summarizer was mocked during testing. The memory mechanism itself remained real.

Three behaviors were tested:

1. **Initial memory creation:** after 25 messages, the first five expired messages were sent to the summarizer while recent history remained at 20.
2. **Rolling updates:** after 30 messages, the second batch was summarized together with the memory produced from the first batch.
3. **Pending context:** when fewer than five messages had expired, they remained available through `context()` instead of temporarily disappearing.

Local test result:

```text
test_old_messages_move_into_memory                 PASSED
test_memory_is_updated_across_multiple_batches     PASSED
test_pending_messages_remain_in_context            PASSED

3 passed
```

The tests ran without a live model provider or network connection.

---

## 4. Finding

### What the example showed

Saayam's existing test in:

```text
tests/test_answer_conversation.py
```

confirms that a 60-message conversation is reduced to the latest 20 messages.

A baseline test then placed meaningful information in the first message:

```text
I need transportation to dialysis three times per week.
```

After enough additional messages, the message was no longer present in the history forwarded to the model.

The comparison was:

| Behavior | Current Saayam | Rolling memory |
|---|---:|---:|
| Recent history bounded | ✅ | ✅ |
| Latest 20 retained | ✅ | ✅ |
| Old messages removed | ✅ | ✅ |
| Older context represented separately | ❌ | ✅ |
| No network required for experiment | ✅ | ✅ |

The experiment shows that **rolling memory provides a mechanism for carrying older context forward after the original messages leave Saayam's 20-message window**.

It does not suggest removing the existing limit. Instead:

```text
Current:
old context → discarded
latest 20 ─────────────→ model

Possible:
summarized old context ─┐
pending context ─────────┼→ model
latest 20 ───────────────┘
```

### Production code affected

A production implementation would primarily affect the conversation-history/model-context flow in:

```text
utils/__init__.py
```

Current relevant locations, verified on `dev`:

```text
Line 35  — MAX_HISTORY_MESSAGES = 20
Line 119 — return out[-MAX_HISTORY_MESSAGES:]
```

The existing limit should remain. A memory mechanism would complement it by preserving selected older context.

Production implementation would additionally require:

- a real summarizer;
- persistent memory across requests/sessions;
- memory injection into model context;
- summary-quality and information-loss evaluation;
- failure handling;
- cost/token analysis; and
- privacy and retention rules.

The current experiment stores memory only inside a Python object, so it demonstrates rolling memory, **not persistent long-term memory**.

### Limitation

Because summarization was mocked, this experiment validates the **memory architecture**, not whether a real LLM will reliably select and preserve the correct information.

The batch size of five is also experimental, not a production recommendation.

### Conclusion

**Agentic memory appears potentially useful for Saayam and is worth further evaluation.**

The baseline confirmed that useful early context can disappear after exceeding the 20-message history window. The experiment demonstrated that older context can instead move through a rolling-memory mechanism while recent history remains bounded.

The next step for a production decision is to evaluate real summarization quality, persistence, cost, privacy, and integration with Saayam's session/context architecture.