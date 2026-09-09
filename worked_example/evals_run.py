"""Reference solution for Mission 8.

Deterministic scorer so the harness can be exercised without a live model.
A real submission would call the classifier; the contract the check cares
about is GOLDEN, PROMPT, CONTROL_PROMPT and run() -> {"score": float}.
"""

PROMPT = ("Classify the help request into one category. Keep the person's own "
          "words. If unsure, return nothing rather than guessing.")

CONTROL_PROMPT = "Classify this. Always pick something."

GOLDEN = [
    ("my apartment has a plumbing leak", "PLUMBING"),
    ("I need help with math homework", "TUTORING"),
    ("looking for entry level software roles", "JOBS"),
    ("I cannot afford my medication", "MEDICINE"),
    ("my elderly father needs daily care", "ELDERLY_CARE"),
    ("need a ride to a dialysis appointment", "TRANSPORT"),
    ("the heating stopped working", "HVAC"),
    ("help writing a resume", "JOBS"),
    ("groceries for this week", "FOOD"),
    ("my landlord is evicting me", "LEGAL"),
    ("need winter coats for two children", "CLOTHING"),
    ("help filing taxes", "FINANCE"),
    ("broken wheelchair ramp", "ACCESSIBILITY"),
    ("counselling after a bereavement", "MENTAL_HEALTH"),
    ("english lessons for my mother", "TUTORING"),
    ("cannot pay the electricity bill", "UTILITIES"),
    ("need childcare on thursdays", "CHILDCARE"),
    ("help moving furniture", "MOVING"),
    ("laptop for online classes", "EDUCATION_EQUIPMENT"),
    ("dog needs veterinary care", "PET_CARE"),
    ("leaking roof after the storm", "HOME_REPAIR"),
    ("job interview clothes", "CLOTHING"),
    ("applying for disability benefits", "BENEFITS"),
    ("food for a family of five", "FOOD"),
    ("car will not start and I work nights", "VEHICLE_REPAIR"),
    ("need a translator for a hospital visit", "LANGUAGE_SUPPORT"),
    # deliberately hard: two symptoms at once
    ("no heat and a burst pipe", "PLUMBING"),
    # deliberately hard: uncertain cause
    ("something is wrong with the electrics, lights flicker", "ELECTRICAL"),
    # deliberately hard: should produce nothing
    ("asdfgh qwerty zxcvb", None),
    # deliberately hard: not English
    ("necesito ayuda con la comida", "FOOD"),
    ("I am homeless and need shelter tonight", "SHELTER"),
]


def _predict(prompt, text):
    """Stand-in classifier. The good prompt abstains on nonsense; the control
    always guesses, which is exactly the failure the metric should punish."""
    table = {t: c for t, c in GOLDEN}
    guess = table.get(text)
    if guess is None:
        return "FINANCE" if prompt is CONTROL_PROMPT else None
    return guess


def run(prompt):
    hits = sum(1 for text, want in GOLDEN if _predict(prompt, text) == want)
    invented = sum(1 for text, want in GOLDEN
                   if want is None and _predict(prompt, text) is not None)
    # Accuracy, with inventing an answer where none exists penalised twice over.
    score = (hits - 2 * invented) / len(GOLDEN)
    return {"score": round(score, 4), "hits": hits, "invented": invented,
            "n": len(GOLDEN)}
