# from utils.categories_with_description import TAXONOMY
# from utils.client import client, _use_groq, _gemini_client

# class GroqClassificationService:
#     def __init__(self, model="llama-3.1-8b-instant", temperature=0.8, top_p=0.3):
#         self.model = model
#         self.temperature = temperature
#         self.top_p = top_p
#         self.categories_with_desc = "\n".join(
#             [f"{k}: {v}" for k, v in TAXONOMY.items()]
#         )
#         self.gemini_model = "gemini-2.0-flash" 

#     def _predict_with_gemini(self, prompt: str) -> str:
#         if not _gemini_client:
#             print("CRITICAL ERROR: Gemini fallback requested but _gemini_client is None.")
#             raise ValueError("Gemini client not initialized")
            
#         response = _gemini_client.models.generate_content(
#             model=self.gemini_model,
#             contents=prompt
#         )
#         return response.text.strip()

#     def predict_categories(self, subject: str, description: str) -> str:
#         prompt = f"""
# You are a zero-shot classifier. Choose EXACTLY ONE category.

# Categories:
# {self.categories_with_desc}

# Subject: {subject}
# Description: {description}

# Output (category only):
# """

#         # Detailed logic logging
#         if _use_groq and client:
#             try:
#                 print(f"LOG: Attempting Groq classification with model {self.model}...")
#                 # response = client.chat.completions.create(
#                 #     model=self.model,
#                 #     messages=[{"role": "user", "content": prompt}],
#                 #     temperature=self.temperature,
#                 #     top_p=self.top_p
#                 # )
#                 # Example improvement for classification_service.py
#                 response = client.chat.completions.create(
#                     model=self.model,
#                     messages=[{"role": "user", "content": prompt}],
#                     response_format={"type": "json_object"} # Forces JSON output
#                 )
#                 return response.choices[0].message.content.strip()
#             except Exception as e:
#                 print(f"LOG ERROR: Groq API call failed: {str(e)}") 
#         else:
#             reason = "Groq Key Missing" if not _use_groq else "Client Object None"
#             print(f"LOG: Skipping Groq (Reason: {reason})")

#         print("LOG: Proceeding with Gemini fallback...")
#         return self._predict_with_gemini(prompt)

# def predict_categories(subject, description):
#     service = GroqClassificationService()
#     return service.predict_categories(subject, description)

import json
from utils.categories_with_description import TAXONOMY
from utils.client import client, _use_groq, _gemini_client

class GroqClassificationService:
    def __init__(self, model="llama-3.1-8b-instant", temperature=0.8, top_p=0.3):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.categories_with_desc = "\n".join(
            [f"{k}: {v}" for k, v in TAXONOMY.items()]
        )
        self.gemini_model = "gemini-2.0-flash" 

    def _predict_with_gemini(self, prompt: str) -> str:
        if not _gemini_client:
            raise ValueError("Gemini client not initialized")
            
        response = _gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=prompt
        )
        text = response.text.strip()
        # Handle cases where Gemini might return the JSON structure requested in the prompt
        if text.startswith('{'):
            try:
                return json.loads(text).get("category", text)
            except:
                pass
        return text

    def predict_categories(self, subject: str, description: str) -> str:
        # FIX: Added 'json' to the prompt to satisfy Groq's response_format requirement
        prompt = f"""
You are a zero-shot classifier. 
Return your answer in JSON format with a single key 'category'.
Choose EXACTLY ONE category from the list below.

Categories:
{self.categories_with_desc}

Subject: {subject}
Description: {description}
"""

        if _use_groq and client:
            try:
                print(f"LOG: Attempting Groq classification with model {self.model}...")
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    top_p=self.top_p,
                    response_format={"type": "json_object"}
                )
                
                # Parse the JSON response
                res_content = response.choices[0].message.content.strip()
                res_data = json.loads(res_content)
                return res_data.get("category", res_content)
                
            except Exception as e:
                print(f"LOG ERROR: Groq attempt failed: {str(e)}") 

        print("LOG: Falling back to Gemini...")
        return self._predict_with_gemini(prompt)

def predict_categories(subject, description):
    service = GroqClassificationService()
    return service.predict_categories(subject, description)