# app.py
from flask import Flask, request, jsonify
from typing import Optional

from emergency_data import EMERGENCY_DATA  # Static emergency data 

app = Flask(__name__)

CATEGORY_KEYWORDS = {
    "medical": [
        "ambulance", "heart attack", "not breathing", "unconscious",
        "bleeding", "injured", "hurt", "overdose", "stroke", "burned",
        "accident", "emergency room", "hospital", "poison"
    ],
    "police": [
        "police", "crime", "robbery", "stolen", "theft", "assault",
        "fight", "violence", "kidnap", "mugging", "harassment",
        "breaking in", "burglary"
    ],
    "fire": [
        "fire", "smoke", "burning", "explosion", "gas leak",
        "wildfire", "house on fire"
    ],
    "crisis": [
        "suicidal", "suicide", "self-harm", "self harm", "depressed",
        "want to die", "kill myself", "overwhelmed", "crisis hotline"
    ],
    "other": [
        "non emergency", "information", "help line", "helpline",
        "support services", "shelter", "social services"
    ],
}

CATEGORY_PRIORITY = ["medical", "fire", "police", "crisis", "other"]


def detect_location(text: str) -> Optional[str]:
    """Return the EMERGENCY_DATA key (e.g., 'US', 'IN') or None."""
    text_l = text.lower()
    for code, cfg in EMERGENCY_DATA.items():
        for alias in cfg.get("aliases", []):
            if alias in text_l:
                return code
    return None


def detect_category(text: str) -> Optional[str]:
    """Infer requested help category from text using keyword rules."""
    text_l = text.lower()
    matched_categories = set()

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_l:
                matched_categories.add(category)
                break  

    if not matched_categories:
        return None

    # Return the highest-priority category that is matched
    for cat in CATEGORY_PRIORITY:
        if cat in matched_categories:
            return cat

    return None


def get_emergency_contact(location_code: Optional[str],
                          category: Optional[str]):
    """
    Look up the best emergency contact based on location and category.
    Falls back to location default, then a generic fallback.
    """
    fallback = {
        "number": None,
        "name": "Local Emergency Services",
        "notes": "Dial your local emergency number immediately."
    }

    if not location_code or location_code not in EMERGENCY_DATA:
        return fallback

    loc_cfg = EMERGENCY_DATA[location_code]

    if category:
        cat_cfg = loc_cfg.get("categories", {}).get(category)
        if cat_cfg:
            return cat_cfg

    # If we didn’t find a category-specific contact, use default
    default_cfg = loc_cfg.get("default")
    if default_cfg:
        return default_cfg

    return fallback


@app.route("/emergency", methods=["POST"])
def emergency():
    """
    POST /emergency
    Body: { "message": "<user message>" }
    Optional: { "location_override": "US", "category_override": "medical" }
    """
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")

    if not user_message.strip():
        return jsonify({
            "error": "message field is required"
        }), 400

    # Allow optional explicit overrides (useful for UI integrations)
    location_override = data.get("location_override")
    category_override = data.get("category_override")

    # Detect location & category from message if not overridden
    location_code = location_override or detect_location(user_message)
    category = category_override or detect_category(user_message)

    # Get best emergency contact
    contact = get_emergency_contact(location_code, category)

    response = {
        "input_message": user_message,
        "detected_location_code": location_code,
        "detected_category": category,
        "contact": contact
    }

    # Optionally include a small human-readable summary
    response["summary"] = build_summary(response)

    return jsonify(response)


def build_summary(resp: dict) -> str:
    """
    Build a short, user-friendly summary for UI clients.
    """
    cat = resp.get("detected_category") or "general"
    contact = resp.get("contact") or {}
    number = contact.get("number")
    name = contact.get("name")

    if number and name:
        return f"For {cat} help, call {number} ({name})."
    elif number:
        return f"For {cat} help, call {number}."
    else:
        return ("Unable to determine a specific emergency number. "
                "Please dial your nearest local emergency service immediately.")


if __name__ == "__main__":
    # For local testing only
    app.run(host="0.0.0.0", port=5001, debug=True)
