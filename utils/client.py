"""Provider clients, built on first use (#237).

Keys are read from SSM on first use, not at import; call the accessors where used."""
from functools import lru_cache
import logging
import time

from groq import Groq
from google import genai
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from utils.model_fallback import ModelTarget

logger = logging.getLogger(__name__)

GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"

# Legacy defaults for get_groq_llm() / get_gemini_llm().
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_TEMPERATURE = 0.3
GROQ_REASONING_EFFORT = "low"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.3

# After a failed read, skip SSM for this long so one request can't stack slow retries.
FAILURE_BACKOFF_SECONDS = 30

_SSM_CONFIG = Config(
    connect_timeout=2,
    read_timeout=2,
    # total_max_attempts counts the first try (legacy max_attempts doesn't).
    retries={"mode": "standard", "total_max_attempts": 2},
)

_last_failure_at: float | None = None


def _print_key_status(groq_key, gemini_key):
    print(f"INIT LOG: Groq Key Found: {bool(groq_key)}")
    print(f"INIT LOG: Gemini Key Found: {bool(gemini_key)}")


# lru_cache doesn't cache a call that raised, so failed reads aren't cached.
@lru_cache(maxsize=1)
def _fetch_keys() -> tuple[str | None, str | None]:
    """Read both keys from SSM; raises on failure."""
    ssm = boto3.client("ssm", config=_SSM_CONFIG)
    response = ssm.get_parameters(
        Names=[GROQ_PARAM, GEMINI_PARAM],
        WithDecryption=True,
    )
    params = {p["Name"]: p["Value"] for p in response.get("Parameters", [])}

    missing = [n for n in [GROQ_PARAM, GEMINI_PARAM] if n not in params]
    if missing:
        logger.warning("INIT: Parameters not found in SSM: %s", missing)

    keys = (params.get(GROQ_PARAM), params.get(GEMINI_PARAM))
    _print_key_status(*keys)
    return keys


def _load_keys() -> tuple[str | None, str | None]:
    """Return (groq_key, gemini_key), or (None, None) if SSM is failing."""
    global _last_failure_at
    if (
        _last_failure_at is not None
        and time.monotonic() - _last_failure_at < FAILURE_BACKOFF_SECONDS
    ):
        return None, None

    try:
        keys = _fetch_keys()
    except (BotoCoreError, ClientError) as e:
        logger.error("INIT: Failed to fetch from Parameter Store: %s", str(e))
    except Exception as e:
        logger.exception("INIT: Unexpected error fetching from Parameter Store: %s", str(e))
    else:
        _last_failure_at = None
        return keys

    _last_failure_at = time.monotonic()
    _print_key_status(None, None)
    return None, None


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
    groq_key, gemini_key = _load_keys()
    if target.provider == "groq":
        api_key = groq_key
    elif target.provider == "gemini":
        api_key = gemini_key
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


@lru_cache(maxsize=4)
def _build_groq_client(api_key: str):
    client = Groq(api_key=api_key)
    print("INIT LOG: Groq raw client initialized.")
    return client


@lru_cache(maxsize=4)
def _build_gemini_client(api_key: str):
    client = genai.Client(api_key=api_key)
    print("INIT LOG: Gemini raw client initialized.")
    return client


def get_groq_client():
    """Raw Groq SDK client, or None if unavailable."""
    groq_key, _ = _load_keys()
    if not groq_key:
        return None
    try:
        return _build_groq_client(groq_key)
    except Exception as e:
        print(f"INIT ERROR: Groq client initialization failed: {str(e)}")
        return None


def get_gemini_client():
    """Raw google.genai client, or None if unavailable."""
    _, gemini_key = _load_keys()
    if not gemini_key:
        return None
    try:
        return _build_gemini_client(gemini_key)
    except Exception as e:
        print(f"INIT ERROR: Gemini client initialization failed: {str(e)}")
        return None


def get_groq_llm():
    """Legacy LangChain Groq model, or None if unavailable."""
    if not has_groq():
        return None
    try:
        return create_chat_model(
            ModelTarget(
                provider="groq",
                model=GROQ_MODEL,
                reasoning_effort=GROQ_REASONING_EFFORT,
            ),
            temperature=GROQ_TEMPERATURE,
        )
    except Exception as e:
        print(f"INIT ERROR: Groq LangChain model initialization failed: {str(e)}")
        return None


def get_gemini_llm():
    """Legacy LangChain Gemini model, or None if unavailable."""
    if not _load_keys()[1]:
        return None
    try:
        return create_chat_model(
            ModelTarget(provider="gemini", model=GEMINI_MODEL),
            temperature=GEMINI_TEMPERATURE,
        )
    except Exception as e:
        print(f"INIT ERROR: Gemini LangChain model initialization failed: {str(e)}")
        return None


def has_groq() -> bool:
    """True when a Groq key is configured."""
    return bool(_load_keys()[0])
