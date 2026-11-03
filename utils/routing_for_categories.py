# Routing helpers for category selection.

STRONG_ELDERLY_TRIGGERS = (
    "elderly",
    "elder",
    "senior",
    "senior citizen",
    "senior living",
    "senior housing",
    "older adult",
    "older person",
    "older relative",
    "older family member",
    "retired",
    "retiree",
    "grandparent",
    "grandmother",
    "grandfather",
    "grandma",
    "grandpa",
    "grandson",
    "granddaughter",
    "retirement home",
    "retirement community",
    "senior center",
    "assisted living",
    "nursing home",
    "nursing facility",
    "care home",
    "long-term care",
    "long term care",
    "elder care",
    "geriatric",
    "aging",
    "ageing",
    "aging parent",
)

WEAK_ELDERLY_TRIGGERS = (
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
    "doctor",
    "clinic",
    "home visit",
    "mobility",
    "walker",
    "wheelchair",
    "fall",
    "falls",
    "hearing",
    "vision",
    "nursing",
    "home health",
    "home care",
    "in-home care",
    "in home care",
    "home aide",
    "care aide",
    "live-in care",
    "live in care",
    "companionship",
    "lonely",
    "meal prep",
    "meal preparation",
    "transport",
    "ride",
    "rides",
    "errand",
    "errands",
)


def is_elderly_context(description: str) -> bool:
    text = description.lower()

    if any(trigger in text for trigger in STRONG_ELDERLY_TRIGGERS):
        return True

    if not any(trigger in text for trigger in WEAK_ELDERLY_TRIGGERS):
        return False

    return any(cue in text for cue in ELDERLY_CONTEXT_CUES)
