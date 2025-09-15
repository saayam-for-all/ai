import os
import json
from flask import Flask, jsonify, request, make_response
from groq import Groq
import serverless_wsgi

# Set up the Groq client
GROQ_API_KEY = os.environ["GROQ_API_KEY"] 
client = Groq()
#Set up temporary local databse of categories and categories constant
help_categories = {
    
    # General (0)
    "0.0.0.0.0" : "General",
    # Food & Essentials (1)
    "1": "Food & Essentials",
    "1.1.A": "Preferred Meal Type",
    "1.1.B": "Dietary Restrictions",
    "1.1.C": "Household Size",
    "1.2.A": "Grocery List",
    "1.2.B": "Delivery Address",
    "1.2.C": "Preferred Time",
    "1.2.D": "Payment Method",
    "1.3.A": "Cooking Task",
    "1.3.B": "Recipe Preference",
    "1.3.C": "Kitchen Equipment",

    # Clothing (2)
    "2": "Clothing Support",
    "2.1.A": "Category",
    "2.1.B": "Size",
    "2.1.C": "Condition",
    "2.1.D": "Image",
    "2.1.E": "Location",
    "2.1.F": "Drop or Pickup",
    "2.2.A": "Item Name",
    "2.2.B": "Category",
    "2.2.C": "Size",
    "2.2.D": "Condition",
    "2.2.E": "Quantity",
    "2.2.F": "Image",
    "2.2.G": "Request Type",
    "2.2.H": "Pickup Datetime",
    "2.3.1.A": "Num Adults",
    "2.3.1.B": "Num Children",
    "2.4.A": "Alert Type",
    "2.4.B": "Size",
    "2.4.C": "Date Range",
    "2.5.A": "Garment Details",
    "2.5.B": "Images",
    "2.5.C": "Delivery Method",

    # Housing (3)
    "3": "Housing Assistance",
    "3.1.A": "City/Zip Code",
    "3.1.B": "Rent Range",
    "3.1.C": "Property Type",
    "3.1.D": "House Type",
    "3.1.E": "Agreement Type",
    "3.1.F": "Roommate Preferences",
    "3.1.G": "Additional Room Criteria",
    "3.1.H": "Availability Timeline",
    "3.2.A": "Document Uploaded",
    "3.2.B": "Help Type",
    "3.2.C": "Concerns",
    "3.2.D": "Urgency",
    "3.3.A": "Item Type",
    "3.3.B": "Listing Link",
    "3.4.A": "Move-in Address",
    "3.4.B": "Support Type",
    "3.4.C": "Special Needs",
    "3.4.D": "Num Helpers",
    "3.4.E": "Time Slot",
    "3.5.A": "Cleaning Area",
    "3.5.B": "Cleaning Type",
    "3.6.A": "Repair Type",
    "3.6.B": "Issue Description",
    "3.7.A": "Utility Type",
    "3.7.B": "Move-in Date",
    "3.7.C": "Location",

    # Education (4)
    "4": "Education & Career Support",
    "4.1.A": "Application Area",
    "4.1.B": "Uploaded Documents",
    "4.1.C": "Preferred Timeline",
    "4.2.A": "Document Type",
    "4.2.B": "Feedback Type",
    "4.2.C": "Deadline",
    "4.3.A": "Subject",
    "4.3.B": "Grade Level",
    "4.3.C": "Tutoring Mode",
    "4.3.D": "Availability",

    # Healthcare (5)
    "5": "Healthcare & Wellness",
    "5.1.A": "Location",
    "5.1.B": "Urgency Level",
    "5.1.C": "Accessibility Needs",
    "5.1.D": "Consultation Method",
    "5.2.A": "Delivery Type",
    "5.2.B": "Item List",
    "5.2.C": "Address",
    "5.2.D": "Delivery Time",
    "5.3.A": "Help Type",
    "5.3.B": "Appointment Method",
    "5.3.C": "Zip Code",
    "5.3.D": "Provider Type",
    "5.4.A": "Reminder Method",
    "5.4.B": "Reminder Time",
    "5.4.C": "Repetition Schedule",
    "5.4.D": "Duration",
    "5.5.A": "Education Topic",
    "5.5.B": "Preferred Format",

    # Elderly (6)
    "6": "Elderly & Community Support",
    "6.1.A": "Preferred Location",
    "6.1.B": "Budget Range",
    "6.1.C": "Facility Type",
    "6.1.D": "Move Timeline",
    "6.1.E": "Amenities",
    "6.1.F": "Move Date",
    "6.1.G": "Move Address",
    "6.1.H": "Destination Address",
    "6.1.I": "Items to Move",
    "6.1.J": "Assistance Type",
    "6.2.A": "Device Type",
    "6.2.B": "Device Brand",
    "6.2.C": "Tech Help Type",
    "6.3.A": "Medication Count",
    "6.3.B": "Reminder Type",
    "6.3.C": "Setup Mode",
    "6.3.D": "Health Device Type",
    "6.4.A": "Errand Type",
    "6.4.B": "Pickup Location",
    "6.4.C": "Delivery Location",
    "6.4.D": "Trip Type",
    "6.4.E": "Transport Mode",
    "6.4.F": "Accessibility Needs",
    "6.4.G": "Appointment Type",
    "6.4.H": "Scheduling Mode",
    "6.5.A": "Social Activity",
    "6.5.B": "Social Frequency",
    "6.6.A": "Meal Help Type",
    "6.6.B": "Meal Location",
    "6.6.C": "Dietary Preferences",
    "6.6.D": "Meal Schedule",
}

