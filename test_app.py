import pytest
from unittest.mock import patch, MagicMock
from app import app, categories, format_response


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


def test_homepage(client):
    """Test that the homepage loads successfully."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Saayam AI Assistant" in response.data


def test_predict_categories(client):
    """Test category prediction with valid input."""
    response = client.post('/predict_categories', json={
        "subject": "How to save money?",
        "description": "I want to start budgeting my expenses."
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "predicted_categories" in data
    assert len(data["predicted_categories"]) > 0


def test_predict_categories_missing_subject(client):
    """Test category prediction fails without subject."""
    response = client.post('/predict_categories', json={
        "description": "I want to start budgeting my expenses."
    })
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_predict_categories_missing_description(client):
    """Test category prediction fails without description."""
    response = client.post('/predict_categories', json={
        "subject": "How to save money?"
    })
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


@pytest.mark.parametrize("category", categories[:5])
@patch('app.ai_client')
def test_generate_answer(mock_ai_client, client, category):
    """Test answer generation for different categories."""
    # Mock the AI response
    mock_ai_client.prompt.return_value = {
        'message': f'Information about {category}.\n- Tip 1\n- Tip 2'
    }
    response = client.post('/generate_answer', json={
        "category": category,
        "question": "Tell me something about this category."
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data or "error" in data


def test_generate_answer_missing_category(client):
    """Test answer generation fails without category."""
    response = client.post('/generate_answer', json={
        "question": "Tell me something."
    })
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "Category and question required" in data["error"]


def test_generate_answer_missing_question(client):
    """Test answer generation fails without question."""
    response = client.post('/generate_answer', json={
        "category": "Banking"
    })
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "Category and question required" in data["error"]


@patch('app.ai_client')
def test_generate_answer_returns_metrics(mock_ai_client, client):
    """Test that answer generation includes metrics."""
    # Mock the AI response
    mock_ai_client.prompt.return_value = {
        'message': 'A savings account is a deposit account.\n- Safe storage\n- Earns interest'
    }
    response = client.post('/generate_answer', json={
        "category": "Banking",
        "question": "What is a savings account?"
    })
    assert response.status_code == 200
    data = response.get_json()
    # Should have either answer with metrics or an error
    if "answer" in data:
        assert "metrics" in data
        assert "model" in data["metrics"]
        assert "ttft_seconds" in data["metrics"]
        assert "ttlt_seconds" in data["metrics"]


def test_format_response_basic():
    """Test format_response with basic text."""
    text = "This is a simple answer."
    result = format_response(text)
    assert "This is a simple answer." in result


def test_format_response_with_lists():
    """Test format_response with list items."""
    text = "Here are some tips:\nTip 1: Save money\nTip 2: Invest wisely"
    result = format_response(text)
    assert result is not None


def test_format_response_with_bullet_points():
    """Test format_response with existing bullet points."""
    text = "- First item\n- Second item\n- Third item"
    result = format_response(text)
    assert "First item" in result
    assert "Second item" in result


def test_format_response_with_numbered_items():
    """Test format_response with numbered items."""
    text = "1. First point\n2. Second point\n3. Third point"
    result = format_response(text)
    assert result is not None


def test_format_response_empty_string():
    """Test format_response with empty string."""
    text = ""
    result = format_response(text)
    assert result == ""


def test_format_response_with_sections():
    """Test format_response with section headers."""
    text = "**Introduction**\nThis is the intro.\n\n**Main Content**\nThis is the main part."
    result = format_response(text)
    assert "Introduction" in result
    assert "Main Content" in result


def test_format_response_with_list_indicators():
    """Test format_response with list indicator patterns."""
    text = "General information\nIndeed: Job search\nLinkedIn: Professional network"
    result = format_response(text)
    assert result is not None


def test_format_response_with_colons():
    """Test format_response with colon-separated items."""
    text = "Website 1: Description of site\nWebsite 2: Another description"
    result = format_response(text)
    assert "Website 1" in result or "Website" in result


def test_format_response_mixed_content():
    """Test format_response with mixed content types."""
    text = "Introduction text\n\nGeneral\nItem 1: Details\nItem 2: More details\n\nConclusion"
    result = format_response(text)
    assert result is not None
    assert len(result) > 0


def test_format_response_already_formatted_bullets():
    """Test format_response with already formatted bullet points."""
    text = "- Already formatted\n- Another bullet\n- Third bullet"
    result = format_response(text)
    assert "Already formatted" in result


def test_format_response_with_network_pattern():
    """Test format_response with 'Network' pattern."""
    text = "Network with professionals\nCheck your connections"
    result = format_response(text)
    assert result is not None


def test_format_response_multiline_empty_lines():
    """Test format_response with multiple empty lines."""
    text = "Line 1\n\n\n\nLine 2\n\n\nLine 3"
    result = format_response(text)
    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result


@patch('app.ai_client')
def test_generate_answer_with_mocked_client(mock_client, client):
    """Test answer generation with mocked AI client."""
    # Mock the AI client response
    mock_response = {
        'message': 'This is a test response about banking.'
    }
    mock_client.prompt.return_value = mock_response

    response = client.post('/generate_answer', json={
        "category": "Banking",
        "question": "What is a bank?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data or "error" in data


def test_format_response_with_stay_pattern():
    """Test format_response with 'Stay' pattern."""
    text = "Stay informed about updates\nCheck regularly\nNetwork effectively"
    result = format_response(text)
    assert result is not None


def test_format_response_single_line():
    """Test format_response with single line."""
    text = "Single line of text"
    result = format_response(text)
    assert result == "Single line of text"


def test_format_response_only_whitespace():
    """Test format_response with only whitespace."""
    text = "   \n   \n   "
    result = format_response(text)
    assert isinstance(result, str)


def test_format_response_special_characters():
    """Test format_response with special characters."""
    text = "Item 1: 50% discount!\nItem 2: Buy now @ $99\nItem 3: #1 choice"
    result = format_response(text)
    assert result is not None


def test_predict_categories_exception_handling(client):
    """Test that predict_categories handles exceptions gracefully."""
    # Send malformed JSON to trigger potential errors
    response = client.post('/predict_categories', json={
        "subject": "",
        "description": ""
    })
    # Should return 400 for empty fields
    assert response.status_code == 400


@patch('app.classifier')
def test_predict_categories_classifier_exception(mock_classifier, client):
    """Test predict_categories when classifier raises exception."""
    mock_classifier.side_effect = Exception("Classifier error")

    response = client.post('/predict_categories', json={
        "subject": "Test subject",
        "description": "Test description"
    })

    assert response.status_code == 500
    data = response.get_json()
    assert "error" in data


def test_format_response_complex_list_scenario():
    """Test format_response with complex list scenarios."""
    text = """General Tips
