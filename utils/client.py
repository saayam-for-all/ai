import os
import logging
import boto3
from groq import Groq
from google import genai
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

DEFAULT_GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
DEFAULT_GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"


def _load_keys_from_ssm() -> tuple[str | None, str | None]:
    groq_param = os.getenv("GROQ_API_KEY_PARAM", DEFAULT_GROQ_PARAM)
    gemini_param = os.getenv("GEMINI_API_KEY_PARAM", DEFAULT_GEMINI_PARAM)
    session = boto3.session.Session()
    region = (
        session.region_name
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
    )

    if not region:
        return None, None

    try:
        ssm = session.client("ssm", region_name=region)
        response = ssm.get_parameters(
            Names=[groq_param, gemini_param],
            WithDecryption=True,
        )
        params = {
            param["Name"]: param["Value"] for param in response.get("Parameters", [])
        }
        missing = [name for name in [groq_param, gemini_param] if name not in params]
        if missing:
            logger.warning("INIT WARN: Parameters not found in SSM: %s", missing)
        return params.get(groq_param), params.get(gemini_param)
    except (BotoCoreError, ClientError) as e:
        logger.warning("INIT WARN: Failed to fetch API keys from SSM: %s", str(e))
    except Exception as e:
        logger.exception("INIT ERROR: Unexpected SSM fetch error: %s", str(e))
    return None, None


GROQ_API_KEY, GEMINI_API_KEY = _load_keys_from_ssm()
groq_source = "ssm" if GROQ_API_KEY else "missing"
gemini_source = "ssm" if GEMINI_API_KEY else "missing"

# --- BOOTSTRAP LOGGING ---
print(f"INIT LOG: Groq Key Found: {bool(GROQ_API_KEY)}")
print(f"INIT LOG: Gemini Key Found: {bool(GEMINI_API_KEY)}")
print(f"INIT LOG: Groq Key Source: {groq_source}")
print(f"INIT LOG: Gemini Key Source: {gemini_source}")

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
