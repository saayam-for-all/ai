from groq import Groq
from google import genai
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import logging

from utils.model_fallback import ModelTarget

logger = logging.getLogger(__name__)

GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"

# Legacy defaults used by the prebuilt LangChain exports below.  New fallback
# code gets model IDs and per-model options from config/model_routing.json.
# Keep these until subject and answer generation finish migrating to the
# target-aware factory.
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_TEMPERATURE = 0.3
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.3

GROQ_API_KEY = None
GEMINI_API_KEY = None


def create_chat_model(target: ModelTarget, *, temperature: float):
    """Construct a LangChain chat model for one configured target.

    Model selection and fallback order belong to ``model_routing.json`` and
    ``run_model_chain``.  This factory only turns the selected target into the
    matching provider client using the credentials loaded by this module.
    """
    if target.provider == "groq":
        if not GROQ_API_KEY:
            raise ValueError("Groq API key is not configured")

        kwargs = {
            "api_key": GROQ_API_KEY,
            "model": target.model,
            "temperature": temperature,
        }
        if target.reasoning_effort:
            kwargs["reasoning_effort"] = target.reasoning_effort
        return ChatGroq(**kwargs)

    if target.provider == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API key is not configured")

        return ChatGoogleGenerativeAI(
            google_api_key=GEMINI_API_KEY,
            model=target.model,
            temperature=temperature,
        )

    raise ValueError(f"Unsupported model provider: {target.provider}")


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

# Legacy prebuilt LangChain models used by answer and subject generation until
# those services call create_chat_model(target, ...) from the shared chain.
groq_llm = None
gemini_llm = None

_use_groq = False
_use_gemini = False

if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        groq_llm = create_chat_model(
            ModelTarget(provider="groq", model=GROQ_MODEL),
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
        gemini_llm = create_chat_model(
            ModelTarget(provider="gemini", model=GEMINI_MODEL),
            temperature=GEMINI_TEMPERATURE,
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
