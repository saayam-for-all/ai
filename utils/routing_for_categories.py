# Routing helpers for category selection.

import re


DIRECT_ELDERLY_TRIGGERS = (
    "senior citizen",
    "senior living",
    "senior housing",
    "retirement home",
    "retirement community",
    "senior center",
    "assisted living",
    "nursing home",
    "nursing facility",
    "care home",
    "long term care",
    "long term care",
    "elder care",
    "geriatric",
    "aging parent",
    "ageing parent",
)

ELDERLY_PERSON_TRIGGERS = (
    "elderly",
    "elder",
    "older adult",
    "older person",
    "older relative",
    "older family member",
    "grandparent",
    "grandmother",
    "grandfather",
    "grandma",
    "grandpa",
)

WEAK_ELDERLY_PERSON_TRIGGERS = (
    "mom",
    "dad",
    "mother",
    "father",
    "parent",
    "aunt",
    "uncle",
    "relative",
    "family member",
)

ELDERLY_CONTEXT_CUES = (
    "caregiver",
    "caregiving",
    "daily help",
    "daily living",
    "activities of daily living",
    "adl",
    "medication",
    "pill",
    "reminder",
    "pharmacy",
    "appointment",
    "clinic",
    "home visit",
    "mobility",
    "walker",
    "wheelchair",
    "fall",
    "falls",
    "hearing",
    "vision",
    "home health",
    "home care",
    "in home care",
    "home aide",
    "care aide",
    "live in care",
    "companionship",
    "lonely",
    "meal prep",
    "meal preparation",
    "preparing meals",
    "meal support",
    "dietary meals",
    "transport",
    "ride",
    "rides",
    "errand",
    "errands",
    "smartphone",
    "tablet",
    "video call",
    "messages",
    "tech support",
    "medical device",
    "blood pressure monitor",
    "glucometer",
    "schedule appointments",
)

ELDERLY_FALSE_POSITIVE_PHRASES = (
    "senior software engineer",
    "senior engineer",
    "senior developer",
    "senior manager",
    "senior role",
    "grandfather clock",
    "nursing entrance exam",
    "nursing school",
    "nursing exam",
)


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {text} "


def is_elderly_context(description: str) -> bool:
    text = _normalize_text(description)

    if any(_contains_phrase(text, phrase) for phrase in DIRECT_ELDERLY_TRIGGERS):
        return True

    if any(_contains_phrase(text, phrase) for phrase in ELDERLY_FALSE_POSITIVE_PHRASES):
        return False

    has_person_trigger = any(
        _contains_phrase(text, trigger)
        for trigger in ELDERLY_PERSON_TRIGGERS + WEAK_ELDERLY_PERSON_TRIGGERS
    )
    if not has_person_trigger:
        return False

    return any(_contains_phrase(text, cue) for cue in ELDERLY_CONTEXT_CUES)
