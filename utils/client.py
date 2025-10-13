from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

# Set up the Groq client

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("Groq API Key not Found")

client = Groq()