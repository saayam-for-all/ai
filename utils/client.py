from groq import Groq
import os

# Set up the Groq client
GROQ_API_KEY = os.environ["GROQ_API_KEY"] 
client = Groq()