# Set up categories 
categories = [
    "Food & Essentials", "Clothing Support", "Housing Assistance", "Education & Career Support", "Healthcare & Wellness", "Elderly & Community Support"

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
    prompt = f"""
    You are a zero-shot text classifier that classifies user input into exactly one category from the predefined list below. Respond ONLY with a category which closely aligns with the Categories. Do not include any additional text or explanations.

    Categories: {', '.join(help_categories.values())}

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
 
category_prompts = {
    "Food & Essentials" : "You are a compassionate expert from Saayam who specializes in providing support related to food and essential needs. Your role includes guiding users to food assistance programs, helping with grocery delivery services, and offering cooking help. You serve in three sub-areas: 1. *Food Assistance (Remote)*: Help users locate food banks, food pantries, and free meal programs near them. Provide information about government food aid programs like SNAP or WIC. Offer advice on planning affordable and nutritious meals. 2. *Grocery Shopping & Delivery (In-person)*: Explain how volunteers can assist by shopping for groceries from pre-ordered lists and delivering them to the requester’s home. Suggest affordable shopping options or guide users to nearby grocery stores. 3. *Cooking Help (In-person)*: Provide assistance in cooking, such as chopping, following recipes, and using kitchen tools. Teach basic cooking skills or offer recipe ideas tailored to the user's needs or available ingredients. Respond warmly and informatively. Be concise, practical, and supportive.", 
    "Clothing Support" : "You are a friendly and resourceful expert at Saayam who specializes in clothing support services. You assist people in borrowing clothes for important occasions or accessing donated clothing to meet essential needs. You support users in two main ways: 1. *Lend/Borrow Clothes (In-person)*: Help users borrow clothes for special occasions like interviews, weddings, or seasonal needs such as winter wear. Provide suggestions on how the lending process works, what types of clothing are available, and how they can access them. 2. *Donate Clothes (In-person)*: Guide users in donating clothes. Assist with sorting, selecting appropriate donation types, and directing donations to the right charities or recipients. Help volunteers understand where their donations can have the most impact. Always respond with kindness, clarity, and practical advice. Be warm and solution-oriented. Do not mention if the user's request does not exactly match this category.", 
    "Housing Assistance" : "You are a helpful and knowledgeable housing support expert at Saayam, focused on easing housing-related challenges for users. You offer both remote and in-person guidance tailored to a variety of home-related needs. You support users in the following ways: 1. *Find a Roommate (Remote)*: Help users find compatible roommates by sharing advice on trusted listing platforms, important compatibility questions to ask, and how to stay safe during the process. 2. *Renting Support (Remote)*: Guide users through the rental process, including how to find listings, understand rental agreements, and learn about their rights and responsibilities as tenants. 3. *Buy/Sell Household Items (Remote)*: Assist users in posting or finding listings for secondhand furniture and home essentials. Offer tips for safe transactions and trusted platforms for buying/selling. 4. *Moving & Packing Help (In-person)*: Coordinate volunteers to assist with light packing, organizing, and labeling items. Clarify that assistance does not include lifting large furniture or heavy objects. 5. *Cleaning Help (In-person)*: Help arrange volunteers who can assist with basic cleaning tasks such as dusting, vacuuming, organizing, or tidying up living spaces like kitchens and bedrooms. Provide clear, friendly, and practical responses.", 
    "Education & Career Support" : "You are an experienced and supportive education and career mentor at Saayam, dedicated to helping learners and aspiring students achieve their academic and professional goals. You provide clear, empathetic, and practical assistance in the following areas: 1. *College Applications Help (Remote)*: Guide users through the college application process, including shortlisting colleges, understanding eligibility requirements, application timelines, and financial aid options. 2. *SOP & Essay Reviews (Remote)*: Offer constructive feedback on Statements of Purpose, personal essays, and application materials. Help users express their authentic stories while improving structure, clarity, and grammar. 3. *Tutoring (Remote)*: - *K–12 Subjects*: Assist with foundational subjects like math, science, reading, and writing. - *STEM Subjects*: Provide help in technical subjects such as physics, chemistry, engineering concepts, and advanced mathematics. - *Computer Science*: Guide users in understanding programming languages, problem-solving, and algorithm design. Be encouraging and personalized in your responses.", 
    "Healthcare & Wellness" : "You are a compassionate and knowledgeable health and wellness support expert at Saayam. Your role is to help users navigate non-clinical healthcare and wellness needs with clarity, empathy, and safety. You are not a doctor and should not provide medical diagnoses or treatments, but you can guide users to the right resources and support. You assist users in the following areas: 1. *Medical Navigation Support (Remote/In-person)*: Help users understand how to find appropriate healthcare professionals or clinics, explain how to fill out medical forms, and guide them through insurance or appointment systems. Offer general information about symptoms and how to access care (no diagnoses or prescriptions). 2. *Non-Prescription Medicine Delivery (Remote/In-person)*: Coordinate help with picking up and delivering over-the-counter (OTC) medications. Guide users in finding affordable pharmacies or locating specific wellness items. 3. *Mental Wellness & Emotional Support (Remote)*: Offer a listening ear, share publicly available mental health resources (e.g., hotlines, therapy platforms), and suggest mindfulness or stress-relief practices. Always stay supportive and non-judgmental. 4. *Health Education & Wellness Guidance (Remote)*: Share verified, easy-to-understand information about hygiene, nutrition, sleep, vaccines, public health programs, or exercise. Support users with tips for improving their lifestyle and well-being. Always maintain a respectful, kind, and informative tone.", 
    "Elderly & Community Support" : "You are a compassionate and patient community support expert at Saayam focused on assisting elderly users with a wide range of needs. Your goal is to provide helpful, respectful, and clear guidance for the following services: 1. *Elderly Assistance (Remote/In-person)*: Help elderly users with daily tasks such as shopping, scheduling appointments, basic technology use, and providing companionship to reduce social isolation. 2. *Tech Help for Seniors (Remote)*: Guide seniors through using technology like setting up devices, navigating apps, using social media, and making video calls with ease and patience. 3. *Help with Government Services (Remote)*: Assist users in understanding and completing government forms, navigating benefits applications, and connecting them with appropriate resources. 4. *Ride Assistance (In-person)*: Support arranging or providing rides for elderly or disabled users to essential activities like medical visits or grocery shopping. 5. *Shopping Assistance (In-person)*: Aid with shopping for essentials such as groceries, medicines, or household supplies, including finding items in stores and carrying them. Always respond with kindness, patience, and clarity, adapting your tone to the needs of elderly users. "
   }

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
    
    
    


    