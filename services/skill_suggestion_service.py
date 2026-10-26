"""Suggest volunteer skill categories from a free-text description (issue #216).

The Become a Volunteer wizard lets a candidate describe what they are good at
in their own words. This service maps that text to the same category tree that
help requests use, so the web app can pre-select skills in its existing picker.

Why this is not `predict_categories` with a different input: the help-request
classifier is right for a request and wrong for a volunteer profile, in four
ways that issue #216 measured.

  * It walks one branch of the tree, because a request has one category. A
    volunteer usually offers skills in several areas.
  * `is_elderly_context()` forces category 6 on words such as "retired". In a
    request that describes the person who needs help; here it describes the
    volunteer.
  * It can return parents such as `4.3`, and General. The Skills picker only
    accepts leaves, and a General tick tells a matcher nothing.
  * Its prompt classifies a need. Short statements of a profession ("I'm a
    dentist") fell to General.

So this mode makes one call over every selectable leaf, says plainly that the
text is an offer, and validates the answer server-side against the leaf set.

Privacy: the description and the model's `evidence` quotes are the volunteer's
own words. Neither may reach a log line or an exception message, because
`run_model_chain` logs `str(error)` on every failover.
"""

from __future__ import annotations

import json
import os

from utils.categories_with_description import TAXONOMY
from utils.client import client, _use_groq, _gemini_client
from utils.model_fallback import ModelTarget, run_model_chain
from utils.predict_category_list import (
    help_categories,
    category_name_to_number,
    get_direct_children,
    get_category_hierarchy,
)
from utils import token_usage


GENERAL_CATEGORY_ID = "0.0.0.0.0"

#: Longest description sent to the model. The handler trims to this too; the
#: service repeats it so a direct caller cannot send an unbounded prompt.
MAX_DESCRIPTION_CHARS = 2000

DEFAULT_MIN_CONFIDENCE = 0.5
DEFAULT_MAX_RESULTS = 6

_MAX_EVIDENCE_CHARS = 120
_MAX_UNMATCHED_SKILLS = 6
_MAX_UNMATCHED_SKILL_CHARS = 60


def _leaf_category_ids() -> tuple[str, ...]:
    """Every category the Skills picker can select, in taxonomy order."""
    return tuple(
        category_id
        for category_id in help_categories
        if category_id != GENERAL_CATEGORY_ID and not get_direct_children(category_id)
    )


LEAF_CATEGORY_IDS = _leaf_category_ids()
_LEAF_SET = frozenset(LEAF_CATEGORY_IDS)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value > 0 else default


def _provider_error(provider: str, error: Exception) -> ValueError:
    """A failover reason that cannot quote the volunteer's text.

    The Groq SDK puts the whole HTTP response body in its exception message.
    For `json_validate_failed` that body includes `failed_generation`, the
    model's partial output with its evidence quotes, and the model chain logs
    str(error). Keep only what identifies the failure.
    """
    parts = [f"{provider} request failed: {type(error).__name__}"]
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        parts.append(f"status={status_code}")
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        detail = body.get("error", body)
        code = detail.get("code") if isinstance(detail, dict) else None
        if isinstance(code, str) and code.isidentifier():
            parts.append(f"code={code}")
    return ValueError(" ".join(parts))


