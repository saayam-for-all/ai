from services.classification_service import predict_categories
from utils.prompts import category_prompts
from utils.client import client

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