import sys
import types
import numpy as np
import pandas as pd
from types import SimpleNamespace
# Mock app.embeddings before importing matcher.
# This prevents the unit test from loading SentenceTransformer/PyTorch.
fake_embeddings = types.ModuleType("app.embeddings")

fake_embeddings.get_embedding = lambda text: np.array([1.0])
fake_embeddings.cosine_similarity = lambda a, b: 0.0

sys.modules["app.embeddings"] = fake_embeddings

from app import matcher
from app import crud_requests



def test_match_volunteers_returns_ranked_results(monkeypatch):
    volunteers = pd.DataFrame([
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
        {
            "VolunteerId": "V1",
            "VolunteerName": "Best Volunteer",
            "Skills": "Medical Aid",
            "PreferredServiceAreas": "Healthcare",
            "Status": "Active",
            "LanguagesSpoken": "English",
            "TransportationAvailability": "Yes",
            "WillingnessToTravel": "High",
            "Rating": 5.0
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
            [0.2],
            [1.0],
        ])

        request_vector = np.array([[1.0]])

        class FakeMatrix:
            def __init__(self, values):
                self.values = values

            def __matmul__(self, other):
                return FakeMatrix(self.values @ other.values)

            def toarray(self):
                return self.values

            @property
            def T(self):
                return FakeMatrix(self.values.T)

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

def test_match_volunteer_group_with_blank_vol_ids(monkeypatch):
    requests = pd.DataFrame([
        {
            "RequestId": "REQ_GROUP",
            "RequestCategory": "Community",
            "Subject": "Community Event",
            "Description": "Need multiple volunteers",
            "LanguagePreferred": "English",
            "RequestType": "Remote",
        }
    ])

    candidate_pool = pd.DataFrame([
        {
            "VOL_ID": "",
            "VolunteerName": "Volunteer 1",
            "FinalScore": 0.9,
            "Skills": "Skill A",
            "LanguagesSpoken": "English",
            "Location": "Location A",
            "Rating": 5.0,
        },
        {
            "VOL_ID": "",
            "VolunteerName": "Volunteer 2",
            "FinalScore": 0.8,
            "Skills": "Skill B",
            "LanguagesSpoken": "English",
            "Location": "Location B",
            "Rating": 4.0,
        },
        {
            "VOL_ID": "",
            "VolunteerName": "Volunteer 3",
            "FinalScore": 0.7,
            "Skills": "Skill C",
            "LanguagesSpoken": "English",
            "Location": "Location C",
            "Rating": 3.0,
        },
        {
            "VOL_ID": "",
            "VolunteerName": "Volunteer 4",
            "FinalScore": 0.6,
            "Skills": "Skill D",
            "LanguagesSpoken": "English",
            "Location": "Location D",
            "Rating": 2.0,
        },
    ])

    monkeypatch.setattr(
        matcher,
        "load_volunteers",
        lambda: candidate_pool.copy()
    )

    monkeypatch.setattr(
        matcher,
        "load_requests",
        lambda: requests.copy()
    )

    monkeypatch.setattr(
        matcher,
        "match_volunteers",
        lambda request_id, top_k: candidate_pool.copy()
    )

    monkeypatch.setattr(
        matcher,
        "calculate_diversity_score",
        lambda candidate, selected, req: candidate["FinalScore"]
    )

    result = matcher.match_volunteer_group("REQ_GROUP", group_size=3)

    assert len(result) == 3
    assert result["VolunteerName"].nunique() == 3


def test_add_request_populates_request_id(monkeypatch, tmp_path):
    temp_csv = tmp_path / "requests.csv"

    monkeypatch.setattr(
        crud_requests,
        "CSV_PATH",
        str(temp_csv)
    )

    request = SimpleNamespace(
        RequestCategory="Medical",
        Location="Remote",
        RequestType="Remote",
        PriorityLevel="High",
        LeadVolunteerNeeded=False,
        ForSelfOrOthers="Self",
        IsCalamity=False,
        Subject="First Aid",
        Description="Need medical assistance",
        LanguagePreferred="English",
        RequestorId="USER_TEST",
        Status="Open",
        Duration="1 hour",
    )

    result = crud_requests.add_request(request)

    saved_requests = pd.read_csv(temp_csv)

    assert len(saved_requests) == 1
    assert saved_requests.iloc[0]["RequestId"] == result["request_id"]
    assert saved_requests.iloc[0]["REQ_ID"] == result["request_id"]
    assert saved_requests.iloc[0]["RequestId"] == saved_requests.iloc[0]["REQ_ID"]
    