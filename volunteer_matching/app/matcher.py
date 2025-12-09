from app.data_loader import load_volunteers, load_requests
from app.preprocessing import prepare_tfidf
from app.embeddings import get_embedding, cosine_similarity
from app.scoring import calculate_score

def match_volunteers(request_id, top_k=3):
    volunteers = load_volunteers()
    requests = load_requests()

    req = requests[requests["RequestId"] == request_id].iloc[0]

    active = volunteers[volunteers["Status"] == "Active"].copy()
    if active.empty:
        return []

    # text preparation
    volunteer_texts = active["Skills"].astype(str).tolist()
    req_text = str(req["Subject"]) + " " + str(req["Description"])

    # TF-IDF
    vol_vecs, req_vec = prepare_tfidf(volunteer_texts, req_text)
    tfidf_sims = (vol_vecs @ req_vec.T).toarray().flatten()
    active["TFIDF_Sim"] = tfidf_sims

    # embeddings
    req_emb = get_embedding(req_text)
    vol_embs = [get_embedding(v) for v in volunteer_texts]
    active["BERT_Sim"] = [cosine_similarity(vol_embs[i], req_emb) for i in range(len(active))]

    # language match
    req_lang = req["LanguagePreferred"]
    active["LanguageMatch"] = active["LanguagesSpoken"].apply(
        lambda x: 1 if req_lang in x else 0
    )

    # skill match
    req_skill = req["RequestCategory"].split()[0]
    active["SkillMatch"] = active["Skills"].apply(
        lambda s: 1 if req_skill.lower() in s.lower() else 0
    )

    # location
    if req["RequestType"] == "Remote":
        active["LocationScore"] = 1
    else:
        active["LocationScore"] = active["TransportationAvailability"].apply(
            lambda x: 1 if x == "Yes" else 0
        )

    # text similarity combined
    active["TextSim"] = (
        0.40 * active["TFIDF_Sim"] +
        0.60 * active["BERT_Sim"]
    )

    # final score
    active["FinalScore"] = active.apply(
        lambda r: calculate_score(r, req, r["TextSim"]), axis=1
    )

    active = active.sort_values(by="FinalScore", ascending=False)
    return active.head(top_k)
