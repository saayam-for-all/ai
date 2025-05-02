import os
import json
from flask import Flask, jsonify, request, make_response
from groq import Groq
import serverless_wsgi

# Set up the Groq client
os.environ["GROQ_API_KEY"] = "  "
client = Groq()

# Set up categories 
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

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"message": "API is running"})

#Predict categories based on subject and description
@app.route('/predict_categories', methods=['POST'])
def predict_categories_api():
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")

    if not subject or not description:
        return jsonify({"error": "Subject and description are required"}), 400

    try:
        predicted_categories = predict_categories(subject, description)
        response = jsonify(predicted_categories)
        #print("Respose body:", response)            
        # Adding headers. Pl modify * to our release website address in production
        response.headers['Access-Control-Allow-Origin'] = '*'
        
        #return jsonify(predicted_categories)  # Return only categories
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500

#Generate an answer based on category, subject, and description
@app.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    data = request.get_json()
    category = data.get("category")
    subject = data.get("subject")
    question = data.get("description")  

    if not category or not subject or not question:
        return jsonify({"error": "Category, subject, and description are required"}), 400

    try:
        answer = chat_with_llama(category, subject, question)
        response = jsonify(answer)
        #print("Respose body:", response)            
        # Adding headers. Pl modify * to our release website address in production
        response.headers['Access-Control-Allow-Origin'] = '*'
        
        return response
        #return jsonify(answer)  
    except Exception as e:
        return jsonify({"error": str(e)}), 500

#Function to predict categories
def predict_categories(subject, description):
    prompt = f"""
    You are a zero-shot text classifier that classifies user input into exactly three categories from the predefined list below. Respond ONLY with a comma-separated list of categories. Do not include any additional text or explanations.

    Categories: {", ".join(categories)}

    User Input:
    Subject: {subject}
    Description: {description}

    Output (comma-separated categories):
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        top_p=0.3
    )

    # Extract and parse the output
    raw_output = response.choices[0].message.content.strip()

    # Split by commas and clean up
    parts = [category.strip() for category in raw_output.split(",")]
    valid_categories = [category for category in parts if category in categories]
    return valid_categories[:3]  
 
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

#Function to generate an answer based on category, subject, and description
def chat_with_llama(category, subject, description):
    # Define the prompt dictionary globally or import it if external
    role_prompt = category_prompts.get(
        category,
        "You are a helpful expert from Saayam. Answer the question clearly and kindly:"  # fallback/default
    )

    # Compose full prompt
    full_prompt = f"{role_prompt}\n\nSubject: {subject}\nQuestion: {description}"

    # Make call to Groq API
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": full_prompt}],
        temperature=0.7
    )

    return response.choices[0].message.content.strip()


def lambda_handler(event, context):   

    # Extract path to determine which API is calling
    #path1 = event.get('resource', event.get('path', ''))
    #print("Received event path:", path1)
    #body = json.loads(event.get('body', '{}'))
    #print("Received event body:", body)

    if "path" in event:
        event["path"] = event["path"].replace("/dev/genai/v0.0.1", "")

    return serverless_wsgi.handle_request(app, event, context)
