import os
from pydantic import SecretStr
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI


def load_llm():
    """
    Load LLM client with Groq-first, Gemini-fallback strategy.
    Groq (free tier) is attempted first. If unavailable, falls back to Gemini.
    """
    # Try Groq first (free tier)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        print("Using Groq model")
        return ChatGroq(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0.1,
            api_key=SecretStr(groq_key),
        )

    # Fallback to Gemini (paid)
    gemini_key = os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        print("Using Gemini model (fallback)")
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            temperature=0.1,
            google_api_key=SecretStr(gemini_key),
        )

    raise ValueError(
        "No LLM available. Set GROQ_API_KEY or GOOGLE_API_KEY in environment."
    )