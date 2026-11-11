
import logging
import threading
from functools import lru_cache

from utils.model_fallback import ModelTarget

logger = logging.getLogger(__name__)

GROQ_PARAM = "/dev/saayam/GenAI/groq/key"
GEMINI_PARAM = "/dev/saayam/GenAI/gemini/key"

# Legacy defaults used by the prebuilt LangChain exports.
# Model selection and per-model options are also available through
# config/model_routing.json.
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_TEMPERATURE = 0.3
GROQ_REASONING_EFFORT = "low"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.3

# Credentials are loaded only when an AI client is requested.
GROQ_API_KEY = None
GEMINI_API_KEY = None

_credentials_loaded = False

# Reentrant lock allows initialization functions to call other
# initialization functions safely.
_client_lock = threading.RLock()

# Raw SDK clients used by services/classification_service.py.
client = None
_gemini_client = None

# Legacy prebuilt LangChain models used by answer and subject generation.
groq_llm = None
gemini_llm = None

_use_groq = False
_use_gemini = False


def _load_api_keys():
    """Fetch provider API keys from AWS SSM once, when first needed.

    Importing this module does not create an AWS client or make an SSM call.
    """
    global GROQ_API_KEY
    global GEMINI_API_KEY
    global _credentials_loaded

    with _client_lock:
        if _credentials_loaded:
            return

        # Mark as loaded before making the request so repeated failures do
        # not cause an SSM request on every subsequent invocation.
        _credentials_loaded = True

        try:
            import boto3

            ssm = boto3.client("ssm")
            response = ssm.get_parameters(
                Names=[GROQ_PARAM, GEMINI_PARAM],
                WithDecryption=True,
            )

            params = {
                parameter["Name"]: parameter["Value"]
                for parameter in response.get("Parameters", [])
            }

            missing = [
                name
                for name in (GROQ_PARAM, GEMINI_PARAM)
                if name not in params
            ]

            if missing:
                logger.warning("Parameters not found in SSM: %s", missing)

            GROQ_API_KEY = params.get(GROQ_PARAM)
            GEMINI_API_KEY = params.get(GEMINI_PARAM)

            logger.info(
                "AI credentials loaded. Groq available: %s; Gemini available: %s",
                bool(GROQ_API_KEY),
                bool(GEMINI_API_KEY),
            )

        except Exception:
            logger.exception("Failed to fetch AI credentials from AWS SSM")
            GROQ_API_KEY = None
            GEMINI_API_KEY = None


@lru_cache(maxsize=32)
def _create_chat_model_cached(
    provider: str,
    model: str,
    reasoning_effort: str | None,
    temperature: float,
):
    """Build and cache a LangChain model for a specific configuration.

    The primitive arguments form a stable cache key, so different model
    targets, reasoning settings, or temperatures get separate instances.
    Failed constructions are not cached by functools.lru_cache.
    """
    _load_api_keys()

    with _client_lock:
        if provider == "groq":
            if not GROQ_API_KEY:
                raise ValueError("Groq API key is not configured")

            from langchain_groq import ChatGroq

            kwargs = {
                "api_key": GROQ_API_KEY,
                "model": model,
                "temperature": temperature,
            }

            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

            return ChatGroq(**kwargs)

        if provider == "gemini":
            if not GEMINI_API_KEY:
                raise ValueError("Gemini API key is not configured")

            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                google_api_key=GEMINI_API_KEY,
                model=model,
                temperature=temperature,
            )

        raise ValueError(f"Unsupported model provider: {provider}")


def create_chat_model(target: ModelTarget, *, temperature: float):
    """Construct or reuse a LangChain chat model for the selected provider.

    Credentials and provider libraries are loaded only when this function
    is called. Model selection and fallback order remain the responsibility
    of model_routing.json and run_model_chain.
    """
    with _client_lock:
        return _create_chat_model_cached(
            provider=target.provider,
            model=target.model,
            reasoning_effort=target.reasoning_effort,
            temperature=temperature,
        )


def get_groq_client():
    """Return the memoized raw Groq SDK client, initializing it on demand."""
    global client
    global _use_groq

    with _client_lock:
        if client is not None:
            return client

        _load_api_keys()

        if not GROQ_API_KEY:
            logger.warning("Groq API key is not configured")
            return None

        try:
            from groq import Groq

            client = Groq(api_key=GROQ_API_KEY)
            _use_groq = True

            logger.info("Groq raw SDK client initialized")
            return client

        except Exception:
            logger.exception("Failed to initialize Groq raw SDK client")
            client = None
            _use_groq = False
            return None


def get_gemini_client():
    """Return the memoized raw Gemini SDK client, initializing it on demand."""
    global _gemini_client
    global _use_gemini

    with _client_lock:
        if _gemini_client is not None:
            return _gemini_client

        _load_api_keys()

        if not GEMINI_API_KEY:
            logger.warning("Gemini API key is not configured")
            return None

        try:
            from google import genai

            _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            _use_gemini = True

            logger.info("Gemini raw SDK client initialized")
            return _gemini_client

        except Exception:
            logger.exception("Failed to initialize Gemini raw SDK client")
            _gemini_client = None
            _use_gemini = False
            return None


def get_groq_llm():
    """Return the memoized LangChain Groq model, initializing it on demand."""
    global groq_llm
    global _use_groq

    with _client_lock:
        if groq_llm is not None:
            return groq_llm

        _load_api_keys()

        if not GROQ_API_KEY:
            logger.warning("Groq API key is not configured")
            return None

        try:
            groq_llm = create_chat_model(
                ModelTarget(
                    provider="groq",
                    model=GROQ_MODEL,
                    reasoning_effort=GROQ_REASONING_EFFORT,
                ),
                temperature=GROQ_TEMPERATURE,
            )

            _use_groq = True
            logger.info("Groq LangChain model initialized")
            return groq_llm

        except Exception:
            logger.exception("Failed to initialize Groq LangChain model")
            groq_llm = None
            _use_groq = False
            return None


def get_gemini_llm():
    """Return the memoized LangChain Gemini model, initializing it on demand."""
    global gemini_llm
    global _use_gemini

    with _client_lock:
        if gemini_llm is not None:
            return gemini_llm

        _load_api_keys()

        if not GEMINI_API_KEY:
            logger.warning("Gemini API key is not configured")
            return None

        try:
            gemini_llm = create_chat_model(
                ModelTarget(
                    provider="gemini",
                    model=GEMINI_MODEL,
                ),
                temperature=GEMINI_TEMPERATURE,
            )

            _use_gemini = True
            logger.info("Gemini LangChain model initialized")
            return gemini_llm

        except Exception:
            logger.exception("Failed to initialize Gemini LangChain model")
            gemini_llm = None
            _use_gemini = False
            return None


def is_groq_enabled() -> bool:
    """Check whether the Groq raw SDK client can be initialized."""
    return get_groq_client() is not None


def is_gemini_enabled() -> bool:
    """Check whether the Gemini raw SDK client can be initialized."""
    return get_gemini_client() is not None


def has_any_llm() -> bool:
    """Return whether at least one LangChain provider model is available."""
    return get_groq_llm() is not None or get_gemini_llm() is not None
