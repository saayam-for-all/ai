def calculate_score(row, req, text_sim):
    """
    Calculate final matching score with heavy emphasis on semantic similarity.
    This works for ANY type of request/skill, not just predefined categories.

    Weights:
    - 50% Text similarity (BERT + TF-IDF on full request description)
    - 20% Skill-to-category semantic match (BERT on skills vs category)
    - 15% Language match (essential for communication)
    - 10% Location/transportation (practical logistics)
    - 5% Volunteer rating (quality indicator)
    """
    score = 0

    # Semantic understanding of full request is most important
    score += 0.50 * text_sim

    # Semantic skill match (now using BERT, not keywords)
    score += 0.20 * row["SkillMatch"]

    # Language match is critical for communication
    score += 0.15 * row["LanguageMatch"]

    # Location matters for in-person requests
    score += 0.10 * row["LocationScore"]

    # Volunteer rating (normalized to 0-1)
    score += 0.05 * (row["Rating"] / 5)

    return score