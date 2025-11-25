from flask import Flask, render_template, request, jsonify
from transformers import pipeline
from meta_ai_api import MetaAI
import google.generativeai as genai  # Gemini API
from openai import OpenAI  # OpenAI API
from groq import Groq  # Grok API
from dotenv import load_dotenv
import os
import re
import argparse
import time
import tiktoken
import logging
import transformers

# Suppress transformers logging to reduce clutter
transformers.logging.set_verbosity_error()

# Load environment variables from .env
load_dotenv()

# Set up logging to a file for metrics
logging.basicConfig(
    filename='model_metrics.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

# Ensure Flask's logger outputs to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addHandler(console_handler)

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Run Saayam AI Assistant with a specific AI model.")
parser.add_argument(
    "--model",
    type=str,
    choices=["meta_ai", "gemini", "openai", "grok"],
    default="meta_ai",
    help="Choose the AI model to use: meta_ai, gemini, openai, or grok"
)
args = parser.parse_args()
selected_model = args.model

# Default temperature for models that support it
DEFAULT_TEMPERATURE = 0.7

# Initialize the chosen AI client
if selected_model == "meta_ai":
    ai_client = MetaAI()
elif selected_model == "gemini":
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=gemini_api_key)
    ai_client = genai.GenerativeModel('gemini-1.5-flash')
elif selected_model == "openai":
    ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
elif selected_model == "grok":
    groq_api_key = os.getenv("GROQ_API_KEY")
    ai_client = Groq(api_key=groq_api_key)

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

# Initialize tokenizer for token counting (for OpenAI models)
openai_tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")

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

    # Create a prompt with formatting instructions
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

    # Count input tokens (approximation for non-OpenAI models)
    input_tokens = len(openai_tokenizer.encode(prompt)) if selected_model == "openai" else len(prompt.split())

    # Measure latency and generate response
    try:
        start_time = time.time()
        first_token_time = None
        raw_answer = None

        if selected_model == "meta_ai":
            response = ai_client.prompt(prompt)
            raw_answer = response['message'].strip()
            first_token_time = time.time()
        elif selected_model == "gemini":
            response = ai_client.generate_content(prompt, generation_config={"temperature": DEFAULT_TEMPERATURE})
            raw_answer = response.text.strip()
            first_token_time = time.time()
        elif selected_model == "openai":
            response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=DEFAULT_TEMPERATURE
            )
            raw_answer = response.choices[0].message.content.strip()
            first_token_time = time.time()
        elif selected_model == "grok":
            response = ai_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=DEFAULT_TEMPERATURE
            )
            raw_answer = response.choices[0].message.content.strip()
            first_token_time = time.time()

        end_time = time.time()

        # Calculate latency
        ttft = first_token_time - start_time
        ttlt = end_time - start_time

        # Format the response
        formatted_answer = format_response(raw_answer)

        # Count output tokens
        output_tokens = len(openai_tokenizer.encode(raw_answer)) if selected_model == "openai" else len(raw_answer.split())

        # Calculate speed (tokens per second)
        speed = output_tokens / ttlt if ttlt > 0 else 0

        # Log metrics
        metrics = {
            "model": selected_model,
            "temperature": DEFAULT_TEMPERATURE if selected_model in ["gemini", "openai", "grok"] else "N/A",
            "ttft_seconds": round(ttft, 3),
            "ttlt_seconds": round(ttlt, 3),
            "speed_tokens_per_second": round(speed, 2),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
        logging.info(f"Metrics: {metrics}")

        # Return the answer and metrics
        return jsonify({
            "answer": formatted_answer,
            "metrics": metrics
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def format_response(text):
    lines = text.split('\n')
    formatted_lines = []
    in_list = False

    list_indicators = [
        r'^(General|Niche|International|Country-Specific|Additional)\b',
        r'^(Indeed|LinkedIn|Glassdoor|H1BGrader|H1B Visa Jobs|ImmIhelp)\b',
        r'^(Network|Check|Stay)\b'
    ]

    for line in lines:
        line = line.strip()
        if not line:
            if in_list:
                in_list = False
                formatted_lines.append('')
            continue

        if any(re.match(pattern, line, re.IGNORECASE) for pattern in list_indicators):
            if in_list:
                in_list = False
                formatted_lines.append('')
            formatted_lines.append(f"**{line}**")
            in_list = True
            continue

        if in_list and not line.startswith('-'):
            if ': ' in line:
                parts = line.split(': ', 1)
                item = parts[0].strip()
                description = parts[1].strip() if len(parts) > 1 else ""
                formatted_lines.append(f"- **{item}**: {description}")
            else:
                formatted_lines.append(f"- {line}")
        else:
            if in_list:
                in_list = False
                formatted_lines.append('')
            formatted_lines.append(line)

    formatted_text = '\n'.join(formatted_lines)
    return formatted_text


if __name__ == '__main__':
    print(f"Starting Saayam AI Assistant with model: {selected_model}")
    app.run(debug=True, host='127.0.0.1', port=5000)
