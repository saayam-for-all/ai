import re

from utils.categories import help_categories
from utils.categories_with_description import TAXONOMY

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "before",
    "but",
    "by",
    "for",
    "from",
    "get",
    "help",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "me",
    "my",
    "need",
    "of",
    "on",
    "or",
    "so",
    "someone",
    "that",
    "the",
    "their",
    "them",
    "there",
    "this",
    "to",
    "up",
    "want",
    "with",
}

CATEGORY_SIGNAL_DATA = {
    "1": {"phrases": ["food pantry", "groceries", "meal prep", "cooking help"]},
    "1.1": {"phrases": ["food pantry", "food bank", "pantry", "free meals"]},
    "1.2": {
        "phrases": [
            "grocery delivery",
            "grocery shopping",
            "shop for groceries",
            "deliver groceries",
        ]
    },
    "1.3.1": {
        "phrases": ["meal prep", "prepare meals", "simple meals", "basic cooking"]
    },
    "1.3.2": {
        "phrases": [
            "bulk cooking",
            "festival food",
            "event cooking",
            "large quantities",
        ]
    },
    "1.3.3": {
        "phrases": ["meal planning", "healthy meals", "balanced diet", "nutrition plan"]
    },
    "1.3.4": {
        "phrases": [
            "cultural cuisine",
            "traditional dishes",
            "regional dishes",
            "family recipes",
        ]
    },
    "1.3.5": {"phrases": ["baking", "cake", "oven", "recipe help", "kitchen help"]},
    "2": {"phrases": ["clothes", "jacket", "tailor", "wardrobe"]},
    "2.1": {"phrases": ["donate clothes", "clothing donation", "give away clothes"]},
    "2.2": {"phrases": ["borrow clothes", "borrow a suit", "interview outfit"]},
    "2.3": {
        "phrases": [
            "emergency clothes",
            "flooded",
            "lost my clothes",
            "urgent clothing",
        ]
    },
    "2.4": {"phrases": ["tailor", "zipper repair", "alterations", "shorten sleeves"]},
    "3": {"phrases": ["rent", "lease", "apartment", "repairs", "move", "roommate"]},
    "3.1": {
        "phrases": [
            "lease renewal",
            "lease agreement",
            "lease terms",
            "landlord clause",
        ]
    },
    "3.2": {
        "phrases": [
            "rent increase",
            "tenant rights",
            "eviction",
            "overdue rent",
            "rent support",
        ]
    },
    "3.3.1": {
        "phrases": ["plumber", "plumbing", "leak", "faucet", "drain", "pipe", "sink"]
    },
    "3.3.2": {
        "phrases": [
            "handyman",
            "mount shelves",
            "small fixes",
            "assemble furniture",
            "loose cabinet",
        ]
    },
    "3.3.3": {
        "phrases": [
            "electrician",
            "wiring",
            "breaker",
            "outlet",
            "light switch",
            "ceiling fan",
        ]
    },
    "3.3.4": {
        "phrases": [
            "carpentry",
            "wood repair",
            "bed frame",
            "wobbly table",
            "wooden furniture",
        ]
    },
    "3.3.5": {
        "phrases": [
            "garden",
            "lawn",
            "landscaping",
            "yard work",
            "trim plants",
            "weeds",
        ]
    },
    "3.3.6": {
        "phrases": ["hvac", "air conditioner", "ac repair", "heating", "thermostat"]
    },
    "3.3.7": {"phrases": ["roof leak", "roof repair", "shingles", "ceiling drip"]},
    "3.3.8": {
        "phrases": ["locksmith", "locked out", "lockout", "key duplication", "deadbolt"]
    },
    "3.3.9": {
        "phrases": ["painting", "repaint", "paint peeling", "wall paint", "touch up"]
    },
    "3.3.10": {
        "phrases": ["masonry", "concrete", "brick", "cracked steps", "patio repair"]
    },
    "3.3.11": {
        "phrases": ["welding", "metal gate", "metal repair", "gate hinge", "metalwork"]
    },
    "3.3.12": {"phrases": ["pool", "spa", "pool pump", "pool cleaning"]},
    "3.3.13": {
        "phrases": [
            "minor repair",
            "fixtures",
            "blinds",
            "miscellaneous repair",
            "odd repair",
        ]
    },
    "3.4": {
        "phrases": [
            "utilities",
            "electricity",
            "water service",
            "internet setup",
            "service setup",
        ]
    },
    "3.5": {
        "phrases": [
            "rental listings",
            "find rental",
            "apartment search",
            "affordable apartment",
        ]
    },
    "3.6": {
        "phrases": [
            "roommate",
            "flatmate",
            "shared apartment",
            "room share",
            "share rent",
        ]
    },
    "3.7": {
        "phrases": ["move in help", "packing boxes", "unpacking", "moving day help"]
    },
    "3.8": {
        "phrases": ["packers movers", "moving company", "book movers", "moving quotes"]
    },
    "3.9": {
        "phrases": [
            "buy furniture",
            "buy a bed",
            "home essentials",
            "purchase used furniture",
        ]
    },
    "3.10": {
        "phrases": ["sell furniture", "list couch", "sell table", "marketplace listing"]
    },
    "4": {
        "phrases": [
            "college",
            "tutoring",
            "scholarship",
            "resume",
            "interview",
            "study materials",
        ]
    },
    "4.1": {
        "phrases": ["college application", "application deadline", "required documents"]
    },
    "4.2": {
        "phrases": ["statement of purpose", "sop", "essay review", "personal statement"]
    },
    "4.3.1": {"phrases": ["math tutoring", "algebra", "calculus", "geometry"]},
    "4.3.2": {"phrases": ["english tutoring", "grammar", "essay writing"]},
    "4.3.3": {"phrases": ["science tutoring", "chemistry", "physics", "biology"]},
    "4.3.4": {
        "phrases": [
            "computer science tutoring",
            "python",
            "data structures",
            "programming",
        ]
    },
    "4.3.5": {"phrases": ["test prep", "sat", "gre", "gmat", "exam strategy"]},
    "4.3.6": {"phrases": ["history tutoring", "other subject", "social studies"]},
    "4.4": {"phrases": ["scholarship", "financial aid"]},
    "4.5": {"phrases": ["study group", "study partner"]},
    "4.6": {
        "phrases": [
            "resume",
            "interview",
            "job search",
            "networking",
            "career advice",
            "software role",
        ]
    },
    "4.7": {
        "phrases": [
            "study materials",
            "textbooks",
            "class notes",
            "learning resources",
            "books",
        ]
    },
    "5": {
        "phrases": [
            "doctor",
            "symptoms",
            "pain",
            "pharmacy",
            "wellness",
            "vaccine",
            "anxiety",
        ]
    },
    "5.1.1": {"phrases": ["fever", "body aches", "fatigue", "general symptoms"]},
    "5.1.2": {"phrases": ["ent", "ear pain", "sinus pressure", "sore throat", "nasal"]},
    "5.1.3": {"phrases": ["tooth pain", "gums", "dental", "oral health"]},
    "5.1.4": {"phrases": ["blurry vision", "eye pain", "eye doctor", "vision care"]},
    "5.1.5": {"phrases": ["blood pressure", "hypertension", "palpitations", "cardiac"]},
    "5.1.6": {
        "phrases": [
            "knee pain",
            "mobility",
            "physiotherapy",
            "orthopedic",
            "joint pain",
        ]
    },
    "5.1.7": {"phrases": ["skin rash", "dermatology", "itching", "eczema"]},
    "5.1.8": {"phrases": ["reproductive health", "irregular periods", "womens health"]},
    "5.1.9": {
        "phrases": [
            "vaccine",
            "vaccination",
            "immunization",
            "booster",
            "required shots",
            "preventive screening",
            "school shots",
            "school vaccine record",
            "vaccine requirement",
        ]
    },
    "5.1.10": {"phrases": ["pediatric", "child health", "child fever", "kids doctor"]},
    "5.1.11": {
        "phrases": [
            "stomach pain",
            "digestive issues",
            "abdominal pain",
            "gastrointestinal",
            "unexplained symptoms",
        ]
    },
    "5.2": {
        "phrases": [
            "pharmacy pickup",
            "medicine delivery",
            "otc medicine",
            "pick up medicine",
        ]
    },
    "5.3": {
        "phrases": [
            "anxiety",
            "overwhelmed",
            "emotional support",
            "therapy",
            "counselor",
        ]
    },
    "5.4": {
        "phrases": [
            "medication reminder",
            "take pills",
            "daily reminder",
            "medicine alarm",
        ]
    },
    "5.5": {
        "phrases": [
            "sleep hygiene",
            "wellness habits",
            "healthy routine",
            "bedtime routine",
            "preventive care",
        ]
    },
    "6": {
        "phrases": [
            "elderly parent",
            "senior care",
            "grandmother",
            "grandfather",
            "older adult",
        ]
    },
    "6.1": {
        "phrases": [
            "senior housing",
            "assisted living",
            "relocate parents",
            "move elderly parents",
        ]
    },
    "6.2": {
        "phrases": [
            "smartphone help",
            "tablet help",
            "video calls",
            "tech support",
            "messages",
        ]
    },
    "6.3": {
        "phrases": [
            "organize pills",
            "pill box",
            "medication management",
            "sort medicines",
        ]
    },
    "6.4": {
        "phrases": [
            "blood pressure monitor",
            "medical device",
            "glucometer",
            "device setup",
        ]
    },
    "6.5": {
        "phrases": [
            "errands",
            "grocery pickup",
            "pharmacy pickup",
            "drop off prescriptions",
        ]
    },
    "6.6": {
        "phrases": [
            "ride to appointment",
            "transportation",
            "doctor ride",
            "ride to clinic",
        ]
    },
    "6.7": {"phrases": ["schedule appointments", "calendar help", "organize tasks"]},
    "6.8": {"phrases": ["companionship", "lonely", "social visit", "check in calls"]},
    "6.9": {
        "phrases": [
            "meals for seniors",
            "dietary meals",
            "meal prep for elderly",
            "preparing meals",
            "dietary restrictions",
        ]
    },
}

