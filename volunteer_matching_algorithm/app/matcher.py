from app.data_loader import load_volunteers, load_requests
from app.preprocessing import prepare_tfidf
from app.embeddings import get_embedding, cosine_similarity
from app.scoring import calculate_score
import pandas as pd
import numpy as np


def match_volunteers(request_id, top_k=3):
    """
    Match volunteers to a request using hybrid approach:
    - Semantic matching via BERT embeddings (understands meaning) - PRIMARY
    - Keyword matching via TF-IDF (exact term overlap)
    - Direct attribute matching (language, location)

    This approach works for ANY skill/request type, not just predefined categories.
    """

    # Load clean data (NaN already handled in data_loader)
    volunteers = load_volunteers()
    requests = load_requests()

    # Handle both column naming conventions (RequestId vs REQ_ID)
    req_id_column = "REQ_ID" if "REQ_ID" in requests.columns else "RequestId"

    # Find the request
    matching_requests = requests[requests[req_id_column] == request_id]
    if matching_requests.empty:
        return pd.DataFrame()

    req = matching_requests.iloc[0]

    # Get active volunteers only
    active = volunteers[volunteers["Status"] == "Active"].copy()
    if active.empty:
        return pd.DataFrame()

    # === SEMANTIC MATCHING (CORE) ===
    # Prepare rich text combining multiple fields for better semantic understanding
    volunteer_texts = (
            active["Skills"] + " " +
            active["PreferredServiceAreas"]
    ).tolist()

    # Rich request text with full context
    req_text = (
            req["RequestCategory"] + " " +
            req["Subject"] + " " +
            req["Description"]
    )

    # TF-IDF similarity (keyword-based matching)
    vol_vecs, req_vec = prepare_tfidf(volunteer_texts, req_text)
    tfidf_sims = (vol_vecs @ req_vec.T).toarray().flatten()
    active["TFIDF_Sim"] = tfidf_sims

    # BERT embeddings similarity (semantic understanding - understands meaning)
    req_emb = get_embedding(req_text)
    vol_embs = [get_embedding(v) for v in volunteer_texts]
    active["BERT_Sim"] = [cosine_similarity(vol_embs[i], req_emb) for i in range(len(active))]

    # === ADDITIONAL SKILL MATCHING (Semantic) ===
    # Compare skills directly to request category for additional signal
    req_category_emb = get_embedding(req["RequestCategory"])
    skill_sims = [cosine_similarity(get_embedding(skill), req_category_emb)
                  for skill in active["Skills"].tolist()]
    active["SkillMatch"] = skill_sims

    # === DIRECT ATTRIBUTE MATCHING ===

    # Language match - exact match required for communication
    req_lang = req["LanguagePreferred"]
    active["LanguageMatch"] = active["LanguagesSpoken"].apply(
        lambda x: 1 if req_lang in x else 0
    )

    # Location/Transportation score
    if req["RequestType"] == "Remote":
        active["LocationScore"] = 1
    else:
        # For in-person, prioritize volunteers with transportation
        active["LocationScore"] = active["TransportationAvailability"].apply(
            lambda x: 1 if x == "Yes" else 0.3
        )

        # Bonus for high willingness to travel for in-person requests
        active["LocationScore"] = active.apply(
            lambda row: row["LocationScore"] * (
                1.2 if row["WillingnessToTravel"] == "High" else
                1.0 if row["WillingnessToTravel"] == "Moderate" else
                0.8
            ), axis=1
        )
        # Cap at 1.0
        active["LocationScore"] = active["LocationScore"].clip(upper=1.0)

    # Combined text similarity - heavily weighted toward semantic understanding
    active["TextSim"] = 0.30 * active["TFIDF_Sim"] + 0.70 * active["BERT_Sim"]

    # Calculate final score
    active["FinalScore"] = active.apply(
        lambda r: calculate_score(r, req, r["TextSim"]), axis=1
    )

    # Sort by score and return top_k
    active = active.sort_values(by="FinalScore", ascending=False)
    return active.head(top_k)


