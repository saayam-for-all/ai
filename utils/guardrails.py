"""Checks around the classification model, and a record of each time one fires.

Issue #197, stack 5. A guardrail is a check placed around the model rather
than inside it:

  * **inbound** checks look at what goes in. `scan_for_injection` looks for a
    description that tries to steer the classifier instead of describing a
    need - "ignore the instructions above", a forged `Categories:` block, a
    ready-made JSON answer.
  * **outbound** checks look at what comes out. `dedupe_ranked` removes a
    category the model listed twice; `_normalize_category_id` in
    services/classification_service.py already drops ids that were not
    offered, and reports each drop here.

The injection check only *records* for now. A rule that blocks has to be
measured first: a false positive refuses a real person's request for help,
and we have no data yet on how often these patterns appear in real ones. The
GUARDRAIL lines this module prints are that data.

Each line is CloudWatch Embedded Metric Format, like CLASSIFICATION_OUTCOME
(utils/classification_telemetry.py): a `Triggered` count per service and
guardrail, with no extra AWS call. Lines never carry the description, only
the names of the rules that matched. Nothing here may raise into a request.
"""

from __future__ import annotations

import json
import logging
import re
import time

logger = logging.getLogger(__name__)

EVENT = "GUARDRAIL"
NAMESPACE = "Saayam/GenAI"

#: Rule name -> pattern. Each is narrow on purpose: they are matched against
#: free text from people asking for help, so "ignore" or "system" alone must
#: not match. tests/test_guardrails.py checks none fires on the golden set.
INJECTION_RULES = {
    # "Ignore the previous instructions", "disregard all rules above".
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instructions?|prompts?|rules)\b",
        re.I,
    ),
    # A line that claims a chat role, or a chat-template control token.
    "role_marker": re.compile(
        r"(^|\n)\s*(system|assistant|developer)\s*:|<\|im_start\|>|\[/?INST\]|<<SYS>>",
        re.I,
    ),
    # A line that forges a section of our own prompt.
    "prompt_structure": re.compile(
        r"(^|\n)\s*(routing hint|categories|return format|description)\s*:",
        re.I,
    ),
    # A ready-made answer in the shape the classifier is asked to return.
    "answer_injection": re.compile(r"\{\s*\"categor(y|ies)\"\s*:", re.I),
    # "You are now a ...", "you are no longer the ...". Not "act as" or
    # "pretend to be": people ask for a mentor to act as a guide, or for
    # someone to pretend to be a landlord so they can rehearse a call.
    "persona_switch": re.compile(r"\byou are (now|no longer) (a|an|the)\b", re.I),
}


def record(service: str, guardrail: str, action: str, **detail) -> None:
    """Print one GUARDRAIL line saying a check fired. Never raises.

    `action` is what was done about it: "logged" (nothing changed),
    "removed" or "dropped" (part of a model answer was discarded).
    `detail` must not contain the person's text.
    """
    try:
        line = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [["Service", "Guardrail"]],
                        "Metrics": [{"Name": "Triggered", "Unit": "Count"}],
                    }
                ],
            },
            "event": EVENT,
            "Service": service,
            "Guardrail": guardrail,
            "action": action,
            "Triggered": 1,
            **detail,
        }
        print(json.dumps(line, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 - the request must not fail on its telemetry
        logger.exception("%s: could not print the record for %s", EVENT, guardrail)


def scan_for_injection(text: str) -> list[str]:
    """Names of the injection rules `text` matches, in rule order; empty if none."""
    if not isinstance(text, str) or not text:
        return []
    return [name for name, pattern in INJECTION_RULES.items() if pattern.search(text)]


def check_description(description: str, *, service: str) -> list[str]:
    """Inbound guardrail: scan a description and record any match.

    Returns the matched rule names so a caller can act on them later. Today
    no caller does: the request goes ahead unchanged.
    """
    try:
        matched = scan_for_injection(description)
    except Exception:  # noqa: BLE001 - a broken check must not refuse a request
        logger.exception("%s: injection scan failed", EVENT)
        return []
    if matched:
        record(service, "prompt_injection", "logged", rules=matched,
               description_chars=len(description))
    return matched


def dedupe_ranked(items: list[dict], *, service: str, key: str = "category") -> list[dict]:
    """Outbound guardrail: keep the first occurrence of each category, in order.

    A model sometimes lists one category several times. Shown to a person,
    `[General, General, General]` is three suggestions that are one; it also
    pushes real second and third choices out of the top three. The first
    occurrence is kept because the list is ranked.
    """
    seen: set = set()
    kept = []
    for item in items:
        value = item.get(key)
        if value in seen:
            continue
        seen.add(value)
        kept.append(item)
    if len(kept) < len(items):
        record(service, "duplicate_category", "removed", removed=len(items) - len(kept))
    return kept
