import os
import json
from flask import Flask, jsonify, request, make_response
from groq import Groq
import serverless_wsgi

from prompts import category_prompts
from categories import help_categories
from categories_with_description import TAXONOMY

# Set up the Groq client
GROQ_API_KEY = os.environ["GROQ_API_KEY"] 
client = Groq()
#Set up temporary local databse of categories and categories constant


# Set up categories 
# categories = [
#     "Food & Essentials", "Clothing Support", "Housing Assistance", "Education & Career Support", "Healthcare & Wellness", "Elderly & Community Support"

# ]

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
    
    # if description is 'geneal'.lower():
    #     predict_categories(subject=subject, description= description)

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

#Generate an answer based on category constant, subject, description, location and gender
@app.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    data = request.get_json()
    category_const = data.get("category_const")
    subject = data.get("subject")
    question = data.get("description")
    location = data.get("location")
    gender = data.get("gender")
    print(gender)

    if not category_const or not subject or not question or not location:
        return jsonify({"error": "Category_const, subject, description and location are required"}), 400

    try:
        category = help_categories[category_const]
        answer = chat_with_llama(category, subject, question, location, gender)
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
    categories_with_desc = "\n".join([f"{k}: {v}" for k, v in TAXONOMY.items()]) # Move it outside the function, so that this is executed only once and not everytime
    print(categories_with_desc)
    prompt = f"""
    You are a zero-shot text classifier that classifies user input into exactly one category from the predefined list of categories along with their description below. Respond ONLY with a category from the given list of categories whose meaning closely aligns with the category's description in the list. Do not include any additional text or explanations.

    Categories: {categories_with_desc}

    User Input:
    Subject: {subject}
    Description: {description}

    Output (category):
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        top_p=0.3
    )

    # Extract and parse the output
    raw_output = response.choices[0].message.content.strip()
    print(raw_output)
    return raw_output.strip()

    # Split by commas and clean up
    # parts = [category.strip() for category in raw_output.split(",")]
    # valid_categories = [category for category in parts if category in categories]
    # return valid_categories[:3]  
 


#Function to generate an answer based on category, subject, and description
def chat_with_llama(category, subject, description, location, gender):
    # Define the prompt dictionary globally or import it if external
    
    print(f'Initial Category: {category}')
    #Predict Category ONLY when the user inputs General as category.
    if category == 'General':  #GENERAL CATEGORY
        category = predict_categories(subject=subject, description=description)
    print('updated category: ', category)
    role_prompt = category_prompts.get(
        category,
        "I am a helpful expert at Saayam and I am glad to assist you today. Do not mention if the user's request does not exactly match this category. Always provide the most helpful answer possible for the user's request clearly and kindly:"  # fallback/default
    )

    # Compose full prompt
    instruction = "Do not mention if the user's request does not exactly match this category or details about your expertise."
    full_prompt = f"{role_prompt}\n{instruction}You must provide a clear and actionable solution based on the user input. Do not ask follow-up questions unless the user request is unclear.\n\nSubject: {subject}\nQuestion: {description} \nLocation: {location}\nGender:{gender}"

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



if __name__ == "__main__":
    app.run(debug=True)
    
    
    


    