def match_volunteer_group(request_id, group_size=5):
    """
    Match a GROUP of volunteers for requests that need multiple people.
    
    Strategy:
    1. Get top candidates based on relevance (2x group_size pool)
    2. Select diverse group with complementary skills
    3. Ensure language coverage and geographic distribution
    4. Balance experience levels (ratings)
    
    Use cases:
    - Community events needing multiple helpers
    - Large-scale disaster relief
    - Educational programs needing teaching teams
    - Construction/renovation projects
    """
    
    # Load data
    volunteers = load_volunteers()
    requests = load_requests()
    
    matching_requests = requests[requests["REQ_ID"] == request_id]
    if matching_requests.empty:
        return pd.DataFrame()
    
    req = matching_requests.iloc[0]
    
    # Get larger pool of candidates (2x desired group size)
    candidate_pool = match_volunteers(request_id, top_k=group_size * 2)
    
    if candidate_pool.empty or len(candidate_pool) < group_size:
        # Return whatever we have if not enough candidates
        return candidate_pool
    
    # === GROUP SELECTION ALGORITHM ===
    selected = []
    remaining = candidate_pool.copy()
    
    # 1. Always pick the highest scorer first (team leader candidate)
    selected.append(remaining.iloc[0])
    remaining = remaining.iloc[1:]
    
    # 2. Select remaining members for diversity
    while len(selected) < group_size and not remaining.empty:
        best_addition = None
        best_diversity_score = -1
        
        for idx, candidate in remaining.iterrows():
            diversity_score = calculate_diversity_score(candidate, selected, req)
            
            if diversity_score > best_diversity_score:
                best_diversity_score = diversity_score
                best_addition = candidate
        
        if best_addition is not None:
            selected.append(best_addition)
            remaining = remaining[remaining["VOL_ID"] != best_addition["VOL_ID"]]
        else:
            break
    
    # Convert back to DataFrame
    result = pd.DataFrame(selected)
    
    # Add group-specific metadata
    result["GroupRole"] = ["Lead"] + ["Member"] * (len(result) - 1)
    
    return result


def calculate_diversity_score(candidate, selected_group, request):
    """
    Calculate how much diversity a candidate adds to the existing group.
    Higher score = more complementary to current group.
    """
    score = 0
    
    # Base relevance score (still important)
    score += 0.3 * candidate["FinalScore"]
    
    # Skill diversity - reward different skill sets
    candidate_skills = set(candidate["Skills"].split(", "))
    
    existing_skills = set()
    for member in selected_group:
        existing_skills.update(member["Skills"].split(", "))
    
    new_skills = candidate_skills - existing_skills
    skill_diversity = len(new_skills) / max(len(candidate_skills), 1)
    score += 0.25 * skill_diversity
    
    # Language diversity - ensure broad coverage
    candidate_langs = set(candidate["LanguagesSpoken"].split(", "))
    
    existing_langs = set()
    for member in selected_group:
        existing_langs.update(member["LanguagesSpoken"].split(", "))
    
    new_langs = candidate_langs - existing_langs
    lang_diversity = len(new_langs) / max(len(candidate_langs), 1)
    score += 0.20 * lang_diversity
    
    # Rating balance - mix experienced and newer volunteers
    existing_ratings = [member["Rating"] for member in selected_group]
    avg_rating = np.mean(existing_ratings)
    
    # Reward candidates that balance the average (not too similar)
    rating_balance = 1 - abs(candidate["Rating"] - avg_rating) / 5.0
    score += 0.15 * rating_balance
    
    # Location diversity (for in-person events)
    if request["RequestType"] != "Remote":
        candidate_loc = candidate["Location"]
        
        existing_locs = [member["Location"] for member in selected_group]
        
        # Reward if from different location (geographic spread)
        if candidate_loc not in existing_locs:
            score += 0.10
    
    return score