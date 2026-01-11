from utils.client import client, _use_groq, _gemini_client

def generate_subject_from_description(description: str, max_length: int = 70) -> str:
    if not description or not description.strip():
        return "General Inquiry"[:max_length]

    prompt = f"""
Generate a concise subject (max {max_length} chars).
Return ONLY the subject.

Description:
{description}
"""

    # 1. Try Groq
    if _use_groq and client:
        try:
            print("LOG: Subject Gen: Attempting Groq...")
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=50
            )
            return response.choices[0].message.content.strip()[:max_length]
        except Exception as e:
            print(f"LOG ERROR: Subject Gen: Groq failed: {str(e)}")

    # 2. Try Gemini
    if _gemini_client:
        try:
            print("LOG: Subject Gen: Attempting Gemini...")
            response = _gemini_client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt
            )
            return response.text.strip()[:max_length]
        except Exception as e:
            print(f"LOG ERROR: Subject Gen: Gemini failed: {str(e)}")

    print("LOG: Subject Gen: All AI options failed, using raw description.")
    return description.strip()[:max_length]