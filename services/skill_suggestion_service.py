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

Token cost. The category list is most of the prompt, so it is written once per
group with a short skill-side hint per leaf, not as a full path plus the
help-request description (those describe a need, and the medical ones run to
several hundred characters of symptom triage). A session also means a repeated
description costs nothing and a new one sends only the new text; see
`suggest_skills_for_session`.

Explanations. Every suggestion says what the volunteer wrote (`evidence`, a
quote checked against the text), what it was matched to (`hierarchy`) and why
(`reason`). Medical consultation categories (5.1.*) are suggested only when
that quote really is in the text.

Privacy: the description and the model's `evidence` quotes are the volunteer's
own words. Neither may reach a log line or an exception message, because
`run_model_chain` logs `str(error)` on every failover. The session carries the
volunteer's text back to the web app; it is never stored server-side.
"""

from __future__ import annotations

import json
import os

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

#: Most suggestions a session returns once several descriptions are merged.
#: A single description still returns at most DEFAULT_MAX_RESULTS.
DEFAULT_MAX_SESSION_RESULTS = 12

#: Descriptions a session remembers. The oldest is dropped beyond this.
MAX_SESSION_ENTRIES = 10

#: Categories whose suggestion must quote the volunteer's own words.
MEDICAL_CONSULTATION_PREFIX = "5.1."

_MAX_EVIDENCE_CHARS = 120
_MAX_REASON_CHARS = 160
_MAX_UNMATCHED_SKILLS = 6
_MAX_UNMATCHED_SKILL_CHARS = 60

#: A few words per leaf, written from the volunteer's side. Leaves whose name
#: already says it (Plumbing, Math) have none. Keys must be leaf IDs; a test
#: keeps this in step with utils/predict_category_list.py.
SKILL_HINTS = {
    "1.1": "food banks, pantries, meal programs",
    "1.2": "shopping for or delivering groceries",
    "1.3.1": "everyday cooking",
    "1.3.2": "cooking for events or large groups",
    "1.3.3": "nutrition, dietitian, balanced diets",
    "1.3.4": "traditional or regional cuisines",
    "2.1": "giving clothes away",
    "2.2": "lending clothes",
    "2.3": "urgent clothing in a crisis",
    "2.4": "sewing, alterations, mending",
    "3.1": "lease agreements, landlord matters",
    "3.2": "tenant rights, rent problems",
    "3.3.2": "small fixes around the home",
    "3.3.4": "woodwork, furniture repair",
    "3.3.5": "gardening, landscaping, yard work",
    "3.3.6": "heating, ventilation, air conditioning",
    "3.3.9": "painting walls or houses",
    "3.4": "setting up internet, power, water",
    "3.5": "finding rentals",
    "3.6": "roommate matching",
    "3.7": "packing, carrying, moving help",
    "3.8": "arranging packers and movers",
    "3.9": "helping buy furniture or home goods",
    "3.10": "helping sell furniture or belongings",
    "4.2": "reviewing essays and personal statements",
    "4.3.2": "English language, literature",
    "4.3.3": "physics, chemistry, biology",
    "4.3.4": "programming, coding",
    "4.3.5": "SAT, GRE, GMAT",
    "4.4": "scholarships, financial aid",
    "4.6": "resumes, interviews, job search, mentoring",
    "4.7": "sharing books, notes, courses",
    "5.1.1": "doctor, nurse, general medical care",
    "5.1.3": "dentist",
    "5.1.4": "optometrist, eye doctor",
    "5.1.5": "cardiology, blood pressure",
    "5.1.6": "physiotherapy, orthopedics, rehab",
    "5.1.8": "gynecology, midwifery",
    "5.1.10": "pediatrician, child health",
    "5.1.11": "other medical professions",
    "5.2": "pharmacy pickup, delivering medicine",
    "5.3": "counselling, emotional support, listening",
    "5.5": "teaching health, hygiene, wellness",
    "6.1": "helping seniors move home",
    "6.2": "phones, tablets, apps, video calls",
    "6.3": "organising medicines (non-clinical)",
    "6.4": "home medical devices",
    "6.5": "errands, rides to events",
    "6.6": "driving people to appointments",
    "6.8": "companionship, visits, calls, walks",
    "6.9": "cooking for dietary needs",
}


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


def _category_lines() -> list[str]:
    """The leaves, one short line each, under a header per parent group.

    `ID | Leaf name: hint`. The shared path is written once in the header
    instead of on every line.
    """
    lines = []
    current_group = None
    for category_id in LEAF_CATEGORY_IDS:
        path = get_category_hierarchy(category_id).split(" > ")
        group = " > ".join(path[:-1])
        if group != current_group:
            lines.append(f"# {group}")
            current_group = group
        line = f"{category_id} | {path[-1]}"
        hint = SKILL_HINTS.get(category_id)
        if hint:
            line = f"{line}: {hint}"
        lines.append(line)
    return lines


def _build_system_prompt() -> str:
    """The fixed instructions and category list.

    Kept identical across requests, and separate from the volunteer's text, so
    provider-side prompt caching can reuse it.
    """
    return "\n".join(
        [
            "Match a volunteer's description of their own skills to the categories below.",
            "The text says what the volunteer can OFFER. It is not a request for help.",
            "Ignore facts that are not skills: age, being retired or a senior, family, location.",
            "Skills may span several areas. Return every category the text supports, and none it does not.",
            "A job title implies that job's everyday skills; match that exact profession, not a neighbouring specialty.",
            "Use only the IDs listed.",
            "",
            "Per match:",
            '"category": the ID',
            '"confidence": 0-1 (0.9+ stated outright, 0.6-0.8 strongly implied, under 0.5 a guess)',
            '"evidence": the phrase from the text, copied word for word',
            '"reason": why it fits, at most 10 words',
            "",
            'Stated skills that fit no category go in "unmatched_skills" as short phrases from the text.',
            "The text may be in any language; evidence stays in that language.",
            "",
            *_category_lines(),
            "",
            'Return JSON only: {"skills": [{"category": "ID", "confidence": 0.9, '
            '"evidence": "phrase", "reason": "why"}], "unmatched_skills": ["phrase"]}',
            'Nothing matches: {"skills": [], "unmatched_skills": []}',
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

    def _suggestion(self, category_id: str, confidence: float, item: dict, text: str) -> dict | None:
        """One suggestion with its explanation, or None if it may not be made.

        `evidence` is kept only if it really is in the volunteer's text, so the
        explanation never shows a quote they did not write. A medical
        consultation category without such a quote is not suggested at all.
        """
        evidence = self._clean_phrase(item.get("evidence"), _MAX_EVIDENCE_CHARS)
        if evidence and not _quote_in_text(evidence, text):
            evidence = None
        if category_id.startswith(MEDICAL_CONSULTATION_PREFIX) and not evidence:
            return None

        hierarchy = get_category_hierarchy(category_id)
        suggestion = {
            "category_number": category_id,
            "category_name": help_categories[category_id],
            "confidence": confidence,
            "hierarchy": hierarchy,
        }
        if evidence:
            suggestion["evidence"] = evidence
        suggestion["explanation"] = {
            "user_said": evidence,
            "matched_to": hierarchy,
            "why": self._clean_phrase(item.get("reason"), _MAX_REASON_CHARS),
        }
        return suggestion

    def _parse_skills(self, response_data: dict, text: str) -> list[dict]:
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

            suggestion = self._suggestion(category_id, confidence, item, text)
            if suggestion:
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
                self._parse_skills(response_data, description),
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


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _quote_in_text(quote: str, text: str) -> bool:
    quote = _normalize_text(quote).strip(" \"'“”‘’.,;:!?")
    return bool(quote) and quote in _normalize_text(text)


def _to_session_skill(suggestion: dict) -> dict:
    """A suggestion in the compact shape the session carries.

    The same shape the model answers in, so a session coming back from the
    client is re-validated by the same parser rather than trusted.
    """
    skill = {
        "category": suggestion["category_number"],
        "confidence": suggestion["confidence"],
    }
    if suggestion.get("evidence"):
        skill["evidence"] = suggestion["evidence"]
    why = suggestion.get("explanation", {}).get("why")
    if why:
        skill["reason"] = why
    return skill


def _read_session(raw, service: SkillSuggestionService) -> list[dict]:
    """The entries of a session the web app sent back, re-validated.

    The client holds the session, so nothing in it is trusted: unknown IDs,
    General, parents, out-of-range confidence and medical suggestions whose
    quote is not in that entry's text are dropped exactly as they would be
    from a model. A malformed session is treated as no session.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        return []
    entries = []
    for entry in raw["entries"][-MAX_SESSION_ENTRIES:]:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()[:MAX_DESCRIPTION_CHARS]
        skills = entry.get("skills")
        entries.append(
            {
                "text": text,
                "categories": service._parse_skills(
                    {"skills": skills if isinstance(skills, list) else []}, text
                ),
                "unmatched_skills": service._parse_unmatched(entry),
            }
        )
    return entries


