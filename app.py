# app.py

import os
import json
import traceback
from typing import Dict, List, Optional

from flask import Flask, jsonify, request
from groq import Groq
import serverless_wsgi
from dotenv import load_dotenv, find_dotenv
try:
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

# ---------- Environment & App setup ----------
# Load .env from current directory or parent directories so a project-level .env is picked up.
load_dotenv(find_dotenv(), override=False)

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = True

# Simple CORS for dev; tighten for prod
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# ---------- Groq client ----------
# Read key from environment (set GROQ_API_KEY in shell, Lambda env, or .env)
print("GROQ key present at startup:", bool(os.getenv("GROQ_API_KEY")))
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL_NAME = "llama-3.1-8b-instant"
DB_SCHEMA = os.getenv("DB_SCHEMA", "virginia_dev_saayam_rdbms")

# ---------- Categories / Prompts ----------
categories: List[str] = [
    "Banking", "Books", "Clothes", "College Admissions", "Cooking",
    "Elementary Education", "Middle School Education", "High School Education", "University Education",
    "Employment", "Finance", "Food", "Gardening", "Homelessness", "Housing", "Jobs", "Investing",
    "Matrimonial", "Brain Medical", "Depression Medical", "Eye Medical", "Hand Medical",
    "Head Medical", "Leg Medical", "Rental", "School", "Shopping",
    "Baseball Sports", "Basketball Sports", "Cricket Sports", "Handball Sports",
    "Jogging Sports", "Hockey Sports", "Running Sports", "Tennis Sports",
    "Stocks", "Travel", "Tourism"
]

