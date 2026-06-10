"""
Answer generation service using Groq with Gemini fallback.
Python 3.14+ compatible.
"""

from utils import GroqAnswerGenerationService

def generate_ai_answer(
    category: str,
    subject: str,
    description: str,
    location: str | None = None,
    gender: str | None = None,
    age: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    additional_info: list[dict] | None = None,
) -> str:
    """Legacy function wrapper for backward compatibility."""
    service = GroqAnswerGenerationService()
    return service.generate_answer(
        category=category,
        subject=subject,
        description=description,
        location=location,
        gender=gender,
        age=age,
        conversation_history=conversation_history,
        additional_info=additional_info,
    )