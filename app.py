from flask import Flask, render_template_string, jsonify, request
from groq import Groq
import os
import serverless_wsgi
from transformers import pipeline

# Set up the Groq client
os.environ["GROQ_API_KEY"] = "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"
client = Groq()

# Set up the zero-shot classification model
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
classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")


def predict_categories(subject, description):
    prompt = f"{subject}. {description}"
    result = classifier(prompt, categories)
    return result['labels'][:3]  # Return top 2-3 predicted categories


def chat_with_llama(category, description):
    full_prompt = f"Category: {category}\nQuestion: {description}"
    response = client.chat.completions.create(
        model="llama-3.2-1b-preview",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": full_prompt}
        ]
    )
    return response.choices[0].message.content.strip()


app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Saayam AI Assistant</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f9f9f9;
        }
        .container {
            max-width: 600px;
            margin: auto;
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        }
        h1 {
            text-align: center;
            color: #4CAF50;
        }
        label {
            font-weight: bold;
            margin-top: 10px;
            display: block;
        }
        textarea, select, input, button {
            margin-top: 10px;
            width: 100%;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 5px;
        }
        button {
            background-color: #4CAF50;
            color: white;
            border: none;
            cursor: pointer;
        }
        button:hover {
            background-color: #45a049;
        }
        .predicted-categories {
            margin-top: 10px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .category-option {
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 5px;
            background-color: #e7f5e7;
            cursor: pointer;
        }
        .category-option.selected {
            background-color: #4CAF50;
            color: white;
            border: 1px solid #4CAF50;
        }
        .loading-message {
            text-align: center;
            margin-top: 10px;
            font-style: italic;
            color: #888;
        }
        .response {
            margin-top: 20px;
            display: none;
        }
        .response p {
            background: #e7f5e7;
            padding: 10px;
            border: 1px solid #4CAF50;
            border-radius: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Create a Request</h1>
        <form id="qa-form">
            <label for="subject">Subject:</label>
            <input id="subject" name="subject" type="text" placeholder="Enter the subject" required />

            <label for="category">Category (Optional):</label>
            <select id="category" name="category">
                <option value="" disabled selected>Select a category</option>
            </select>

            <label for="description">Description:</label>
            <textarea id="description" name="description" rows="4" placeholder="Enter your question here..." required></textarea>
            
            <!-- Placeholder for predicted categories or loading message -->
            <div id="category-prediction-area"></div>

            <button type="button" onclick="askQuestion()">Ask</button>
        </form>
        <div class="response" id="response-container">
            <h3>Response:</h3>
            <p id="response-text"></p>
        </div>
    </div>
    <script>
        const categories = {{ categories|safe }};
        const categoryDropdown = document.getElementById("category");
        const predictionArea = document.getElementById("category-prediction-area");

        // Populate category dropdown
        categories.forEach(cat => {
            const option = document.createElement("option");
            option.value = cat;
            option.textContent = cat;
            categoryDropdown.appendChild(option);
        });

        let selectedCategory = "";

        function askQuestion() {
            const subject = document.getElementById("subject").value;
            const category = document.getElementById("category").value || selectedCategory;
            const description = document.getElementById("description").value;

            if (!subject || !description) {
                alert("Please fill out all required fields.");
                return;
            }

            if (!category) {
                // Show loading message
                predictionArea.innerHTML = '<p class="loading-message">Generating relevant categories for you to choose from...</p>';

                // Predict categories if not selected
                fetch('/predict_categories', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ subject, description })
                })
                .then(res => res.json())
                .then(data => {
                    // Remove loading message and show predicted categories
                    predictionArea.innerHTML = "";
                    const predictedContainer = document.createElement("div");
                    predictedContainer.className = "predicted-categories";
                    data.predicted_categories.forEach(cat => {
                        const div = document.createElement("div");
                        div.textContent = cat;
                        div.className = "category-option";
                        div.onclick = () => selectCategory(div, cat);
                        predictedContainer.appendChild(div);
                    });
                    predictionArea.appendChild(predictedContainer);
                })
                .catch(err => console.error(err));
                return;
            }

            // Generate response
            fetch('/generate_answer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ category, question: description })
            })
            .then(res => res.json())
            .then(data => {
                const responseContainer = document.getElementById("response-container");
                const responseText = document.getElementById("response-text");
                responseText.textContent = data.answer || data.error;
                responseContainer.style.display = 'block';
            })
            .catch(err => console.error(err));
        }

        function selectCategory(element, category) {
            document.querySelectorAll(".category-option").forEach(el => el.classList.remove("selected"));
            element.classList.add("selected");
            selectedCategory = category;
        }
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def home():
    return render_template_string(HTML_TEMPLATE, categories=categories)


@app.route('/predict_categories', methods=['POST'])
def predict_categories_api():
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")

    if not subject or not description:
        return jsonify({"error": "Subject and description are required"}), 400

    try:
        predicted_categories = predict_categories(subject, description)
        return jsonify({"predicted_categories": predicted_categories})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    data = request.get_json()
    category = data.get("category")
    question = data.get("question")

    if not question or not category:
        return jsonify({"error": "Question and category are required"}), 400

    try:
        answer = chat_with_llama(category, question)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
