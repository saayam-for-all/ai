"""
Category-specific prompts optimized for short, precise, and 100% accurate answers.
Each prompt emphasizes using location, gender, age, subject, and description context effectively.
"""
from config.all_prompts import (
    NOT_SPECIFIED,
    BASE_INSTRUCTION,
    CATEGORY_PROMPTS_PROMPTS_NO_HALLUCINATIONS,
    CONVERSATIONAL_BASE_INSTRUCTION,
    CONVERSATIONAL_CONTEXT,
    CONTEXT_LIMITATION,
)

# Constants
NOT_SPECIFIED = NOT_SPECIFIED

BASE_INSTRUCTION = BASE_INSTRUCTION

CONTEXT_LIMITATION = CONTEXT_LIMITATION

category_prompts = CATEGORY_PROMPTS_PROMPTS_NO_HALLUCINATIONS


def get_prompt(category: str, subject: str, description: str, location: str = "", gender: str = "", age: str = "") -> str:
    """
    Get the formatted prompt for a category with all context variables filled in.
    
    Args:
        category: The category name
        subject: User's subject
        description: User's description/question
        location: User's location (optional, empty string if not provided)
        gender: User's gender (optional, empty string if not provided)
        age: User's age (optional, empty string if not provided)
        
    Returns:
        Formatted prompt string ready for LLM
    """
    base_prompt = category_prompts.get(
        category,
        category_prompts["General"]  # Fallback to General
    )
    
    # Determine location, gender, and age instructions based on whether they're provided
    if location and location.strip():
        location_str = location
        location_instruction = f"Include location-specific resources for {location} when available"
    else:
        location_str = NOT_SPECIFIED
        location_instruction = "Provide general, non-location-specific guidance"
    
    if gender and gender.strip():
        gender_str = gender
        gender_instruction = f"Address {gender}-specific needs when relevant"
    else:
        gender_str = NOT_SPECIFIED
        gender_instruction = "Provide gender-neutral guidance"
    
    if age and age.strip():
        age_str = age
        age_instruction = f"Consider age-appropriate resources and considerations for {age} when relevant"
    else:
        age_str = NOT_SPECIFIED
        age_instruction = "Provide age-neutral guidance"
    
    # Format the base instruction
    base_instruction_formatted = (
        BASE_INSTRUCTION.format(
            location=location_str,
            gender=gender_str,
            age=age_str,
            subject=subject,
            description=description,
            location_instruction=location_instruction,
            gender_instruction=gender_instruction,
            age_instruction=age_instruction)
        + "\n\n"
        + CONTEXT_LIMITATION
    )
    
    # Format the category-specific prompt
    formatted_prompt = base_prompt.format(
        base_instruction=base_instruction_formatted,
        location=location_str,
        gender=gender_str,
        age=age_str,
        subject=subject,
        description=description
    )
    
    return formatted_prompt


def get_conversational_prompt(category: str, subject: str, location: str = "", gender: str = "", age: str = "") -> str:
    """
    Get a conversational system prompt for chat-based interactions with context maintenance.
    This prompt is optimized for maintaining conversation context across multiple turns.
    
    Args:
        category: The category name
        subject: User's subject (for initial context)
        location: User's location (optional, empty string if not provided)
        gender: User's gender (optional, empty string if not provided)
        age: User's age (optional, empty string if not provided)
        
    Returns:
        Formatted system prompt string for conversational LLM
    """
    base_prompt = category_prompts.get(
        category,
        category_prompts["General"]  # Fallback to General
    )
    
    # Determine location, gender, and age instructions based on whether they're provided
    if location and location.strip():
        location_str = location
        location_instruction = f"Include location-specific resources for {location} when available"
    else:
        location_str = NOT_SPECIFIED
        location_instruction = "Provide general, non-location-specific guidance"
    
    if gender and gender.strip():
        gender_str = gender
        gender_instruction = f"Address {gender}-specific needs when relevant"
    else:
        gender_str = NOT_SPECIFIED
        gender_instruction = "Provide gender-neutral guidance"
    
    if age and age.strip():
        age_str = age
        age_instruction = f"Consider age-appropriate resources and considerations for {age} when relevant"
    else:
        age_str = NOT_SPECIFIED
        age_instruction = "Provide age-neutral guidance"
    

    conversational_base_instruction = CONVERSATIONAL_BASE_INSTRUCTION
    
    # Format the conversational base instruction
    base_instruction_formatted = (
        conversational_base_instruction.format(
            location=location_str,
            gender=gender_str,
            age=age_str,
            subject=subject,
            location_instruction=location_instruction,
            gender_instruction=gender_instruction,
            age_instruction=age_instruction
        )
        + "\n\n"
        + CONTEXT_LIMITATION
    )
    # Format the category-specific prompt (without description since it comes in user messages)
    formatted_prompt = base_prompt.format(
        base_instruction=base_instruction_formatted,
        location=location_str,
        gender=gender_str,
        age=age_str,
        subject=subject,
        description="[User's question will be provided in the conversation]"
    )
    
    # Add conversational context instructions
    conversational_context = CONVERSATIONAL_CONTEXT
    
    return formatted_prompt + conversational_context


# Legacy support - keep the old dictionary for backward compatibility
# But the get_prompt function is preferred for new code
