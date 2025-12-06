# emergency_data.py (or embed directly in app.py)

EMERGENCY_DATA = {
    "US": {
        "aliases": ["united states", "united states of america", "usa", "us", "america"],
        "categories": {
            "medical":  {
                "number": "911",
                "name": "Emergency Medical Services",
                "notes": "Available 24/7. Ask specifically for an ambulance."
            },
            "police": {
                "number": "911",
                "name": "Police",
                "notes": "For crimes in progress, threats, or danger."
            },
            "fire": {
                "number": "911",
                "name": "Fire Department",
                "notes": "For fire, explosion, gas leak, etc."
            },
            "crisis": {
                "number": "988",
                "name": "Suicide & Crisis Lifeline",
                "notes": "Confidential emotional support, 24/7, in the U.S."
            },
            "other": {
                "number": "211",
                "name": "Community Services",
                "notes": "Non-emergency social and community services."
            },
        },
        "default": {
            "number": "911",
            "name": "Emergency Services",
            "notes": "General emergency number for police, fire, and medical."
        }
    },

    "IN": {
        "aliases": ["india", "bharat"],
        "categories": {
            "medical": {
                "number": "102",
                "name": "Ambulance",
                "notes": "Government ambulance services; 108 in many states."
            },
            "police": {
                "number": "100",
                "name": "Police",
                "notes": "Police emergency."
            },
            "fire": {
                "number": "101",
                "name": "Fire Brigade",
                "notes": "Fire and rescue."
            },
            "crisis": {
                "number": "9152987821",
                "name": "KIRAN Mental Health Helpline (example)",
                "notes": "24/7 mental health support."
            },
            "other": {
                "number": "112",
                "name": "Single Emergency Helpline",
                "notes": "Integrated emergency response in many regions."
            },
        },
        "default": {
            "number": "112",
            "name": "Single Emergency Helpline",
            "notes": "Unified emergency number where available."
        }
    },

    "EU_GENERIC": {
        # Fallback for EU countries if you don’t have country-specific entries
        "aliases": ["france", "germany", "spain", "italy", "netherlands", "belgium", "sweden", "norway", "finland"],
        "categories": {
            "medical": {
                "number": "112",
                "name": "European Emergency Number",
                "notes": "Ask for an ambulance."
            },
            "police": {
                "number": "112",
                "name": "European Emergency Number",
                "notes": "Ask for police."
            },
            "fire": {
                "number": "112",
                "name": "European Emergency Number",
                "notes": "Ask for fire brigade."
            },
            "crisis": {
                "number": "116 123",
                "name": "Emotional Support (example)",
                "notes": "Varies by country; verify per country in your dataset."
            },
            "other": {
                "number": "112",
                "name": "European Emergency Number",
                "notes": "General emergencies."
            }
        },
        "default": {
            "number": "112",
            "name": "European Emergency Number",
            "notes": "Emergency services across the EU."
        }
    }
}
