"""More Organizations: the AI half of the Request Details Organizations tab.

This module is called two ways, and both matter:

  * through API Gateway as the "More Organizations" endpoint, and
  * synchronously by the data team's `saayam-org-aggregator` behind
    `v1/ml/orgAggregatorList`, which does `lambda.invoke(...)` and then reads
    `payload["body"]["organizations"]`.

That second caller is the reason `lambda_function._response` must keep `body`
as an object rather than a JSON string, and the reason the field names below
are a contract rather than an implementation detail. See issue #170.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq

# -----------------------------
# 1. JSON Schema Definition
# -----------------------------
class Organization(BaseModel):
    organization_name: str = Field(description="Name of the organization")
    org_type: str = Field(description="Type of organization: 'nonprofit' or 'for-profit'")
    size: str = Field(description="Size of the organization: 'small', 'medium', or 'large'")
    rating: float = Field(description="Rating normalized to a 0.0-5.0 scale with one decimal place (e.g., Charity Navigator 95/100 becomes 4.8). Use 0.0 if not available.")
    location: str = Field(description="Address of the organization")
    contact: str = Field(description="Phone number of the organization")
    email: str = Field(description="Email address of the organization")
    source: str = Field(description="URL of a reputable source verifying the organization's legitimacy")
    web_url: str = Field(description="URL of the organization's website")
    mission: str = Field(description="A 3-line summary of the organization's mission")
    description: str = Field(description="A 3-line summary of what the organization does")
    relevance: str = Field(description="A 3-line summary of why the organization is relevant to the request")
    causes: str = Field(
        default="",
        description="Comma separated cause areas this organization works in, for example 'Housing, Food Security'",
    )


class OrganizationList(BaseModel):
    organizations: list[Organization] = Field(
        description="List of 6 reputable organizations: 3 nonprofit and 3 for-profit"
    )


parser = JsonOutputParser(pydantic_object=OrganizationList)

# The Organizations tab renders these columns, and the ml-api aggregator
# selects a subset of these names out of our rows. Nothing here may be
# dropped or renamed without telling both teams first.
ORGANIZATION_FIELDS = (
    "organization_name",
    "org_type",
    "size",
    "rating",
    "location",
    "contact",
    "email",
    "source",
    "web_url",
    "mission",
    "description",
    "relevance",
    "causes",
)

_SIZES = ("small", "medium", "large")


class OrganizationSearchError(RuntimeError):
    """Every configured provider failed to produce organizations."""


# -----------------------------
# 2. Model Loaders
# -----------------------------
def load_llm():
    """Groq chat model, or None when no Groq key is configured."""
    from utils.client import GROQ_API_KEY, GROQ_MODEL

    if not GROQ_API_KEY:
        return None
    kwargs = dict(model=GROQ_MODEL, temperature=0.1, groq_api_key=GROQ_API_KEY)
    # gpt-oss reasoning models: keep effort low so the JSON output is fast and reliable.
    if "gpt-oss" in GROQ_MODEL:
        kwargs["reasoning_effort"] = "low"
    return ChatGroq(**kwargs)


def load_fallback_llm():
    """Gemini chat model, or None when no Gemini key is configured.

    Answer generation has had a Gemini fallback since the Groq model migration
    in PR #150; organization search did not, so a Groq outage or another
    retired model id took the whole Organizations tab down. It has one now.
    """
    from utils.client import gemini_llm

    return gemini_llm


def _providers():
    """(name, model) pairs to try in order. Groq first, Gemini as fallback."""
    return [
        ("groq", load_llm),
        ("gemini", load_fallback_llm),
    ]


# -----------------------------
# 3. Prompt Builder Function
# -----------------------------
def build_prompt(subject: str, description: str, location: str):
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a safety-focused assistant that helps people find reputable organizations. "
            "Provide only verified, trustworthy organizations at or near the provided location: {location}. "
            "Exclude unverified forums, low-trust sites, or questionable sources. "
            "You must return exactly 3 nonprofit organizations and 3 for-profit organizations (6 total). "
            "For each organization, include its type (nonprofit or for-profit), size (small, medium, or large), "
            "and a rating normalized to a 0.0-5.0 scale with one decimal place (e.g., a Charity Navigator score of 95/100 becomes 4.8; Google/BBB ratings are already on a 5-point scale). Use 0.0 if unavailable."
        ),
        (
            "human",
            (
                "Subject: {subject}\n"
                "Description: {description}\n"
                "Location: {location}\n\n"
                "Return a JSON object following this schema:\n"
                "{format_instructions}\n\n"
                "List exactly 6 reputable organizations related to the subject and description:\n"
                "- 3 nonprofit organizations\n"
                "- 3 for-profit organizations\n\n"
                "Prioritize organizations closest to the provided location.\n"
                "For each organization include: name, org_type (nonprofit or for-profit), "
                "size (small/medium/large based on employee count or operational scale), "
                "rating (normalized to 0.0-5.0 scale, one decimal place; convert Charity Navigator by dividing by 20; use 0.0 if unavailable), "
                "address, phone number, email, source URL, web URL, mission statement, "
                "description of services, a 3-line summary of relevance to this request, "
                "and causes (comma separated cause areas the organization works in)."
            ),
        ),
    ])
    return prompt


# -----------------------------
# 4. Normalisation
# -----------------------------
def _normalize_rating(value):
    """Coerce a rating onto the 0.0-5.0 scale the Organizations tab renders.

    The model is asked for a 5-point scale but sometimes returns the source
    scale it read - a Charity Navigator 95, a percentage - and sometimes a
    string. An out-of-range number in a sortable column is worse than a 0.0,
    because the tab sorts by rating by default.
    """
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return 0.0
    if rating < 0:
        return 0.0
    if rating > 5:
        # 0-100 scales (Charity Navigator, percentages) divide by 20.
        rating = rating / 20 if rating <= 100 else 5.0
    return round(min(rating, 5.0), 1)


def _normalize_size(value):
    text = str(value or "").strip().lower()
    for size in _SIZES:
        if size in text:
            return size
    return ""


def _normalize_org_type(value):
    text = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if "non" in text and "profit" in text:
        return "nonprofit"
    if "profit" in text:
        return "for-profit"
    return ""


def normalize_organization(org, location=None, category=None):
    """Return one organization with every contract field present and sane.

    The aggregator builds a DataFrame from these rows and then selects columns
    by name. A row missing a key becomes a NaN column, or a KeyError in the
    merge, in a different repository. Every field in ORGANIZATION_FIELDS is
    always present.
    """
    org = dict(org or {})
    normalized = {field: org.get(field, "") for field in ORGANIZATION_FIELDS}

    normalized["rating"] = _normalize_rating(org.get("rating"))
    normalized["size"] = _normalize_size(org.get("size"))
    normalized["org_type"] = _normalize_org_type(org.get("org_type"))

    for field in ORGANIZATION_FIELDS:
        if field not in ("rating",) and normalized[field] is None:
            normalized[field] = ""

    if not str(normalized["location"]).strip() and location:
        normalized["location"] = location
    if not str(normalized["causes"]).strip() and category:
        normalized["causes"] = category

    return normalized


def normalize_result(result, location=None, category=None):
    """Coerce a model result into {"organizations": [...]}"""
    if isinstance(result, list):
        organizations = result
    elif isinstance(result, dict):
        organizations = result.get("organizations") or []
    else:
        organizations = []

    return {
        "organizations": [
            normalize_organization(org, location=location, category=category)
            for org in organizations
            if isinstance(org, dict)
        ]
    }


# -----------------------------
# 5. Main Function
# -----------------------------
def _invoke_provider(llm, prompt, subject, description, location):
    """Run one provider's chain. Split out so the fallback loop is testable."""
    chain = prompt | llm | parser
    return chain.invoke({
        "subject": subject,
        "description": description,
        "location": location,
        "format_instructions": parser.get_format_instructions(),
    })



def find_organizations(subject: str, description: str, location: str, category: str | None = None):
    """Return {"organizations": [...]} for the request, trying each provider.

    Raises OrganizationSearchError when every provider fails, so the handler
    can report a real failure instead of an empty success.
    """
    prompt = build_prompt(subject, description, location)
    failures = []

    for name, loader in _providers():
        try:
            llm = loader()
        except Exception as e:
            failures.append(f"{name}: loader failed: {type(e).__name__}: {e}")
            continue

        if llm is None:
            failures.append(f"{name}: not configured")
            continue

        try:
            raw = _invoke_provider(llm, prompt, subject, description, location)
        except Exception as e:
            print(f"WARN: organization search via {name} failed: {type(e).__name__}: {e}")
            failures.append(f"{name}: {type(e).__name__}: {e}")
            continue

        result = normalize_result(raw, location=location, category=category)
        if result["organizations"]:
            print(f"LOG: organization search served by {name}, "
                  f"{len(result['organizations'])} organizations")
            return result

        failures.append(f"{name}: returned no organizations")

    raise OrganizationSearchError("; ".join(failures) or "no provider configured")
