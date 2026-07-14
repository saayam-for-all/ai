from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import logging

logger = logging.getLogger(__name__)

GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"

GROQ_API_KEY = None
GEMINI_API_KEY = None

# Fetching keys from parameter store
try:
    ssm = boto3.client("ssm")
    response = ssm.get_parameters(
        Names=[GROQ_PARAM, GEMINI_PARAM],
        WithDecryption=True
    )

    params = {p["Name"]: p["Value"] for p in response.get("Parameters", [])}

    missing = [n for n in [GROQ_PARAM, GEMINI_PARAM] if n not in params]
    if missing:
        logger.warning("INIT: Parameters not found in SSM: %s", missing)

    GROQ_API_KEY = params.get(GROQ_PARAM)
    GEMINI_API_KEY = params.get(GEMINI_PARAM)

except (BotoCoreError, ClientError) as e:
    logger.error("INIT: Failed to fetch from Parameter Store: %s", str(e))

except Exception as e:
    logger.exception("INIT: Unexpected error fetching from Parameter Store: %s", str(e))

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