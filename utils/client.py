from functools import lru_cache
import logging

from groq import Groq
from google import genai
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from utils.model_fallback import ModelTarget

logger = logging.getLogger(__name__)

GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"

# Legacy defaults used by the prebuilt LangChain exports below.
# Keep these while subject generation still relies on those exports.
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_TEMPERATURE = 0.3
GROQ_REASONING_EFFORT = "low"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.3

GROQ_API_KEY = None
GEMINI_API_KEY = None


@lru_cache(maxsize=32)
def _create_chat_model_cached(
    provider: str,
    model_name: str,
    temperature: float,
    reasoning_effort: str | None,
    api_key: str,
):
    if provider == "groq":
        kwargs = {
            "api_key": api_key,
            "model": model_name,
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        return ChatGroq(**kwargs)

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            google_api_key=api_key,
            model=model_name,
            temperature=temperature,
        )

    raise ValueError(f"Unsupported model provider: {provider}")


def create_chat_model(target: ModelTarget, *, temperature: float):
    """Return a cached LangChain model for the configured target."""
    if target.provider == "groq":
        api_key = GROQ_API_KEY
    elif target.provider == "gemini":
        api_key = GEMINI_API_KEY
    else:
        raise ValueError(f"Unsupported model provider: {target.provider}")

    if not api_key:
        provider_name = "Groq" if target.provider == "groq" else "Gemini"
        raise ValueError(f"{provider_name} API key is not configured")

    return _create_chat_model_cached(
        target.provider,
        target.model,
        temperature,
        target.reasoning_effort,
        api_key,
    )


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

# Legacy prebuilt LangChain models retained for subject generation.
# Answer generation creates models through the shared configured model chain.
groq_llm = None
gemini_llm = None

_use_groq = False
_use_gemini = False

if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        groq_llm = create_chat_model(
            ModelTarget(
                provider="groq",
                model=GROQ_MODEL,
                reasoning_effort=GROQ_REASONING_EFFORT,
            ),
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
