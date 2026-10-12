import pytest



def test_real_model_matches_danny_for_req4():
    # Import here to load the actual embeddings model.
    from app.matcher import match_volunteers

    results = match_volunteers("REQ_4", top_k=20)

    assert not results.empty

    # Danny should be the highest-ranked volunteer.
    assert results.iloc[0]["VolunteerName"] == "Danny"

    # Allow a small tolerance for model/library differences.
    assert results.iloc[0]["FinalScore"] == pytest.approx(
        0.76, abs=0.02
    )