"""Session-only memory; all raw messages remain in the caller's transcript."""

import hashlib
import json

from services.memory_privacy import redact_sensitive
from services.memory_validation import normalize_memory_history
from utils import MAX_HISTORY_MESSAGES, MAX_SUMMARY_CHARS

BATCH_SIZE = 5
MAX_BATCHES_PER_REQUEST = 3
_MAX_FIT_PASSES = 3


def _fingerprint(history):
    encoded = json.dumps(history, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fit_summary(text):
    """Redact, then cut to the store's cap.

    Redaction lengthens text ("1234" becomes "[REDACTED SECRET]"), so a model
    summary inside the cap can leave it. Rejecting that summary re-summarized
    the same batch on every request and stuck the session. Cutting can expose
    a fresh match at the boundary, so the cut text is redacted again.
    """
    text = redact_sensitive(text)
    for _ in range(_MAX_FIT_PASSES):
        if len(text) <= MAX_SUMMARY_CHARS:
            return text
        text = redact_sensitive(text[:MAX_SUMMARY_CHARS].rstrip())
    if len(text) > MAX_SUMMARY_CHARS:
        raise ValueError("Summarized memory exceeds size limit")
    return text


def update_session_memory(store, session_id, history, summarizer):
    """Persist summarized old turns, not pending or recent raw messages.

    Returns (summary, unsummarized_history). The latter belongs to the current
    request; it exceeds the answer service's 20-message prompt cap only while
    a long backlog is still being caught up, MAX_BATCHES_PER_REQUEST at a time.
    """
    clean_history = [
        {"role": m["role"], "content": redact_sensitive(m["content"])}
        for m in normalize_memory_history(history)
    ]
    state, version = store.load(session_id)
    summary = state.get("memory", "")
    cursor = state.get("summarized_count", 0)
    saved_hash = state.get("summarized_hash", _fingerprint([]))

    # A transcript that no longer starts with what was summarized - trimmed by
    # the client, or restarted under the same session_id - describes a
    # different conversation. Refusing it refused the answer on every later
    # request; reusing the summary would answer from the wrong conversation.
    # Start the summary over from the transcript we were given.
    reset = (
        not isinstance(cursor, int)
        or cursor < 0
        or cursor > len(clean_history)
        or _fingerprint(clean_history[:cursor]) != saved_hash
    )
    if reset:
        summary, cursor = "", 0

    # The answer service keeps only the last MAX_HISTORY_MESSAGES turns, so a
    # batch is summarized as soon as any of its turns falls out of that window.
    # Waiting for a whole batch to fall out left up to BATCH_SIZE - 1 turns in
    # neither the summary nor the prompt. A batch may now overlap the window,
    # which repeats a turn the model can already see rather than losing one.
    window_start = max(0, len(clean_history) - MAX_HISTORY_MESSAGES)

    # A long transcript with no saved state - a new session_id, or a row the
    # TTL removed - used to replay every batch in one request: 76 sequential
    # model calls for 400 messages, past API Gateway's 29 seconds, with nothing
    # saved until the end. Each request now does a bounded share and saves
    # after every batch, so a backlog catches up across requests and no
    # finished batch is lost to a later failure.
    batches = 0
    while cursor < window_start and batches < MAX_BATCHES_PER_REQUEST:
        batch = clean_history[cursor:cursor + BATCH_SIZE]
        proposed = summarizer(summary, batch)
        if not isinstance(proposed, str) or not proposed.strip():
            raise ValueError("Summarizer returned empty memory")
        summary = _fit_summary(proposed.strip())
        cursor += len(batch)
        version = _save(store, session_id, summary, clean_history[:cursor], version)
        batches += 1

    if reset and batches == 0:
        # Nothing to summarize yet, but the stale summary must not survive.
        _save(store, session_id, summary, clean_history[:cursor], version)

    return summary, clean_history[cursor:]


def _save(store, session_id, summary, summarized, version):
    return store.save(
        session_id,
        {
            "memory": summary,
            "summarized_count": len(summarized),
            "summarized_hash": _fingerprint(summarized),
        },
        expected_version=version,
    )
