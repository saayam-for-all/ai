from utils.client import client, _use_groq, _gemini_client

def _truncate_with_word_boundary(text: str, max_length: int) -> str:
    """
    Truncate text to max_length.
    Try to cut at the last space if it keeps at least 70% of max_length.
    Otherwise, hard truncate.
    """
    truncated = text[:max_length]
    print("truncated", truncated)
    # find last space index
    last_space = truncated.rfind(" ")

    # only cut at the word boundary if that boundary is close to max limit
    if last_space > max_length * 0.7:
        print("last space >max len")
        return truncated[:last_space].strip()

    return truncated.strip()

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
    
    description = description.strip()

    # declaring prompt
    prompt = f"""Generate a concise subject/title (maximum {max_length} characters) that summarizes the following description. 
Return ONLY the subject, no additional text or explanation. Keep it brief and descriptive.

Description: {description}

Subject (max {max_length} chars)"""

    # ---------- CASE 1: Short description ----------

    # If description is already short enough, use it directly (with some processing)
    if len(description) <= max_length:
        # generate a better summary if possible, but fallback to truncated description
        truncated = description[:max_length]
        
        # Try Groq first
        if _use_groq and client:
            try:
                response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=50
                )

                if response.choices[0].message.content:
                    generated_subject = response.choices[0].message.content.strip()
                    generated_subject = generated_subject.strip('"').strip("'")
                else:
                    generated_subject = "General Inquiry"

                # Strictly enforce max_length - truncate if necessary
                if len(generated_subject) <= max_length:
                    return generated_subject
                else:
                    # Truncate to max_length, trying to cut at word boundary
                    return _truncate_with_word_boundary(generated_subject, max_length)
            except Exception as e:
                print(f"Error generating subject with Groq, trying Gemini: {str(e)}")
        
        # Fallback to Gemini
        if _gemini_client:
            try:
                response = _gemini_client.models.generate_content(
                    model="gemini-2.5-flash", 
                    contents=prompt
                )

                if response.text:
                    generated_subject = response.text.strip()
                    generated_subject = generated_subject.strip('"').strip("'")
                else:
                    generated_subject = "General Inquiry"
                
                # Strictly enforce max_length - truncate if necessary
                if len(generated_subject) <= max_length:
                    return generated_subject
                else:
                    return _truncate_with_word_boundary(generated_subject, max_length)
            except Exception as e:
                print(f"Error generating subject with Gemini: {str(e)}")
        
        # Final fallback: return original description
        print(f"Error generating subject, using truncated description")
        return truncated
    
    # ---------- CASE 2: Long description ----------

    # Try Groq first
    if _use_groq and client:
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=50
            )

            if response.choices[0].message.content:
                generated_subject = response.choices[0].message.content.strip()
                generated_subject = generated_subject.strip('"').strip("'")
            else:
                generated_subject = "General Inquiry"
            
            # Strictly enforce max_length (70 characters)
            if len(generated_subject) <= max_length:
                return generated_subject
            else:
                # Truncate to max_length, trying to cut at word boundary if possible
                return _truncate_with_word_boundary(generated_subject, max_length)
        except Exception as e:
            print(f"Error generating subject with Groq, trying Gemini: {str(e)}")
    
    # Fallback to Gemini
    if _gemini_client:
        try:
            response = _gemini_client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt
            )

            if response.text:
                generated_subject = response.text.strip()
                generated_subject = generated_subject.strip('"').strip("'")
            else:
                generated_subject = "General Inquiry"
            
            # Strictly enforce max_length
            if len(generated_subject) <= max_length:
                return generated_subject
            else:
                return _truncate_with_word_boundary(generated_subject, max_length)

        except Exception as e:
            print(f"Error generating subject with Gemini: {str(e)}")
    
    # Final fallback: return truncated description (strictly enforce max_length)
    print(f"Error generating subject from description, using truncated description")
    return _truncate_with_word_boundary(description, max_length)