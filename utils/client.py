import os
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

# Load .env only if it exists (primarily for local testing)
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- BOOTSTRAP LOGGING ---
print(f"INIT LOG: Groq Key Found: {bool(GROQ_API_KEY)}")
print(f"INIT LOG: Gemini Key Found: {bool(GEMINI_API_KEY)}")

# --- LangChain Chat Model Initialization ---
groq_llm = None
gemini_llm = None

_use_groq = False
_use_gemini = False

if GROQ_API_KEY:
    try:
        groq_llm = ChatGroq(
            api_key=GROQ_API_KEY,
            model="llama-3.1-8b-instant",
            temperature=0.3,
        )
        _use_groq = True
        print("INIT LOG: LangChain Groq ChatGroq successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Groq LangChain initialization failed: {str(e)}")
else:
    print("INIT LOG: Groq API Key is missing. Groq will be disabled.")

if GEMINI_API_KEY:
    try:
        gemini_llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.3,
            google_api_key=GEMINI_API_KEY,
        )
        _use_gemini = True
        print("INIT LOG: LangChain Gemini ChatGoogleGenerativeAI successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Gemini LangChain initialization failed: {str(e)}")
        gemini_llm = None
else:
    print("INIT LOG: Gemini API Key is missing.")


def has_any_llm() -> bool:
    return bool(groq_llm or gemini_llm)