category_prompts = {
    "Banking": "You are a meticulous and trustworthy banking advisor at Saayam, known for simplifying financial jargon and helping people navigate loans, accounts, and credit decisions with clarity and confidence. Answer this question with care and precision:",
    "Books": "You are a well-read literary guide at Saayam who connects people to the perfect book. Your reviews are thoughtful, poetic, and rooted in a love for diverse genres. Share your perspective:",
    "Clothes": "You are a fashion stylist at Saayam, with a keen eye for trends and a passion for helping people express themselves through clothing. Offer friendly and practical advice:",
    "College Admissions": "You are a dedicated admissions mentor at Saayam, guiding students with empathy and clarity through every step of their college application journey. Provide supportive and actionable guidance:",
    "Cooking": "You are a cheerful culinary expert at Saayam, known for sharing home-style recipes and clever kitchen hacks. Help this user with friendly and flavorful advice:",
    "Elementary Education": "You are a nurturing early education specialist at Saayam who believes learning should be playful and personal. Answer with warmth and encouragement:",
    "Middle School Education": "You are a supportive educator at Saayam who specializes in helping middle schoolers grow in confidence and curiosity. Respond in an engaging, friendly tone:",
    "High School Education": "You are a passionate high school mentor from Saayam who understands the pressures of teenage years and helps students make smart academic choices. Provide thoughtful guidance:",
    "University Education": "You are an academic advisor at Saayam, experienced in helping students navigate university life, from choosing majors to managing workloads. Offer strategic and student-centered advice:",
    "Employment": "You are a career counselor at Saayam who’s helped hundreds land their dream roles. Practical, encouraging, and honest—help this user move forward:",
    "Finance": "You are a seasoned financial guide at Saayam, specializing in helping individuals manage money wisely with realistic and simple plans. Answer with practical wisdom:",
    "Food": "You are a food storyteller at Saayam, someone who explores cuisines and shares tips, flavors, and kitchen tricks with joy. Give a flavorful and curious answer:",
    "Gardening": "You are a soil-loving, nature-rooted gardening expert from Saayam, known for turning even the smallest balcony into a blooming haven. Share plant wisdom with enthusiasm and clarity:",
    "Homelessness": "You are a frontline outreach coordinator at Saayam, deeply compassionate and experienced in housing rights and crisis support. Answer with empathy and resourceful guidance:",
    "Housing": "You are a housing advisor from Saayam, known for simplifying leases, tenant rights, and home-buying decisions for all. Provide clear and grounded advice:",
    "Jobs": "You are a job placement strategist at Saayam, skilled at matching talents with opportunities and calming pre-interview jitters. Offer focused, motivational advice:",
    "Investing": "You are a level-headed investment expert at Saayam who makes markets feel less scary and more strategic. Break things down simply and wisely:",
    "Matrimonial": "You are a culturally aware relationship counselor at Saayam who understands traditions and modern love. Offer guidance with care and non-judgmental tone:",
    "Brain Medical": "You are a compassionate neurologist at Saayam who explains complex brain issues in a way anyone can understand. Speak with medical authority and warmth:",
    "Depression Medical": "You are a mental health counselor at Saayam, deeply empathetic and gentle. Your answers reduce stigma and offer realistic hope. Respond with care:",
    "Eye Medical": "You are a sharp-eyed ophthalmologist at Saayam who helps users understand eye care with clarity and confidence. Provide trustworthy advice:",
    "Hand Medical": "You are a hand specialist from Saayam, focused on functionality and healing. Speak with medical precision and human warmth:",
    "Head Medical": "You are a head and neck care expert from Saayam who listens carefully and explains clearly. Offer informative and calming answers:",
    "Leg Medical": "You are a physiotherapist at Saayam who specializes in leg and joint care, with a focus on mobility and recovery. Share precise and motivating guidance:",
    "Rental": "You are a housing rental advisor from Saayam, great at demystifying paperwork and ensuring tenants feel secure. Give simple, actionable advice:",
    "School": "You are a school guidance lead at Saayam who supports students and parents through school choices, transitions, and concerns. Respond with clarity and care:",
    "Shopping": "You are a savvy Saayam shopper and product tester who loves helping others make the best purchase decisions. Recommend with flair and honesty:",
    "Baseball Sports": "You are a strategic baseball coach from Saayam, loved for explaining the game in easy steps and helping new players shine. Share friendly, pro-level insight:",
    "Basketball Sports": "You are a basketball mentor at Saayam with a knack for motivating players and breaking down court tactics. Respond with game-savvy energy:",
    "Cricket Sports": "You are a seasoned cricket advisor from Saayam, trusted for match insights and tips on technique. Share advice like you're talking to a teammate:",
    "Handball Sports": "You are a skilled handball trainer at Saayam, great at building confidence and coordination. Offer action-oriented, clear advice:",
    "Jogging Sports": "You are a fitness motivator at Saayam, helping beginners fall in love with jogging. Keep things upbeat, simple, and personalized:",
    "Hockey Sports": "You are a hockey tactics coach at Saayam, known for sharp reads and supportive guidance. Share tips with team spirit and clarity:",
    "Running Sports": "You are a marathon mentor at Saayam who helps people run smarter, not just harder. Be encouraging, structured, and personal:",
    "Tennis Sports": "You are a calm and skilled tennis pro at Saayam, blending technique with mental game advice. Respond like you're coaching 1-on-1:",
    "Stocks": "You are an investment advisor at Saayam who helps even first-time investors feel confident. Break down trends with clarity and calm:",
    "Travel": "You are an enthusiastic travel planner from Saayam, with a knack for hidden gems and smart hacks. Answer with excitement and practical tips:",
    "Tourism": "You are a friendly tourism expert at Saayam, bringing local culture and insider tips to life. Be vivid, informative, and welcoming:"
}

# ---------- Helpers ----------
def _parse_categories(raw: str) -> List[str]:
    # Split on commas or newlines, trim, filter to known categories
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p in categories][:3]


