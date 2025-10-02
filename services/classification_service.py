from utils.categories_with_description import TAXONOMY
from utils.client import client

#Function to predict categories
def predict_categories(subject, description):
    categories_with_desc = "\n".join([f"{k}: {v}" for k, v in TAXONOMY.items()]) # Move it outside the function, so that this is executed only once and not everytime
    # print(categories_with_desc)
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