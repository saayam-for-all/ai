from flask import Flask, render_template, request, jsonify
from transformers import pipeline
from meta_ai_api import MetaAI
import os
import re  # For text processing

# Initialize Meta AI client
client = MetaAI()

# Category list (unchanged)
categories = [
    "Banking", "Books", "Clothes", "College Admissions", "Cooking",
    "Elementary Education", "Middle School Education", "High School Education", "University Education",
    "Employment", "Finance", "Food", "Gardening", "Homelessness", "Housing", "Jobs", "Investing",
    "Matrimonial", "Brain Medical", "Depression Medical", "Eye Medical", "Hand Medical",
    "Head Medical", "Leg Medical", "Rental", "School", "Shopping",
    "Baseball Sports", "Basketball Sports", "Cricket Sports", "Handball Sports",
    "Jogging Sports", "Hockey Sports", "Running Sports", "Tennis Sports",
    "Stocks", "Travel", "Tourism"
]

# Zero-shot classification pipeline (unchanged)
classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html', categories=categories)

@app.route('/predict_categories', methods=['POST'])
def predict_categories():
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")
    if not subject or not description:
        return jsonify({"error": "Subject and description required"}), 400
    prompt = f"{subject}. {description}"
    try:
        result = classifier(prompt, categories)
        return jsonify({"predicted_categories": result['labels'][:3]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate_answer', methods=['POST'])
def generate_answer():
    data = request.get_json()
    category = data.get("category")
    question = data.get("question")
    if not category or not question:
        return jsonify({"error": "Category and question required"}), 400
    
    # Create a more specific prompt with formatting instructions
    prompt = (
        f"Category: {category}\n"
        f"Question: {question}\n\n"
        "Please provide a detailed and well-structured answer. Format your response as follows:\n"
        "- For any list of items (e.g., websites, tips, steps, examples, or recommendations), use bullet points starting with '-' (e.g., - Item).\n"
        "- Use bold text (e.g., **text**) for headings or key terms, such as section titles or important concepts.\n"
        "- Use line breaks to separate paragraphs or sections for clarity.\n"
        "- Ensure the response is clear, concise, and easy to read.\n"
        "- If the question asks for recommendations, resources, or a list, always present them as bullet points.\n"
        "For example, if asked for websites, format the response like this:\n"
        "**Websites**\n"
        "- Website 1: Description.\n"
        "- Website 2: Description.\n"
    )
    
    try:
        # Get the response from Meta AI
        response = client.prompt(prompt)
        raw_answer = response['message'].strip()

        # Format the response to ensure consistency
        formatted_answer = format_response(raw_answer)

        return jsonify({"answer": formatted_answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def format_response(text):
    """
    Format the raw AI response to ensure bullet points and structure, even if the AI doesn't follow instructions.
    """
    # Split the text into lines
    lines = text.split('\n')
    formatted_lines = []
    in_list = False

    # Patterns to detect list-like content
    list_indicators = [
        r'^(General|Niche|International|Country-Specific|Additional)\b',  # Section headings
        r'^(Indeed|LinkedIn|Glassdoor|H1BGrader|H1B Visa Jobs|ImmIhelp)\b',  # Website names
        r'^(Network|Check|Stay)\b'  # Tips starting with verbs
    ]

    for line in lines:
        line = line.strip()
        if not line:
            if in_list:
                in_list = False
                formatted_lines.append('')  # Add a line break after a list
            continue

        # Check if the line starts a new section (e.g., "General Job Search Websites")
        if any(re.match(pattern, line, re.IGNORECASE) for pattern in list_indicators):
            if in_list:
                in_list = False
                formatted_lines.append('')  # Add a line break before a new section
            # Add the section as a bold heading
            formatted_lines.append(f"**{line}**")
            in_list = True
            continue

        # If we're in a list, format the line as a bullet point
        if in_list and not line.startswith('-'):
            # Split the line into website/tip and description (e.g., "Indeed (link unavailable): Description")
            if ': ' in line:
                parts = line.split(': ', 1)
                item = parts[0].strip()
                description = parts[1].strip() if len(parts) > 1 else ""
                formatted_lines.append(f"- **{item}**: {description}")
            else:
                formatted_lines.append(f"- {line}")
        else:
            # If not in a list, add the line as a paragraph
            if in_list:
                in_list = False
                formatted_lines.append('')  # Add a line break after a list
            formatted_lines.append(line)

    # Join the lines with proper spacing
    formatted_text = '\n'.join(formatted_lines)
    return formatted_text

if __name__ == '__main__':
    app.run(debug=True)