SHORTLIST_FILTER_THRESHOLD = 8
SHORTLIST_SIZE = 6
SHORTLIST_MIN_SCORE = 1.5


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _expand_token(token: str) -> set[str]:
    forms = {token}
    if token.endswith("ies") and len(token) > 4:
        forms.add(token[:-3] + "y")
    elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        forms.add(token[:-1])
    return forms


def _tokenize(text: str) -> set[str]:
    tokens = set()
    for token in _normalize_text(text).split():
        if len(token) < 2 or token in STOP_WORDS:
            continue
        tokens.update(_expand_token(token))
    return tokens


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def _build_category_profile(category_id: str) -> dict:
    category_name = help_categories.get(category_id, "")
    readable_name = category_name.replace("_", " ")
    description = TAXONOMY.get(category_name, "")
    signal_data = CATEGORY_SIGNAL_DATA.get(category_id, {})
    phrases = [readable_name, description, *signal_data.get("phrases", [])]

    normalized_phrases = []
    seen = set()
    for phrase in phrases:
        normalized_phrase = _normalize_text(phrase)
        if not normalized_phrase or normalized_phrase in seen:
            continue
        seen.add(normalized_phrase)
        normalized_phrases.append(normalized_phrase)

    return {
        "phrases": normalized_phrases,
        "tokens": _tokenize(" ".join(phrases)),
    }


