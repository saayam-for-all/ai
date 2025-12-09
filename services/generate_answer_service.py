"""
Answer generation service using Groq/LLaMA with Gemini fallback.
Python 3.14+ compatible.
"""
from abc import ABC, abstractmethod
from services import AnswerGenerationServiceInterface, ClassificationServiceInterface
from utils.prompts import get_prompt, get_conversational_prompt
from utils.client import client, _use_groq, _gemini_client

# Constants
NOT_SPECIFIED = "Not specified"


class GroqAnswerGenerationService(AnswerGenerationServiceInterface):
    """Groq/LLaMA implementation of answer generation service with Gemini fallback."""
    
    def __init__(
        self, 
        model: str = "llama-3.1-8b-instant", 
        temperature: float = 0.7, 
        classification_service: ClassificationServiceInterface | None = None
    ):
        self.model = model
        self.temperature = temperature
        self.classification_service = classification_service
        self.gemini_model = "gemini-2.5-flash"
    
    def _generate_with_gemini(self, messages: list) -> str:
        """Fallback to Gemini API if Groq fails."""
        if not _gemini_client:
            raise ValueError("Gemini API is not available. Please set GEMINI_API_KEY in .env file.")
        
        # Convert messages format for Gemini
        # Gemini uses a different format - combine system and user messages
        prompt_parts = []
        for msg in messages:
            if msg["role"] == "system":
                prompt_parts.append(f"System: {msg['content']}")
            elif msg["role"] == "user":
                prompt_parts.append(f"User: {msg['content']}")
            elif msg["role"] == "assistant":
                prompt_parts.append(f"Assistant: {msg['content']}")
        
        full_prompt = "\n".join(prompt_parts)
        response = _gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=full_prompt
        )
        return response.text.strip()
    
    def generate_answer(
        self, 
        category: str, 
        subject: str, 
        description: str, 
        location: str | None = None, 
        gender: str | None = None,
        age: str | None = None,
        conversation_history: list[dict[str, str]] | None = None
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
        
        # Try Groq first
        if _use_groq and client:
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
                print("Falling back to Gemini API...")
        
        # Fallback to Gemini
        print("Using Gemini API for answer generation")
        try:
            return self._generate_with_gemini(messages)
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error in Gemini API call: {str(e)}")
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
