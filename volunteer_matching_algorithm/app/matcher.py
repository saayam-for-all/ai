from app.data_loader import load_volunteers, load_requests
from app.preprocessing import prepare_tfidf
from app.embeddings import get_embedding, cosine_similarity
from app.scoring import calculate_score
import pandas as pd


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

    # Find the request
    matching_requests = requests[requests["REQ_ID"] == request_id]
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
    active["SkillMatch"] = skill_sims  # Now semantic, not keyword-based

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
            lambda x: 1 if x == "Yes" else 0.3  # Give partial score even without transport
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