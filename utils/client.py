from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

# Set up the Groq client with fallback to Gemini
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Try to initialize Groq client, fallback to None if key is missing
try:
    if not GROQ_API_KEY:
        raise ValueError("Groq API Key not Found")
    client = Groq()
    _use_groq = True
except Exception as e:
    print(f"Warning: Groq client initialization failed: {str(e)}")
    client = None
    _use_groq = False

# Initialize Gemini client for fallback (always try to initialize if key is available)
_gemini_client = None
try:
    from google import genai
    if GEMINI_API_KEY:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        if not _use_groq:
            print("Using Gemini API as primary provider")
        else:
            print("Gemini API configured as fallback")
    elif not _use_groq:
        print("Warning: Neither Groq nor Gemini API keys are available")
except ImportError:
    if not _use_groq:
        print("Warning: google-genai package not installed. Install it for Gemini fallback support.")
except Exception as e:
    if not _use_groq:
        print(f"Warning: Gemini client initialization failed: {str(e)}")