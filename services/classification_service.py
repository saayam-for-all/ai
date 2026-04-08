import json
from langchain_core.messages import HumanMessage
from utils.categories_with_description import TAXONOMY
from utils.categories import (
    help_categories,
    category_name_to_number,
    get_top_level_categories,
    get_direct_children,
)
from utils.routing_for_categories import is_elderly_context

from utils.client import groq_llm, gemini_llm, _use_groq, _use_gemini


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
        if not gemini_llm:
            raise ValueError("Gemini client not initialized")

        response = gemini_llm.invoke([HumanMessage(content=prompt)])
        text = response.content if hasattr(response, "content") else str(response)
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
        return []

    def _parse_ranked_categories(self, response_data: dict) -> list:
        """Parse the response and return ranked categories with numbers."""
        categories = response_data.get("categories", [])

        # If single category format, convert to list
        if "category" in response_data and not categories:
            single_cat = response_data.get("category")
            if single_cat:
                categories = [{"category": single_cat, "confidence": 1.0}]

        # Map category names to numbers and sort by confidence
        ranked_results = []
        for item in categories:
            if isinstance(item, dict):
                cat_name = item.get("category", "")
                confidence = item.get("confidence", 0.0)
            elif isinstance(item, str):
                cat_name = item
                confidence = 1.0
            else:
                continue

            cat_number = category_name_to_number.get(cat_name)
            if cat_number:
                ranked_results.append({
                    "category_number": cat_number,
                    "category_name": cat_name,
                    "confidence": confidence
                })

        # Sort by confidence (highest first)
        ranked_results.sort(key=lambda x: x["confidence"], reverse=True)
        return ranked_results

    def _predict_one_level(
        self, description: str, candidates: list[str]
    ) -> dict | None:
        if not candidates:
            return None

        prompt = self._build_prompt_for_candidates(description, candidates)
        candidate_set = set(candidates)

        if _use_groq and groq_llm:
            res_content = None
            try:
                print(f"LOG: Attempting Groq classification with model {self.model}...")
                response = groq_llm.invoke(
                    [HumanMessage(content=prompt)],
                    response_format={"type": "json_object"},
                )
                message_content = (
                    response.content if hasattr(response, "content") else str(response)
                )
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
                if res_content:
                    print(f"LOG ERROR: Groq raw response: {res_content}")

        print("LOG: Falling back to Gemini...")
        return self._predict_with_gemini_single(prompt, candidate_set)

    def predict_categories(self, description: str) -> list:
        selected_path = []
        candidates = get_top_level_categories()

        if is_elderly_context(description):
            category_id = "6"
            category_name = help_categories.get(category_id)
            if category_name:
                selected_path.append(
                    {
                        "category_number": category_id,
                        "category_name": category_name,
                        "confidence": 1.0,
                    }
                )
                candidates = get_direct_children(category_id)
            else:
                candidates = []

        while candidates:
            result = self._predict_one_level(description, candidates)
            if not result:
                break

            category_id = result.get("category")
            if not category_id:
                break

            category_name = help_categories.get(category_id)
            if not category_name:
                break

            selected_path.append(
                {
                    "category_number": category_id,
                    "category_name": category_name,
                    "confidence": result.get("confidence", 0.0),
                }
            )

            candidates = get_direct_children(category_id)

        # Return only the deepest leaf category from the selected path.
        leaf_categories = [
            item
            for item in selected_path
            if not get_direct_children(item["category_number"])
        ]
        if leaf_categories:
            return [leaf_categories[-1]]
        return []


def predict_categories(description):
    service = GroqClassificationService()
    return service.predict_categories(description)
