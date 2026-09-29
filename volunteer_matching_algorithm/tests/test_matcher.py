import sys
import types
import numpy as np
import pandas as pd
# Mock app.embeddings before importing matcher.
# This prevents the unit test from loading SentenceTransformer/PyTorch.
fake_embeddings = types.ModuleType("app.embeddings")

fake_embeddings.get_embedding = lambda text: np.array([1.0])
fake_embeddings.cosine_similarity = lambda a, b: 0.0

sys.modules["app.embeddings"] = fake_embeddings

from app import matcher


def test_match_volunteers_returns_ranked_results(monkeypatch):
    volunteers = pd.DataFrame([
        {
            "VolunteerId": "V1",
            "VolunteerName": "Best Volunteer",
            "Skills": "Medical Aid",
            "PreferredServiceAreas": "Healthcare",
            "Status": "Active",
            "LanguagesSpoken": "English",
            "TransportationAvailability": "Yes",
            "WillingnessToTravel": "High",
            "Rating": 5.0,
        },
        {
            "VolunteerId": "V2",
            "VolunteerName": "Second Volunteer",
            "Skills": "Cooking",
            "PreferredServiceAreas": "Food",
            "Status": "Active",
            "LanguagesSpoken": "English",
            "TransportationAvailability": "Yes",
            "WillingnessToTravel": "Moderate",
            "Rating": 4.0,
        },
    ])

    requests = pd.DataFrame([
        {
            "RequestId": "REQ_TEST",
            "RequestCategory": "Medical",
            "Subject": "First Aid",
            "Description": "Need medical assistance",
            "LanguagePreferred": "English",
            "RequestType": "Remote",
        }
    ])

    monkeypatch.setattr(
        matcher,
        "load_volunteers",
        lambda: volunteers.copy()
    )

    monkeypatch.setattr(
        matcher,
        "load_requests",
        lambda: requests.copy()
    )

    def fake_prepare_tfidf(volunteer_texts, request_text):
        volunteer_vectors = np.array([
            [1.0],
            [0.2],
        ])

        request_vector = np.array([[1.0]])

        class FakeMatrix:
            def __init__(self, values):
                self.values = values

            def __matmul__(self, other):
                return FakeMatrix(self.values)

            def toarray(self):
                return self.values

            @property
            def T(self):
                return self

        return FakeMatrix(volunteer_vectors), FakeMatrix(request_vector)

    monkeypatch.setattr(
        matcher,
        "prepare_tfidf",
        fake_prepare_tfidf
    )

    monkeypatch.setattr(
        matcher,
        "get_embedding",
        lambda text: np.array([1.0])
    )

    monkeypatch.setattr(
        matcher,
        "cosine_similarity",
        lambda a, b: 0.0
    )

    monkeypatch.setattr(
        matcher,
        "calculate_score",
        lambda row, req, text_sim: text_sim
    )

    result = matcher.match_volunteers("REQ_TEST", top_k=2)

    assert not result.empty
    assert len(result) == 2
    assert result.iloc[0]["VolunteerName"] == "Best Volunteer"
    assert result.iloc[0]["FinalScore"] > result.iloc[1]["FinalScore"]