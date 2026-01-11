import os
from groq import Groq
from google import genai
from dotenv import load_dotenv

# Load .env only if it exists (primarily for local testing)
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- BOOTSTRAP LOGGING ---
print(f"INIT LOG: Groq Key Found: {bool(GROQ_API_KEY)}")
print(f"INIT LOG: Gemini Key Found: {bool(GEMINI_API_KEY)}")

# --- Groq Initialization ---
client = None
_use_groq = False
if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        _use_groq = True
        print("INIT LOG: Groq Client successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Groq initialization failed: {str(e)}")
else:
    print("INIT LOG: Groq API Key is missing. Groq will be disabled.")

# --- Gemini (New SDK) Initialization ---
_gemini_client = None
if GEMINI_API_KEY:
    try:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print("INIT LOG: Gemini Client successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Gemini initialization failed: {str(e)}")
        _gemini_client = None
else:
    print("INIT LOG: Gemini API Key is missing.")