CATEGORY_PROFILES = {
    category_id: _build_category_profile(category_id) for category_id in help_categories
}


def score_candidate(description: str, category_id: str) -> float:
    normalized_text = _normalize_text(description)
    query_tokens = _tokenize(description)
    profile = CATEGORY_PROFILES.get(category_id)
    if not profile:
        return 0.0

    score = 0.0
    for phrase in profile["phrases"]:
        if _contains_phrase(normalized_text, phrase):
            word_count = len(phrase.split())
            if word_count >= 4:
                score += 3.0
            elif word_count >= 2:
                score += 2.0
            else:
                score += 1.0

    overlap = query_tokens & profile["tokens"]
    for token in overlap:
        score += 0.45 if len(token) < 8 else 0.65

    return score


def order_candidates_by_similarity(
    description: str, candidates: list[str]
) -> list[str]:
    if len(candidates) <= SHORTLIST_FILTER_THRESHOLD:
        return candidates

    scored_candidates = []
    for index, category_id in enumerate(candidates):
        scored_candidates.append(
            (category_id, score_candidate(description, category_id), index)
        )

    scored_candidates.sort(key=lambda item: (-item[1], item[2]))
    ordered_candidates = [
        category_id for category_id, _score, _index in scored_candidates
    ]

    top_score = scored_candidates[0][1]
    if top_score < SHORTLIST_MIN_SCORE:
        return ordered_candidates

    shortlist = ordered_candidates[:SHORTLIST_SIZE]
    return shortlist
