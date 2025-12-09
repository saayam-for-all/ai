def calculate_score(row, req, text_sim):
    score = 0

    score += 0.50 * text_sim
    score += 0.20 * row["SkillMatch"]
    score += 0.15 * row["LanguageMatch"]
    score += 0.10 * row["LocationScore"]
    score += 0.05 * (row["Rating"] / 5)

    return score
