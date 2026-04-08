import json
from utils.categories_with_description import TAXONOMY
from utils.client import client, _use_groq, _gemini_client
from utils.categories import (
    help_categories,
    category_name_to_number,
    get_top_level_categories,
    get_direct_children,
)
from utils.routing_for_categories import is_elderly_context


class GroqClassificationService:
    def __init__(self, model="llama-3.1-8b-instant", temperature=0.8, top_p=0.3):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.gemini_model = "gemini-2.0-flash"

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

    def _predict_with_gemini_single(
        self, prompt: str, candidates: set[str]
    ) -> dict | None:
        if not _gemini_client:
            raise ValueError("Gemini client not initialized")

        response = _gemini_client.models.generate_content(
            model=self.gemini_model, contents=prompt
        )
        text = response.text
        if not text:
            return None
        text = text.strip()
        if text.startswith("{"):
            try:
                data = json.loads(text)
                category_id = data.get("category")
                normalized_id = self._normalize_category_id(category_id, candidates)
                if normalized_id:
                    confidence = self._normalize_confidence(data.get("confidence"))
                    return {"category": normalized_id, "confidence": confidence}
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"LOG: Error parsing Gemini response: {str(e)}")
        return None

    def _predict_with_gemini_ranked(
        self, prompt: str, candidates: set[str]
    ) -> list[dict]:
        if not _gemini_client:
            raise ValueError("Gemini client not initialized")

        response = _gemini_client.models.generate_content(
            model=self.gemini_model, contents=prompt
        )
        text = response.text
        if not text:
            return []
        text = text.strip()
        if text.startswith("{"):
            try:
                data = json.loads(text)
                return self._parse_ranked_categories(data, candidates)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"LOG: Error parsing Gemini response: {str(e)}")
        return []

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
        self, description: str, candidates: list[str]
    ) -> dict | None:
        if not candidates:
            return None

        prompt = self._build_prompt_for_candidates(description, candidates)
        candidate_set = set(candidates)

        if _use_groq and client:
            res_content = None
            try:
                print(f"LOG: Attempting Groq classification with model {self.model}...")
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    top_p=self.top_p,
                    response_format={"type": "json_object"},
                )
                message_content = response.choices[0].message.content
                if not message_content:
                    raise ValueError("Groq response content is empty")
                res_content = message_content.strip()
                res_data = json.loads(res_content)
                category_id = res_data.get("category")
                normalized_id = self._normalize_category_id(category_id, candidate_set)
                if normalized_id:
                    confidence = self._normalize_confidence(res_data.get("confidence"))
                    return {"category": normalized_id, "confidence": confidence}
                print(
                    f"LOG ERROR: Groq returned invalid category: {category_id}. Raw={res_content}"
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                print(f"LOG ERROR: Groq attempt failed: {str(e)}")

        print("LOG: Falling back to Gemini...")
        return self._predict_with_gemini_single(prompt, candidate_set)

    def _predict_ranked_level(
        self, description: str, candidates: list[str]
    ) -> list[dict]:
        if not candidates:
            return []

        prompt = self._build_ranked_prompt_for_candidates(description, candidates)
        candidate_set = set(candidates)

        if _use_groq and client:
            res_content = None
            try:
                print(f"LOG: Attempting Groq classification with model {self.model}...")
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    top_p=self.top_p,
                    response_format={"type": "json_object"},
                )
                res_content = response.choices[0].message.content
                if not res_content:
                    raise ValueError("Groq response content is empty")
                res_data = json.loads(res_content)
                ranked_results = self._parse_ranked_categories(res_data, candidate_set)
                if ranked_results:
                    return ranked_results
                print(
                    "LOG ERROR: Groq ranked response yielded no valid categories. "
                    f"Candidates={len(candidate_set)}"
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                print(f"LOG ERROR: Groq attempt failed: {str(e)}")

        print("LOG: Falling back to Gemini...")
        return self._predict_with_gemini_ranked(prompt, candidate_set)

    def predict_categories(self, description: str) -> list:
        candidates = get_top_level_categories()

        if is_elderly_context(description):
            category_id = "6"
            candidates = get_direct_children(category_id)

        while candidates:
            ranked_level = self._predict_ranked_level(description, candidates)
            if not ranked_level:
                return []

            top_choice = ranked_level[0].get("category")
            if not top_choice:
                return []

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
                        }
                    )
                    if len(results) >= 3:
                        break
                return results

            candidates = next_candidates

        return []


def predict_categories(description):
    service = GroqClassificationService()
    return service.predict_categories(description)