def _build_system_prompt() -> str:
    """The fixed instructions and category list.

    Kept identical across requests, and separate from the volunteer's text, so
    provider-side prompt caching can reuse it.
    """
    category_lines = []
    for category_id in LEAF_CATEGORY_IDS:
        line = f"{category_id} | {get_category_hierarchy(category_id)}"
        description = TAXONOMY.get(help_categories[category_id], "")
        if description:
            line = f"{line} | {description}"
        category_lines.append(line)

    return "\n".join(
        [
            "You match a volunteer's description of their own skills to the skill categories below.",
            "The text describes what the volunteer can OFFER to other people. It is not a request for help.",
            "Ignore personal facts that are not skills, such as age, being retired or a senior, family or location.",
            "A volunteer may have skills in several unrelated areas. Return every category the text supports, not only the closest one.",
            "Some category descriptions are written from the point of view of a person asking for help. Match the skill that would meet that need: a plumber matches Plumbing, a math teacher matches Math.",
            "A job title implies that job's own everyday skills. Match the category for that exact profession; never pick a different specialty just because it sits in the same area.",
            "Do not guess skills the text does not support.",
            "Choose only from the category IDs listed below. Do not invent IDs or use names.",
            "",
            "For each match give:",
            '- "category": the category ID',
            '- "confidence": 0.0 to 1.0 (0.9-1.0 stated explicitly; 0.6-0.8 strongly implied; below 0.5 a guess)',
            '- "evidence": the short phrase from the text that supports it, copied word for word',
            "",
            'Put skills the volunteer clearly states but that fit none of the categories in "unmatched_skills", as short phrases from the text.',
            "The description may be in any language. Evidence and unmatched skills stay in the description's language.",
            "",
            "Categories (ID | path | description):",
            *category_lines,
            "",
            "Return JSON only, in this format:",
            '{"skills": [{"category": "CATEGORY_ID", "confidence": 0.9, "evidence": "phrase from the text"}], '
            '"unmatched_skills": ["phrase from the text"]}',
            'If nothing matches, return {"skills": [], "unmatched_skills": []}.',
        ]
    )


SYSTEM_PROMPT = _build_system_prompt()


