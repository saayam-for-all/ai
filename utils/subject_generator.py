import re

from utils.client import groq_llm, gemini_llm, _use_groq, _use_gemini

# Strips a leading "Subject:" / "Title:" label that some models prepend despite
# being told not to.
_LABEL_RE = re.compile(r"^\s*(subject|title)\s*[:\-]\s*", re.IGNORECASE)

# Safety net for status words the prompt already forbids. Models still slip
# these into subjects; stripping here is deterministic.
_STATUS_PHRASE_RE = re.compile(r"\blooking for\b", re.IGNORECASE)
_STATUS_WORD_RE = re.compile(
    r"\b(needed|needs|need|required|wanted|seeking|help|guidance|request|assistance)\b",
    re.IGNORECASE,
)


def _clean_subject(text) -> str:
    """Normalize a raw LLM subject: drop a leading label, quotes, and status words."""
    s = str(text).strip()
    s = _LABEL_RE.sub("", s)
    s = s.strip().strip('"').strip("'").strip()
    s = _STATUS_PHRASE_RE.sub(" ", s)
    s = _STATUS_WORD_RE.sub(" ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" ,-")
    return s or "General Inquiry"


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
    prompt = f"""You are writing the subject line for a help request. Produce ONE concise, specific subject (max {max_length} characters) for the description below. Write it as the person's own request or concern, never as a diagnosis or clinical assessment.

Rules:
- Write a concise noun phrase, like a news headline.
- Include the specific details actually stated (symptoms, who it's for, type, timeframe), and keep meaning-critical words exactly (e.g. "roommate" is not "room").
- If the person raises a possible cause, body part, or specialty they are worried about (e.g. "not sure if it's my heart"), keep that cue but frame it as THEIR concern (e.g. "Heart Concern"), NOT as a diagnosis. Do not add words like "Possible", "Issue", "Condition", or "Disorder" that they did not say.
- Do not introduce assessment, severity, or certainty words the person did not use (e.g. "severe", "chronic", "acute", "unexplained").
- Do NOT over-generalize away specifics: keep "ringing / congestion" (not "ear problem"); keep BOTH symptoms if two are stated; keep a stated timeframe like "short/mid term".
- Name the thing itself; do NOT use status words like "Needed", "Needs", "Required", "Wanted", "Seeking", "Looking for", "Help", "Guidance", "Request", "Assistance", or "Appointment". E.g. "Knee Injury Physiotherapy Needed" -> "Knee Injury Physiotherapy"; "Kid Needs Warm Winter Coat" -> "Warm Winter Coat for School".
- Do not invent details.
- Do not invent abstract labels the person did not use. E.g. "my car broke down and I cannot afford the repair" -> "Car Breakdown, Cannot Afford Repair", never "Affordability".
- Output ONLY the subject text: no quotes, no "Subject:"/"Title:" label, no explanation.

Examples (description -> subject):
"My ears feel clogged and are ringing lately." -> Ear Congestion and Ringing
"I feel tired and short of breath on stairs, not sure if it's my heart." -> Fatigue and Breathlessness, Heart Concern
"Single male looking for a roommate to share a room for rent, short/mid term." -> Single Male Roommate for Rent (Short/Mid Term)

Description: {description}"""

    # ---------- CASE 1: Short description ----------

    # If description is already short enough, use it directly (with some processing)
    if len(description) <= max_length:
        # generate a better summary if possible, but fallback to truncated description
        truncated = description[:max_length]

        # Try Groq (LangChain) first
        if _use_groq and groq_llm:
            try:
                ai_message = groq_llm.invoke(prompt)
                content = getattr(ai_message, "content", None) or ""
                generated_subject = _clean_subject(content)

                # Strictly enforce max_length - truncate if necessary
                if len(generated_subject) <= max_length:
                    return generated_subject
                return _truncate_with_word_boundary(generated_subject, max_length)
            except Exception as e:
                print(f"Error generating subject with Groq (LangChain), trying Gemini: {str(e)}")

        # Fallback to Gemini (LangChain)
        if _use_gemini and gemini_llm:
            try:
                ai_message = gemini_llm.invoke(prompt)
                content = getattr(ai_message, "content", None) or ""
                generated_subject = _clean_subject(content)

                # Strictly enforce max_length - truncate if necessary
                if len(generated_subject) <= max_length:
                    return generated_subject
                return _truncate_with_word_boundary(generated_subject, max_length)
            except Exception as e:
                print(f"Error generating subject with Gemini (LangChain): {str(e)}")

        # Final fallback: return original description
        print("Error generating subject, using truncated description")
        return truncated

    # ---------- CASE 2: Long description ----------

    # Try Groq (LangChain) first
    if _use_groq and groq_llm:
        try:
            ai_message = groq_llm.invoke(prompt)
            content = getattr(ai_message, "content", None) or ""
            generated_subject = str(content).strip().strip('"').strip("'") or "General Inquiry"

            # Strictly enforce max_length (70 characters)
            if len(generated_subject) <= max_length:
                return generated_subject
            return _truncate_with_word_boundary(generated_subject, max_length)
        except Exception as e:
            print(f"Error generating subject with Groq (LangChain), trying Gemini: {str(e)}")

    # Fallback to Gemini (LangChain)
    if _use_gemini and gemini_llm:
        try:
            ai_message = gemini_llm.invoke(prompt)
            content = getattr(ai_message, "content", None) or ""
            generated_subject = str(content).strip().strip('"').strip("'") or "General Inquiry"

            # Strictly enforce max_length
            if len(generated_subject) <= max_length:
                return generated_subject
            return _truncate_with_word_boundary(generated_subject, max_length)

        except Exception as e:
            print(f"Error generating subject with Gemini (LangChain): {str(e)}")

    # Final fallback: return truncated description (strictly enforce max_length)
    print("Error generating subject from description, using truncated description")
    return _truncate_with_word_boundary(description, max_length)