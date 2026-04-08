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

    def _collect_leaf_candidates(self, root_id: str | None = None) -> list[str]:
        leaf_ids = []
        for category_id in help_categories.keys():
            if root_id:
                if category_id != root_id and not category_id.startswith(f"{root_id}."):
                    continue
            if not get_direct_children(category_id):
                leaf_ids.append(category_id)
        return leaf_ids

    def _build_prompt_for_top_k_leaves(
        self, description: str, leaf_candidates: list[str], top_k: int
    ) -> str:
        candidate_lines = []
        for category_id in leaf_candidates:
            category_name = help_categories.get(category_id, "")
            category_description = TAXONOMY.get(category_name, "")
            if category_description:
                candidate_lines.append(
                    f"{category_id}: {category_name} - {category_description}"
                )
            else:
                candidate_lines.append(f"{category_id}: {category_name}")

        return "\n".join(
            [
                "You are a classifier. Select the best matching leaf categories for the request.",
                f"Return JSON only as: {{\"categories\": [{{\"category\": \"CATEGORY_ID\", \"confidence\": 0.0}}]}} with up to {top_k} items.",
                "Rules: only choose from the provided IDs, no duplicates, confidence must be between 0.0 and 1.0, sorted highest confidence first.",
                f"Leaf categories:\n{chr(10).join(candidate_lines)}",
                f"Description: {description}",
            ]
        )

    def _normalize_top_k_response(
        self, response_data: dict, candidate_set: set[str], top_k: int
    ) -> list[dict]:
        raw_items = response_data.get("categories", [])
        normalized = []
        seen = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            category_id = self._normalize_category_id(item.get("category"), candidate_set)
            if not category_id or category_id in seen:
                continue
            normalized.append(
                {
                    "category": category_id,
                    "confidence": self._normalize_confidence(item.get("confidence")),
                }
            )
            seen.add(category_id)
            if len(normalized) >= top_k:
                break
        normalized.sort(key=lambda x: x["confidence"], reverse=True)
        return normalized

    def _predict_top_leaf_categories(self, description: str, top_k: int = 3) -> list[dict]:
        root_id = "6" if is_elderly_context(description) else None
        leaf_candidates = self._collect_leaf_candidates(root_id)
        if not leaf_candidates:
            return []

        prompt = self._build_prompt_for_top_k_leaves(description, leaf_candidates, top_k)
        candidate_set = set(leaf_candidates)

        if _use_groq and groq_llm:
            try:
                response = groq_llm.invoke(
                    [HumanMessage(content=prompt)],
                    response_format={"type": "json_object"},
                )
                text = response.content if hasattr(response, "content") else str(response)
                if text:
                    parsed = json.loads(text.strip())
                    normalized = self._normalize_top_k_response(
                        parsed, candidate_set, top_k
                    )
                    if normalized:
                        return normalized
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                print(f"LOG ERROR: Groq top-k attempt failed: {str(e)}")

        if _use_gemini and gemini_llm:
            try:
                response = gemini_llm.invoke([HumanMessage(content=prompt)])
                text = response.content if hasattr(response, "content") else str(response)
                if text:
                    parsed = json.loads(text.strip())
                    return self._normalize_top_k_response(parsed, candidate_set, top_k)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                print(f"LOG ERROR: Gemini top-k attempt failed: {str(e)}")
        return []

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
        top_leaf_results = self._predict_top_leaf_categories(description, top_k=3)
        formatted = []
        for item in top_leaf_results:
            category_id = item.get("category")
            category_name = help_categories.get(category_id)
            if not category_name:
                continue
            formatted.append(
                {
                    "category_number": category_id,
                    "category_name": category_name,
                    "confidence": item.get("confidence", 0.0),
                }
            )
        return formatted


def predict_categories(description):
    service = GroqClassificationService()
    return service.predict_categories(description)
