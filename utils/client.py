from groq import Groq
from google import genai
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import logging

logger = logging.getLogger(__name__)

GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"

# Model / temperature configuration.
# Imported by utils/__init__.py (answer generation) and used to build the models below.
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_TEMPERATURE = 0.3
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.3

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

# Raw SDK clients (used by services/classification_service.py):
#   client.chat.completions.create(...)  and  _gemini_client.models.generate_content(...)
client = None
_gemini_client = None

# LangChain chat models (used by utils/__init__.py answer generation and
# utils/subject_generator.py):  groq_llm.invoke(...) / gemini_llm.invoke(...)
groq_llm = None
gemini_llm = None

_use_groq = False
_use_gemini = False

if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        groq_llm = ChatGroq(
            api_key=GROQ_API_KEY,
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
        )
        _use_groq = True
        print("INIT LOG: Groq clients (raw + LangChain) successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Groq initialization failed: {str(e)}")
        client = None
        groq_llm = None
        _use_groq = False
else:
    print("INIT LOG: Groq API Key is missing. Groq will be disabled.")

if GEMINI_API_KEY:
    try:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        gemini_llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            temperature=GEMINI_TEMPERATURE,
            google_api_key=GEMINI_API_KEY,
        )
        _use_gemini = True
        print("INIT LOG: Gemini clients (raw + LangChain) successfully initialized.")
    except Exception as e:
        print(f"INIT ERROR: Gemini initialization failed: {str(e)}")
        _gemini_client = None
        gemini_llm = None
        _use_gemini = False
else:
    print("INIT LOG: Gemini API Key is missing.")


def has_any_llm() -> bool:
    return bool(groq_llm or gemini_llm)
