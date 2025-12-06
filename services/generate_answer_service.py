from abc import ABC, abstractmethod
from typing import Optional, List, Dict
from services import AnswerGenerationServiceInterface, ClassificationServiceInterface
from utils.prompts import get_prompt, get_conversational_prompt
from utils.client import client

# Constants
NOT_SPECIFIED = "Not specified"


class GroqAnswerGenerationService(AnswerGenerationServiceInterface):
    """Groq/LLaMA implementation of answer generation service."""
    
    def __init__(
        self, 
        model: str = "llama-3.1-8b-instant", 
        temperature: float = 0.7, 
        classification_service: Optional[ClassificationServiceInterface] = None
    ):
        self.model = model
        self.temperature = temperature
        self.classification_service = classification_service
    
    def generate_answer(
        self, 
        category: str, 
        subject: str, 
        description: str, 
        location: Optional[str] = None, 
        gender: Optional[str] = None,
        age: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Generate conversational answer with context maintenance using Groq/LLaMA.
        Maintains conversation history to provide context-aware responses.
        """
        print(f'Initial Category: {category}')
        
        # Predict Category ONLY when the user inputs General as category.
        if category == 'General' and self.classification_service:
            category = self.classification_service.predict_categories(subject=subject, description=description)
        
        print('updated category: ', category)
        
        # Get the system prompt with context
        system_prompt = get_conversational_prompt(
            category=category,
            subject=subject,
            location=location or "",
            gender=gender or "",
            age=age or ""
        )
        
        # Build message history for conversational context
        messages = []
        
        # Add system message with context
        messages.append({"role": "system", "content": system_prompt})
        
        # Add conversation history if provided (maintains context across turns)
        if conversation_history:
            # Validate and add previous messages
            for msg in conversation_history:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    # Only include user and assistant messages (skip system messages from history)
                    if msg["role"] in ["user", "assistant"]:
                        messages.append({
                            "role": msg["role"],
                            "content": str(msg["content"])  # Ensure content is a string
                        })
        
        # Add current user message
        current_user_message = f"Subject: {subject}\nQuestion: {description}"
        messages.append({"role": "user", "content": current_user_message})
        
        print(f"Total messages in context: {len(messages)}")
        print(f"First message role: {messages[0]['role'] if messages else 'None'}")
        
        try:
            # Make call to Groq API with full conversation context
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature
            )
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Empty response from Groq API")
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error in Groq API call: {str(e)}")
            print(f"Traceback: {error_trace}")
            print(f"Messages being sent: {messages}")
            raise


# Legacy function wrapper for backward compatibility
def chat_with_llama(category, subject, description, location=None, gender=None, age=None, conversation_history=None):
    """Legacy function wrapper - uses default Groq service."""
    from services.classification_service import GroqClassificationService
    classification_service = GroqClassificationService()
    service = GroqAnswerGenerationService(classification_service=classification_service)
    return service.generate_answer(category, subject, description, location, gender, age, conversation_history)
