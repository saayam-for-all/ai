"""
Utility module for generating summarized subjects from descriptions.
Python 3.14+ compatible.
"""
from utils.client import client


def generate_subject_from_description(description: str, max_length: int = 70) -> str:
    """
    Generate a concise subject summary from a description using LLM.
    Automatically generates a subject without asking the user for input.
    
    Args:
        description: The user's description/question
        max_length: Maximum character length for the generated subject (default: 70)
        
    Returns:
        str: A concise subject summary (max max_length characters, strictly enforced)
    """
    if not description or not description.strip():
        return "General Inquiry"[:max_length]
    
    # If description is already short enough, use it directly (with some processing)
    if len(description.strip()) <= max_length:
        # Still generate a better summary if possible, but fallback to truncated description
        truncated = description.strip()[:max_length]
        # Try to generate a better summary
        try:
            prompt = f"""Generate a concise subject/title (maximum {max_length} characters) that summarizes the following description. 
Return ONLY the subject, no additional text or explanation. Keep it brief and descriptive.

Description: {description}

Subject (max {max_length} chars):"""
            
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=50
            )
            
            generated_subject = response.choices[0].message.content.strip()
            # Strictly enforce max_length - truncate if necessary
            if len(generated_subject) <= max_length:
                return generated_subject
            else:
                # Truncate to max_length, trying to cut at word boundary
                truncated = generated_subject[:max_length]
                last_space = truncated.rfind(' ')
                if last_space > max_length * 0.7:  # Keep at least 70% of length
                    return truncated[:last_space].strip()
                return truncated.strip()
        except Exception as e:
            print(f"Error generating subject, using truncated description: {str(e)}")
            return truncated
    
    # For longer descriptions, generate a summary
    try:
        prompt = f"""Generate a concise subject/title (maximum {max_length} characters) that summarizes the following description. 
Return ONLY the subject, no additional text or explanation. Keep it brief and descriptive.

Description: {description}

Subject (max {max_length} chars):"""
        
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50
        )
        
        generated_subject = response.choices[0].message.content.strip()
        
        # Strictly enforce max_length (70 characters)
        if len(generated_subject) <= max_length:
            return generated_subject
        else:
            # Truncate to max_length, trying to cut at word boundary if possible
            truncated = generated_subject[:max_length]
            # Try to cut at last space to avoid cutting words
            last_space = truncated.rfind(' ')
            if last_space > max_length * 0.7:  # Only if we keep at least 70% of the length
                return truncated[:last_space].strip()
            return truncated.strip()
            
    except Exception as e:
        print(f"Error generating subject from description: {str(e)}")
        # Fallback: return truncated description (strictly enforce max_length)
        truncated = description.strip()[:max_length]
        # Try to cut at word boundary
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.7:
            result = truncated[:last_space].strip()
        else:
            result = truncated.strip()
        # Final check to ensure we never exceed max_length
        return result[:max_length]

