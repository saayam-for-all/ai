import json
from utils.categories_with_description import TAXONOMY
from utils.client import client, _use_groq, _gemini_client
from utils.model_fallback import ModelTarget, run_model_chain
from utils.predict_category_list import (
    help_categories,
    category_name_to_number,
    get_top_level_categories,
    get_direct_children,
    get_category_hierarchy,
)
from utils.routing_for_categories import is_elderly_context
from utils import token_usage


class GroqClassificationService:
    def __init__(self, temperature=0.8, top_p=0.3):
        self.temperature = temperature
        self.top_p = top_p

    @staticmethod
    def _groq_extra_kwargs(target: ModelTarget) -> dict:
        """Return only the request options configured for this model."""
        if target.reasoning_effort:
            return {"reasoning_effort": target.reasoning_effort}
        return {}

    def _build_prompt_for_candidates(
        self, description: str, candidates: list[str]
    ) -> str:
        candidate_lines = []
        for category_id in candidates:
            category_name = help_categories.get(category_id, "")
            category_description = TAXONOMY.get(category_name, "")
            if category_description:
                candidate_lines.append(
                    f"{category_id}: {category_name} - {category_description}"
                )
            else:
                candidate_lines.append(f"{category_id}: {category_name}")
        candidates_text = "\n".join(candidate_lines)

        prompt_lines = [
            "You are a classifier. For each category, rate how well the request matches from 0 to 1, then select the best category ID from the list.",
            "Return JSON only with keys category and confidence (0.0 to 1.0).",
            "Confidence bands: 0.9-1.0 explicit match; 0.6-0.8 strong match; 0.3-0.5 weak/ambiguous; <0.3 unsure.",
        ]
        if set(candidates) == set(get_top_level_categories()):
            prompt_lines.append(
                "Routing hint: choose HOUSING_ASSISTANCE for repairs/maintenance (plumber, leak, electrician, handyman); "
                "choose FOOD_AND_ESSENTIALS for food access or groceries; choose CLOTHING_ASSISTANCE for clothes; "
                "choose EDUCATION_CAREER_SUPPORT for tutoring, exams, or school; "
                "choose HEALTHCARE_AND_WELLNESS for medical or health needs; "
                "choose ELDERLY_COMMUNITY_ASSISTANCE for seniors or caregiving; "
                "choose GENERAL_CATEGORY for unclear or uncategorized requests."
            )
        prompt_lines.extend(
            [
                f"Categories:\n{candidates_text}",
                f"Description: {description}",
                'Return format: {"category": "CATEGORY_ID", "confidence": <0.0-1.0>}',
            ]
        )

        return "\n".join(prompt_lines)

    def _build_ranked_prompt_for_candidates(
        self, description: str, candidates: list[str]
    ) -> str:
        candidate_lines = []
        for category_id in candidates:
            category_name = help_categories.get(category_id, "")
            category_description = TAXONOMY.get(category_name, "")
            if category_description:
                candidate_lines.append(
                    f"{category_id}: {category_name} - {category_description}"
                )
            else:
                candidate_lines.append(f"{category_id}: {category_name}")
        candidates_text = "\n".join(candidate_lines)

        prompt_lines = [
            "You are a zero-shot classifier.",
            "Return JSON only with a key 'categories' containing a list of ranked categories.",
            "For each item include the category ID and a confidence score (0.0 to 1.0).",
            "Return at least the top 3 most relevant categories.",
            "Choose only from the category IDs listed below; do not invent IDs or use names.",
        ]
        if set(candidates) == set(get_top_level_categories()):
            prompt_lines.append(
                "Routing hint: choose HOUSING_ASSISTANCE for repairs/maintenance (plumber, leak, electrician, handyman); "
                "choose FOOD_AND_ESSENTIALS for food access or groceries; choose CLOTHING_ASSISTANCE for clothes; "
                "choose EDUCATION_CAREER_SUPPORT for tutoring, exams, or school; "
                "choose HEALTHCARE_AND_WELLNESS for medical or health needs; "
                "choose ELDERLY_COMMUNITY_ASSISTANCE for seniors or caregiving; "
                "choose GENERAL_CATEGORY for unclear or uncategorized requests."
            )
        prompt_lines.extend(
            [
                f"Categories:\n{candidates_text}",
                f"Description: {description}",
                "Return format:",
                "{",
                '  "categories": [',
                '    {"category": "CATEGORY_ID", "confidence": 0.95},',
                '    {"category": "CATEGORY_ID", "confidence": 0.80},',
                '    {"category": "CATEGORY_ID", "confidence": 0.65}',
                "  ]",
                "}",
            ]
        )

        return "\n".join(prompt_lines)

    def _normalize_confidence(self, value) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        if confidence < 0.0:
            return 0.0
        if confidence > 1.0:
            return 1.0
        return confidence

    def _normalize_category_id(
        self, category_id: str | None, candidate_set: set[str]
    ) -> str | None:
        if not category_id:
            return None
        if category_id in candidate_set:
            return category_id
        mapped = category_name_to_number.get(category_id)
        if mapped and mapped in candidate_set:
            return mapped
        return None

    def _request_json(
        self,
        target: ModelTarget,
        prompt: str,
        accumulator: dict,
        depth: int,
    ) -> dict:
        """Call one configured model and decode its classification JSON."""
        if target.provider == "groq":
            if not (_use_groq and client):
                raise ValueError("Groq client not initialized")

            response = client.chat.completions.create(
                model=target.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                top_p=self.top_p,
                response_format={"type": "json_object"},
                **self._groq_extra_kwargs(target),
            )
            token_usage.record(
                accumulator,
                response,
                provider=target.provider,
                model=target.model,
                depth=depth,
            )
            content = response.choices[0].message.content
        elif target.provider == "gemini":
            if not _gemini_client:
                raise ValueError("Gemini client not initialized")

            response = _gemini_client.models.generate_content(
                model=target.model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            token_usage.record(
                accumulator,
                response,
                provider=target.provider,
                model=target.model,
                depth=depth,
            )
            content = response.text
        else:
            raise ValueError(f"Unsupported model provider: {target.provider}")

        if not content or not str(content).strip():
            raise ValueError(f"{target.provider} response content is empty")

        decoded = json.loads(str(content).strip())
        if not isinstance(decoded, dict):
            raise ValueError(f"{target.provider} response must be a JSON object")
        return decoded

    def _predict_single_target(
        self,
        target: ModelTarget,
        prompt: str,
        candidates: set[str],
        accumulator: dict,
        depth: int,
    ) -> dict | None:
        data = self._request_json(target, prompt, accumulator, depth)
        category_id = data.get("category")
        normalized_id = self._normalize_category_id(category_id, candidates)
        if not normalized_id:
            return None
        return {
            "category": normalized_id,
            "confidence": self._normalize_confidence(data.get("confidence")),
        }

    def _predict_ranked_target(
        self,
        target: ModelTarget,
        prompt: str,
        candidates: set[str],
        accumulator: dict,
        depth: int,
    ) -> list[dict]:
        data = self._request_json(target, prompt, accumulator, depth)
        return self._parse_ranked_categories(data, candidates)

    def _parse_ranked_categories(
        self, response_data: dict, candidate_set: set[str]
    ) -> list[dict]:
        categories = response_data.get("categories")
        if not categories and "category" in response_data:
            categories = [
                {
                    "category": response_data.get("category"),
                    "confidence": response_data.get("confidence", 0.0),
                }
            ]

        if not isinstance(categories, list):
            return []

        ranked_results = []
        for item in categories:
            if isinstance(item, dict):
                category_id = item.get("category")
                confidence = self._normalize_confidence(item.get("confidence"))
            elif isinstance(item, str):
                category_id = item
                confidence = 0.0
            else:
                continue

            normalized_id = self._normalize_category_id(category_id, candidate_set)
            if normalized_id:
                ranked_results.append(
                    {"category": normalized_id, "confidence": confidence}
                )

        return ranked_results

    def _predict_one_level(
        self, description: str, candidates: list[str], accumulator: dict, depth: int
    ) -> dict | None:
        if not candidates:
            return None

        prompt = self._build_prompt_for_candidates(description, candidates)
        candidate_set = set(candidates)
        return run_model_chain(
            invoke=lambda target: self._predict_single_target(
                target,
                prompt,
                candidate_set,
                accumulator,
                depth,
            ),
            is_valid=bool,
            operation=f"predict_category.single.depth_{depth}",
        )

    def _predict_ranked_level(
        self, description: str, candidates: list[str], accumulator: dict, depth: int
    ) -> list[dict]:
        if not candidates:
            return []

        prompt = self._build_ranked_prompt_for_candidates(description, candidates)
        candidate_set = set(candidates)
        return run_model_chain(
            invoke=lambda target: self._predict_ranked_target(
                target,
                prompt,
                candidate_set,
                accumulator,
                depth,
            ),
            is_valid=bool,
            operation=f"predict_category.ranked.depth_{depth}",
        )

    def predict_categories(self, description: str) -> tuple:
        """Walk the taxonomy, returning (ranked results, usage).

        The accumulator is built and logged here rather than inside the walk,
        which has four exit points. Classification is the one service whose
        usage is also returned to the caller - `body.token_usage` predates this
        module - so it both logs and returns.
        """
        usage_accumulator = token_usage.new_accumulator()
        try:
            return self._walk_taxonomy(description, usage_accumulator)
        finally:
            token_usage.log_usage(
                "predict_category",
                usage_accumulator,
                description_chars=len(description or ""),
            )

    def _walk_taxonomy(self, description: str, usage_accumulator: dict) -> tuple:
        candidates = get_top_level_categories()
        depth = 0

        if is_elderly_context(description):
            category_id = "6"
            candidates = get_direct_children(category_id)

        while candidates:
            ranked_level = self._predict_ranked_level(description, candidates, accumulator=usage_accumulator, depth=depth)
            if not ranked_level:
                return [], usage_accumulator

            top_choice = ranked_level[0].get("category")
            if not top_choice:
                return [], usage_accumulator

            next_candidates = get_direct_children(top_choice)
            if not next_candidates:
                results = []
                for item in ranked_level:
                    category_id = item.get("category")
                    category_name = help_categories.get(category_id)
                    if not category_name:
                        continue
                    results.append(
                        {
                            "category_number": category_id,
                            "category_name": category_name,
                            "confidence": item.get("confidence", 0.0),
                            "hierarchy": get_category_hierarchy(category_id),
                        }
                    )
                    if len(results) >= 3:
                        break
                return results, usage_accumulator

            candidates = next_candidates
            depth += 1

        return [], usage_accumulator


def predict_categories(description):
    service = GroqClassificationService()
    return service.predict_categories(description)