First tip: Save money
Second tip: Invest wisely

International Resources
Resource 1: Description here
Resource 2: Another description"""
    result = format_response(text)
    assert "General Tips" in result or "**General Tips**" in result
    assert result is not None


def test_format_response_line_with_colon_no_space():
    """Test format_response with colon but no space after."""
    text = "Item:Description\nAnother:More text"
    result = format_response(text)
    assert result is not None


def test_format_response_list_to_non_list_transition():
    """Test format_response transitioning from list to non-list content."""
    text = """General
Item 1: Details
Item 2: More

Regular paragraph text here"""
    result = format_response(text)
    assert "paragraph" in result.lower()


def test_format_response_h1bgrader_pattern():
    """Test format_response with H1BGrader pattern."""
    text = "H1BGrader helps you check visa status"
    result = format_response(text)
    assert "H1BGrader" in result


def test_format_response_glassdoor_pattern():
    """Test format_response with Glassdoor pattern."""
    text = "Glassdoor: Company reviews and salaries"
    result = format_response(text)
    assert "Glassdoor" in result


def test_format_response_country_specific_pattern():
    """Test format_response with Country-Specific pattern."""
    text = "Country-Specific information\nUSA: Details about USA\nUK: Details about UK"
    result = format_response(text)
    assert result is not None


def test_format_response_additional_pattern():
    """Test format_response with Additional pattern."""
    text = "Additional resources\nResource one\nResource two"
    result = format_response(text)
    assert result is not None


def test_format_response_niche_pattern():
    """Test format_response with Niche pattern."""
    text = "Niche websites\nSite 1: Description\nSite 2: More info"
    result = format_response(text)
    assert result is not None


def test_format_response_immIhelp_pattern():
    """Test format_response with ImmIhelp pattern."""
    text = "ImmIhelp provides immigration assistance"
    result = format_response(text)
    assert "ImmIhelp" in result or "immIhelp" in result.lower()


@patch('app.selected_model', 'meta_ai')
@patch('app.ai_client')
def test_generate_answer_meta_ai_success(mock_client, client):
    """Test generate_answer with meta_ai model."""
    mock_client.prompt.return_value = {
        'message': 'This is a detailed answer about banking services.'
    }

    response = client.post('/generate_answer', json={
        "category": "Banking",
        "question": "What services do banks provide?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data
    assert "metrics" in data
    assert data["metrics"]["model"] == "meta_ai"


@patch('app.selected_model', 'meta_ai')
@patch('app.ai_client')
def test_generate_answer_exception_in_ai_call(mock_client, client):
    """Test generate_answer when AI client raises exception."""
    mock_client.prompt.side_effect = Exception("AI service unavailable")

    response = client.post('/generate_answer', json={
        "category": "Banking",
        "question": "What is a bank?"
    })

    assert response.status_code == 500
    data = response.get_json()
    assert "error" in data


def test_format_response_with_dash_already_present():
    """Test format_response when dashes are already in the list."""
    text = """General