def _first_non_empty(data: dict, keys: List[str]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
    return ""


def _normalize_history(history: Optional[list]) -> List[Dict[str, str]]:
    if not isinstance(history, list):
        return []

    normalized: List[Dict[str, str]] = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if not content:
            continue

        if role in {"ai", "bot", "model"}:
            role = "assistant"
        elif role not in {"user", "assistant", "system"}:
            continue

        normalized.append({"role": role, "content": content})
    return normalized


def _extract_request_payload() -> dict:
    """
    Accept both direct JSON payloads and nested proxy-like payloads:
      { ...fields... }
      { "body": { ...fields... } }
      { "body": "{\"...\": \"...\"}" }
    """
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return {}

    nested = data.get("body")
    if isinstance(nested, dict):
        merged = dict(data)
        merged.pop("body", None)
        merged.update(nested)
        return merged

    if isinstance(nested, str):
        try:
            parsed = json.loads(nested)
            if isinstance(parsed, dict):
                merged = dict(data)
                merged.pop("body", None)
                merged.update(parsed)
                return merged
        except json.JSONDecodeError:
            pass

    return data


def _get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed")

    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing DB env vars: {', '.join(missing)}")

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def _format_additional_info_for_prompt(additional_info: List[Dict[str, object]]) -> str:
    lines: List[str] = []
    for entry in additional_info:
        question = entry.get("question")
        answers = entry.get("answers", [])
        if not question or not isinstance(answers, list) or not answers:
            continue
        rendered = ", ".join(str(ans) for ans in answers if ans not in (None, ""))
        if rendered:
            lines.append(f"- {question}: {rendered}")
    return "\n".join(lines)


def get_request_full_details(user_id: str, req_id: str) -> Dict[str, object]:
    query = f"""
        SELECT
            r.req_id,
            r.req_user_id,
            r.req_cat_id,
            r.req_subj,
            r.req_desc,
            r.req_loc,
            m.field_name_key AS question,
            m.field_type,
            l.item_value AS list_answer,
            rai.field_value
        FROM {DB_SCHEMA}.request r
        LEFT JOIN {DB_SCHEMA}.req_add_info rai
            ON r.req_id = rai.req_id
        LEFT JOIN {DB_SCHEMA}.req_add_info_metadata m
            ON rai.field_id = m.field_id
        LEFT JOIN {DB_SCHEMA}.list_item_metadata l
            ON rai.item_id = l.item_id
        WHERE r.req_user_id = %s
          AND r.req_id = %s
        ORDER BY rai.field_id;
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(query, (user_id, req_id))
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        if not rows:
            return {"error": f"No data found for user_id={user_id}, req_id={req_id}"}

        first = rows[0]
        col = {name: idx for idx, name in enumerate(cols)}
        result: Dict[str, object] = {
            "req_id": first[col["req_id"]],
            "req_user_id": first[col["req_user_id"]],
            "req_cat_id": first[col["req_cat_id"]],
            "req_subj": first[col["req_subj"]],
            "req_desc": first[col["req_desc"]],
            "req_loc": first[col["req_loc"]],
            "additional_info": [],
        }

        grouped: Dict[str, Dict[str, object]] = {}
        for row in rows:
            question = row[col["question"]]
            if not question:
                continue
            entry = grouped.setdefault(
                str(question),
                {
                    "question": str(question),
                    "field_type": row[col["field_type"]],
                    "answers": [],
                },
            )
            list_answer = row[col["list_answer"]]
            field_value = row[col["field_value"]]
            answer = list_answer if list_answer not in (None, "") else field_value
            if answer not in (None, "") and answer not in entry["answers"]:
                entry["answers"].append(str(answer))

        result["additional_info"] = list(grouped.values())
        return result
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()

# ---------- Core LLM calls ----------
def predict_categories(subject: str, description: str) -> List[str]:
    prompt = f"""
You are a zero-shot text classifier that classifies user input into exactly three categories from the predefined list below.
Respond ONLY with a comma-separated list of categories. Do not include any additional text or explanations.

Categories: {", ".join(categories)}

User Input:
Subject: {subject}
Description: {description}

Output (comma-separated categories):
""".strip()

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        top_p=0.3,
    )
    raw_output = resp.choices[0].message.content.strip()
    result = _parse_categories(raw_output)

    # Fallback: if model returns nothing valid, return first three general categories
    if not result:
        result = ["Finance", "Housing", "Jobs"][:3]
    return result


def chat_with_llama(
    category: str,
    subject: str,
    description: str,
    location: str = "",
    gender: str = "",
    age: str = "",
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    role_prompt = category_prompts.get(
        category,
        "You are a helpful expert from Saayam. Answer the question clearly and kindly:",
    )

    base_prompt = (
        f"{role_prompt}\n\n"
        f"Subject: {subject}\n"
        f"Question: {description}\n"
        f"Location: {location}\n"
        f"Gender: {gender}\n"
        f"Age: {age}"
    )
    messages: List[Dict[str, str]] = [{"role": "user", "content": base_prompt}]
    if conversation_history:
        messages = [
            {"role": "system", "content": role_prompt},
            *conversation_history,
            {"role": "user", "content": f"Subject: {subject}\nQuestion: {description}"},
        ]

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "API is running"})

@app.route("/predict_categories", methods=["POST", "OPTIONS"])
def predict_categories_api():
    try:
        if request.method == "OPTIONS":
            return ("", 200)
        data = _extract_request_payload()
        subject = (data.get("subject") or "").strip()
        description = (data.get("description") or "").strip()
        if not subject or not description:
            return jsonify({"error": "Subject and description are required"}), 400

        cats = predict_categories(subject, description)
        return jsonify(cats), 200
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "internal_error"}), 500

@app.route("/generate_answer", methods=["POST", "OPTIONS"])
def generate_answer_api():
    try:
        if request.method == "OPTIONS":
            return ("", 200)
        data = _extract_request_payload()
        answer, error_message, status_code = _generate_answer_from_payload(data)
        if error_message:
            return jsonify({"error": error_message}), status_code
        # Backward compatibility for existing consumers expecting a JSON string.
        return jsonify(answer), 200
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "internal_error"}), 500


def _generate_answer_from_payload(data: dict):
    try:
        category = _first_non_empty(data, ["category", "category_id"])
        subject = _first_non_empty(data, ["subject"])
        question = _first_non_empty(data, ["description", "question"])
        location = _first_non_empty(data, ["location"])
        gender = _first_non_empty(data, ["gender"])
        age = _first_non_empty(data, ["age"])
        lookup_error = ""

        # Wiki-aligned fallback: if user_id + req_id are provided, load request context from DB.
        user_id = _first_non_empty(data, ["user_id", "req_user_id"])
        req_id = _first_non_empty(data, ["req_id", "request_id", "id"])
        if user_id and req_id and (not category or not subject or not question):
            request_details = get_request_full_details(user_id, req_id)
            if "error" in request_details:
                lookup_error = str(request_details["error"])
            else:
                category = category or str(request_details.get("req_cat_id") or "")
                subject = subject or str(request_details.get("req_subj") or "")
                location = location or str(request_details.get("req_loc") or "")
                if not question:
                    base_desc = str(request_details.get("req_desc") or "")
                    additional_info = request_details.get("additional_info") or []
                    context = _format_additional_info_for_prompt(additional_info)
                    question = (
                        f"{base_desc}\n\nAdditional details:\n{context}"
                        if context
                        else base_desc
                    )

        conversation_history = _normalize_history(
            data.get("conversation_history", data.get("chat_history"))
        )
        if not category or not subject or not question:
            message = "category/category_id, subject, and description/question are required"
            if lookup_error:
                message = f"{message}. DB lookup error: {lookup_error}"
            return None, message, 400

        answer = chat_with_llama(
            category,
            subject,
            question,
            location=location,
            gender=gender,
            age=age,
            conversation_history=conversation_history,
        )
        return answer, None, 200
    except Exception:
        traceback.print_exc()
        return None, "internal_error", 500


@app.route("/generate_answer_api", methods=["POST", "OPTIONS"])
def generate_followup_answer_api():
    # UI expects payload shape: { body: { answer: "<text>" } }.
    # Keep top-level `answer` as a compatibility convenience.
    try:
        if request.method == "OPTIONS":
            return ("", 200)
        data = _extract_request_payload()
        answer, error_message, status_code = _generate_answer_from_payload(data)
        if error_message:
            return jsonify({"error": error_message}), status_code
        return jsonify({"answer": answer, "body": {"answer": answer}}), 200
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "internal_error"}), 500


@app.route("/v1/genai/predict_categories", methods=["POST", "OPTIONS"])
def v1_predict_categories_api():
    return predict_categories_api()


@app.route("/v1/genai/generate_answer", methods=["POST", "OPTIONS"])
def v1_generate_answer_api():
    return generate_answer_api()


@app.route("/v1/genai/generate_answer_api", methods=["POST", "OPTIONS"])
def v1_generate_followup_answer_api():
    return generate_followup_answer_api()

# ---------- Lambda entry ----------
def lambda_handler(event, context):
    # Normalize a path prefix if using API Gateway stage mapping in AWS
    if isinstance(event, dict) and "path" in event and isinstance(event["path"], str):
        event["path"] = event["path"].replace("/dev/genai/v0.0.1", "")
    return serverless_wsgi.handle_request(app, event, context)

# ---------- Local dev runner ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
