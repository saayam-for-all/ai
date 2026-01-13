import pytest
from app import app, categories


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


def test_homepage(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b"Saayam AI Assistant" in response.data


def test_predict_categories(client):
    response = client.post('/predict_categories', json={
        "subject": "How to save money?",
        "description": "I want to start budgeting my expenses."
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "predicted_categories" in data
    assert len(data["predicted_categories"]) > 0


@pytest.mark.parametrize("category", categories[:5])  # Use a few categories for demo
def test_generate_answer(client, category):
    response = client.post('/generate_answer', json={
        "category": category,
        "question": "Tell me something about this category."
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data or "error" in data