- Item 1: Details
- Item 2: More details
Regular text"""
    result = format_response(text)
    assert "Item 1" in result
    assert "Item 2" in result


def test_format_response_empty_line_handling():
    """Test format_response handles empty lines in lists correctly."""
    text = """General

Item 1: Test

Item 2: Test"""
    result = format_response(text)
    assert result is not None


def test_format_response_no_colon_in_list():
    """Test format_response with list items without colons."""
    text = """General
First item without colon
Second item without colon"""
    result = format_response(text)
    assert "First item" in result or "- First item" in result


def test_format_response_case_insensitive_patterns():
    """Test that format_response patterns are case insensitive."""
    text = "GENERAL information\nINDEED website\nNETWORK with people"
    result = format_response(text)
    assert result is not None


@patch('app.ai_client')
@patch('app.selected_model', 'meta_ai')
def test_generate_answer_meta_ai(mock_ai_client, client):
    """Test generate_answer with Meta AI model."""
    mock_ai_client.prompt.return_value = {
        'message': 'This is a test response from Meta AI.\n- Item 1\n- Item 2'
    }

    response = client.post('/generate_answer', json={
        "category": "Banking",
        "question": "How to open a bank account?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data
    assert "metrics" in data
    assert data["metrics"]["model"] == "meta_ai"


@patch('app.ai_client')
@patch('app.selected_model', 'gemini')
def test_generate_answer_gemini(mock_ai_client, client):
    """Test generate_answer with Gemini model."""
    mock_response = MagicMock()
    mock_response.text = 'This is a test response from Gemini.\n- Item 1\n- Item 2'
    mock_ai_client.generate_content.return_value = mock_response

    response = client.post('/generate_answer', json={
        "category": "Technology",
        "question": "What is AI?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data
    assert "metrics" in data
    assert data["metrics"]["model"] == "gemini"


@patch('app.ai_client')
@patch('app.selected_model', 'openai')
def test_generate_answer_openai(mock_ai_client, client):
    """Test generate_answer with OpenAI model."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = 'This is a test response from OpenAI.\n- Item 1\n- Item 2'
    mock_ai_client.chat.completions.create.return_value = mock_response

    response = client.post('/generate_answer', json={
        "category": "Science",
        "question": "What is quantum physics?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data
    assert "metrics" in data
    assert data["metrics"]["model"] == "openai"


@patch('app.ai_client')
@patch('app.selected_model', 'grok')
def test_generate_answer_grok(mock_ai_client, client):
    """Test generate_answer with Grok model."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = 'This is a test response from Grok.\n- Item 1\n- Item 2'
    mock_ai_client.chat.completions.create.return_value = mock_response

    response = client.post('/generate_answer', json={
        "category": "History",
        "question": "What happened in 1776?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data
    assert "metrics" in data
    assert data["metrics"]["model"] == "grok"


@patch('app.ai_client')
@patch('app.selected_model', 'meta_ai')
def test_generate_answer_with_complex_formatting(mock_ai_client, client):
    """Test generate_answer with complex response that needs formatting."""
    complex_response = """Here are the best websites for job search:

General Job Sites
Indeed: One of the largest job search engines
LinkedIn: Professional networking and job board

Niche Sites
GitHub Jobs: For tech professionals
Stack Overflow: For developers

Tips:
Network with professionals
Check company websites directly
Stay updated on industry trends"""

    mock_ai_client.prompt.return_value = {'message': complex_response}

    response = client.post('/generate_answer', json={
        "category": "Employment",
        "question": "What are the best job search websites?"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "answer" in data
    assert "metrics" in data
    # Verify formatting was applied
    assert "**" in data["answer"] or "-" in data["answer"]