def suggest_skills_for_session(description: str, session=None, suggest=None) -> dict:
    """Suggest skills for one description within a volunteer's session.

    The session is the free text the volunteer has written so far in this
    sitting, with what was suggested for each piece. It lives in the web app
    and comes back on every call, like `conversation_history` does for
    Generate Answer; nothing is stored server-side.

    It keeps token cost down two ways:

    * a description already in the session (the volunteer pressed Suggest
      again, or went back a step) is answered from it with no model call;
    * a new description is sent to the model on its own, and its suggestions
      are merged with the earlier ones server-side.

    Returns the response body: `categories` (merged, highest confidence
    first), `unmatched_skills`, `token_usage`, `cached`, and the updated
    `session` to send back next time.
    """
    service = SkillSuggestionService()
    suggest = suggest or suggest_skills
    description = (description or "").strip()[:MAX_DESCRIPTION_CHARS]
    entries = _read_session(session, service)

    key = _normalize_text(description)
    cached = any(_normalize_text(entry["text"]) == key for entry in entries)
    if cached:
        usage = token_usage.new_accumulator()
        token_usage.log_usage(
            "suggest_skills", usage, description_chars=len(description), cached=True
        )
    else:
        categories, unmatched, usage = suggest(description)
        entries.append(
            {"text": description, "categories": categories, "unmatched_skills": unmatched}
        )
        entries = entries[-MAX_SESSION_ENTRIES:]

    best_by_id: dict[str, dict] = {}
    for entry in entries:
        for suggestion in entry["categories"]:
            existing = best_by_id.get(suggestion["category_number"])
            if not existing or suggestion["confidence"] > existing["confidence"]:
                best_by_id[suggestion["category_number"]] = suggestion
    max_results = _env_int("SKILL_SUGGESTION_MAX_SESSION_RESULTS", DEFAULT_MAX_SESSION_RESULTS)
    ranked = sorted(best_by_id.values(), key=lambda s: s["confidence"], reverse=True)

    unmatched_skills: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for phrase in entry["unmatched_skills"]:
            if phrase.casefold() not in seen:
                seen.add(phrase.casefold())
                unmatched_skills.append(phrase)

    return {
        "categories": ranked[:max_results],
        "unmatched_skills": unmatched_skills[:max_results],
        "token_usage": usage,
        "cached": cached,
        "session": {
            "entries": [
                {
                    "text": entry["text"],
                    "skills": [_to_session_skill(s) for s in entry["categories"]],
                    "unmatched_skills": entry["unmatched_skills"],
                }
                for entry in entries
            ]
        },
    }
