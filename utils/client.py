from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import logging

logging.basicConfig(level=logging.INFO)
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

# Model config (constants)
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_TEMPERATURE = 0.7
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.7

# --- LangChain Chat Model Initialization ---
groq_llm = None
gemini_llm = None
_use_groq = False
_use_gemini = False

if GROQ_API_KEY:
    try:
        groq_llm = ChatGroq(
            api_key=GROQ_API_KEY,
<<<<<<< HEAD
            model="llama-3.1-8b-instant",
            temperature=0.3,
        )
        _use_groq = True
        print("INIT LOG: LangChain Groq ChatGroq successfully initialized.")
=======
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
        )
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
        )
        _use_groq = True
        print("INIT LOG: Groq LLM successfully initialized.")
            temperature=0.3,
            google_api_key=GEMINI_API_KEY,
        )

# --- Gemini Initialization (LangChain) ---
if GEMINI_API_KEY:
    try:
        gemini_llm = ChatGoogleGenerativeAI(
            api_key=GEMINI_API_KEY,
            model=GEMINI_MODEL,
            temperature=GEMINI_TEMPERATURE,
        )
        _use_gemini = True
        print("INIT LOG: Gemini LLM successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Gemini LangChain initialization failed: {str(e)}")
        gemini_llm = None
else:
    print("INIT LOG: Gemini API Key is missing.")


def has_any_llm() -> bool:
    return bool(groq_llm or gemini_llm)