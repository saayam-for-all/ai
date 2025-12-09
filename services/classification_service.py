from abc import ABC, abstractmethod
from utils.categories_with_description import TAXONOMY
from utils.client import client, _use_groq, _gemini_client
import os
from services import ClassificationServiceInterface


class GroqClassificationService(ClassificationServiceInterface):
    """Groq/LLaMA implementation of classification service with Gemini fallback."""
    
    def __init__(self, model: str = "llama-3.1-8b-instant", temperature: float = 0.8, top_p: float = 0.3):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        # Pre-compute categories description for efficiency
        self.categories_with_desc = "\n".join([f"{k}: {v}" for k, v in TAXONOMY.items()])
        self.gemini_model = "gemini-2.5-flash"
    
    def _predict_with_gemini(self, subject: str, description: str) -> str:
        """Fallback to Gemini API if Groq fails."""
        if not _gemini_client:
            raise ValueError("Gemini API is not available. Please set GEMINI_API_KEY in .env file.")
        
        prompt = f"""
        You are a zero-shot text classifier that classifies user input into exactly one category from the predefined list of categories along with their description below. Respond ONLY with a category from the given list of categories whose meaning closely aligns with the category's description in the list. Do not include any additional text or explanations.

        Categories: {self.categories_with_desc}

        User Input:
        Subject: {subject}
        Description: {description}

        Output (category):
        """
        
        response = _gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=prompt
        )
        return response.text.strip()
    
    def predict_categories(self, subject: str, description: str) -> str:
        """Predict categories using Groq/LLaMA with Gemini fallback."""
        prompt = f"""
        You are a zero-shot text classifier that classifies user input into exactly one category from the predefined list of categories along with their description below. Respond ONLY with a category from the given list of categories whose meaning closely aligns with the category's description in the list. Do not include any additional text or explanations.

        Categories: {self.categories_with_desc}

        User Input:
        Subject: {subject}
        Description: {description}

        Output (category):
        """

        # Try Groq first
        if _use_groq and client:
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    top_p=self.top_p
                )
                raw_output = response.choices[0].message.content.strip()
                print(f"Groq classification result: {raw_output}")
                return raw_output.strip()
            except Exception as e:
                print(f"Groq API call failed: {str(e)}. Falling back to Gemini...")
        
        # Fallback to Gemini
        print("Using Gemini API for classification")
        raw_output = self._predict_with_gemini(subject, description)
        print(f"Gemini classification result: {raw_output}")
        return raw_output.strip()


# Legacy function wrapper for backward compatibility
def predict_categories(subject, description):
    """Legacy function wrapper - uses default Groq service."""
    service = GroqClassificationService()
    return service.predict_categories(subject, description)