class SkillSuggestionService:
    def __init__(
        self,
        temperature: float = 0.2,
        min_confidence: float | None = None,
        max_results: int | None = None,
    ):
        self.temperature = temperature
        self.min_confidence = (
            _env_float("SKILL_SUGGESTION_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
            if min_confidence is None
            else min_confidence
        )
        self.max_results = (
            _env_int("SKILL_SUGGESTION_MAX_RESULTS", DEFAULT_MAX_RESULTS)
            if max_results is None
            else max_results
        )

    @staticmethod
    def _groq_extra_kwargs(target: ModelTarget) -> dict:
        """Return only the request options configured for this model."""
        if target.reasoning_effort:
            return {"reasoning_effort": target.reasoning_effort}
        return {}

    @staticmethod
    def _user_message(description: str) -> str:
        return f"Volunteer description:\n{description}"

    def _request_json(self, target: ModelTarget, description: str, accumulator: dict) -> dict:
        """Call one configured model and decode its JSON object.

        Error messages name the provider only. They are logged by the model
        chain, and the content they could quote is the volunteer's text.
        """
        if target.provider == "groq":
            if not (_use_groq and client):
                raise ValueError("Groq client not initialized")

            try:
                response = client.chat.completions.create(
                    model=target.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": self._user_message(description)},
                    ],
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                    **self._groq_extra_kwargs(target),
                )
            except Exception as error:
                raise _provider_error(target.provider, error) from None
            token_usage.record(
                accumulator, response, provider=target.provider, model=target.model
            )
            content = response.choices[0].message.content
        elif target.provider == "gemini":
            if not _gemini_client:
                raise ValueError("Gemini client not initialized")

            try:
                response = _gemini_client.models.generate_content(
                    model=target.model,
                    contents=self._user_message(description),
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "response_mime_type": "application/json",
                        "temperature": self.temperature,
                    },
                )
            except Exception as error:
                raise _provider_error(target.provider, error) from None
            token_usage.record(
                accumulator, response, provider=target.provider, model=target.model
            )
            content = response.text
        else:
            raise ValueError(f"Unsupported model provider: {target.provider}")

        if not content or not str(content).strip():
            raise ValueError(f"{target.provider} response content is empty")

        try:
            decoded = json.loads(str(content).strip())
        except json.JSONDecodeError:
            # JSONDecodeError's message quotes the document it failed on.
            raise ValueError(f"{target.provider} response is not valid JSON") from None
        if not isinstance(decoded, dict) or not isinstance(decoded.get("skills"), list):
            raise ValueError(f"{target.provider} response has no skills list")
        return decoded

    @staticmethod
    def _normalize_confidence(value) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        if confidence != confidence:  # NaN
            return 0.0
        return min(max(confidence, 0.0), 1.0)

    @staticmethod
    def _normalize_category_id(category_id) -> str | None:
        """Return a selectable leaf ID, or None.

        General, parents and unknown IDs are dropped here: the Skills picker
        can select leaves only.
        """
        if not isinstance(category_id, str):
            return None
        category_id = category_id.strip()
        if category_id not in _LEAF_SET:
            category_id = category_name_to_number.get(category_id.upper(), "")
        return category_id if category_id in _LEAF_SET else None

    @staticmethod
    def _clean_phrase(value, max_chars: int) -> str | None:
        if not isinstance(value, str):
            return None
        phrase = " ".join(value.split())
        return phrase[:max_chars] if phrase else None

    def _parse_skills(self, response_data: dict) -> list[dict]:
        best_by_id: dict[str, dict] = {}
        for item in response_data.get("skills") or []:
            if not isinstance(item, dict):
                continue
            category_id = self._normalize_category_id(item.get("category"))
            if not category_id:
                continue
            confidence = self._normalize_confidence(item.get("confidence"))
            if confidence < self.min_confidence:
                continue
            existing = best_by_id.get(category_id)
            if existing and existing["confidence"] >= confidence:
                continue

            suggestion = {
                "category_number": category_id,
                "category_name": help_categories[category_id],
                "confidence": confidence,
                "hierarchy": get_category_hierarchy(category_id),
            }
            evidence = self._clean_phrase(item.get("evidence"), _MAX_EVIDENCE_CHARS)
            if evidence:
                suggestion["evidence"] = evidence
            best_by_id[category_id] = suggestion

        # sorted() is stable, so equal confidences keep the model's order.
        ranked = sorted(best_by_id.values(), key=lambda s: s["confidence"], reverse=True)
        return ranked[: self.max_results]

    def _parse_unmatched(self, response_data: dict) -> list[str]:
        raw = response_data.get("unmatched_skills")
        if not isinstance(raw, list):
            return []
        phrases: list[str] = []
        seen: set[str] = set()
        for value in raw:
            phrase = self._clean_phrase(value, _MAX_UNMATCHED_SKILL_CHARS)
            if not phrase or phrase.casefold() in seen:
                continue
            seen.add(phrase.casefold())
            phrases.append(phrase)
            if len(phrases) >= _MAX_UNMATCHED_SKILLS:
                break
        return phrases

    def suggest_skills(self, description: str) -> tuple[list[dict], list[str], dict]:
        """Return (categories, unmatched_skills, token_usage).

        An empty `categories` list is a valid answer - nothing in the text
        matched - and does not fail over. Only a provider error or a malformed
        response moves to the next model; if every model fails,
        `ModelChainExhausted` propagates to the handler.
        """
        description = (description or "").strip()[:MAX_DESCRIPTION_CHARS]
        usage_accumulator = token_usage.new_accumulator()
        try:
            response_data = run_model_chain(
                invoke=lambda target: self._request_json(
                    target, description, usage_accumulator
                ),
                # _request_json has already checked the shape; an empty
                # skills list is a successful "no match".
                is_valid=lambda data: isinstance(data, dict),
                operation="suggest_skills",
            )
            return (
                self._parse_skills(response_data),
                self._parse_unmatched(response_data),
                usage_accumulator,
            )
        finally:
            token_usage.log_usage(
                "suggest_skills",
                usage_accumulator,
                description_chars=len(description),
            )


def suggest_skills(description: str) -> tuple[list[dict], list[str], dict]:
    return SkillSuggestionService().suggest_skills(description)
