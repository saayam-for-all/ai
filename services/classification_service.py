import json
from langchain_core.messages import HumanMessage
from utils.categories_with_description import TAXONOMY
from utils.client import groq_llm, gemini_llm, _use_groq, _use_gemini, GROQ_MODEL, GROQ_TEMPERATURE, GEMINI_MODEL
from utils.categories import category_name_to_number


class GroqClassificationService:
    def __init__(
        self,
        model: str = GROQ_MODEL,
        temperature: float = GROQ_TEMPERATURE,
        top_p: float = 0.3,
        gemini_model: str = GEMINI_MODEL,
    ):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.gemini_model = gemini_model
        self.categories_with_desc = "\n".join(
            [f"{k}: {v}" for k, v in TAXONOMY.items()]
        )

    def _predict_with_gemini(self, prompt: str) -> list:
        if not gemini_llm:
            raise ValueError("Gemini client not initialized")

        resp = gemini_llm.invoke([HumanMessage(content=prompt)])
        text = (resp.content if hasattr(resp, "content") else str(resp)).strip()

        if text.startswith("{"):
            try:
                data = json.loads(text)
                categories = data.get("categories", [])
                if isinstance(categories, list):
                    return categories
                # Fallback: if single category returned
                single_cat = data.get("category")
                if single_cat:
                    return [{"category": single_cat, "confidence": 1.0}]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"LOG: Error parsing Gemini response: {str(e)}")
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

    def predict_categories(self, description: str) -> list:
        # Modified prompt to return ranked categories
        prompt = f"""
You are a zero-shot classifier. 
Return your answer in JSON format with a key 'categories' containing a list of ranked categories.
For each category, include the category name and a confidence score (0.0 to 1.0).
Rank categories by relevance, with the most relevant first.
Return at least the top 3 most relevant categories.

Categories:
{self.categories_with_desc}

Description: {description}

Return format:
{{
  "categories": [
    {{"category": "CATEGORY_NAME", "confidence": 0.95}},
    {{"category": "CATEGORY_NAME", "confidence": 0.80}},
    {{"category": "CATEGORY_NAME", "confidence": 0.65}}
  ]
}}
"""

        if _use_groq and groq_llm:
            try:
                print(f"LOG: Attempting Groq classification with model {self.model}...")
                resp = groq_llm.invoke(
                    [HumanMessage(content=prompt)],
                    response_format={"type": "json_object"},
                )
                res_content = (resp.content if hasattr(resp, "content") else str(resp)).strip()
                res_data = json.loads(res_content)
                return self._parse_ranked_categories(res_data)

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"LOG ERROR: Groq attempt failed: {str(e)}")

        print("LOG: Falling back to Gemini...")
        if _use_gemini and gemini_llm:
            gemini_result = self._predict_with_gemini(prompt)
            if gemini_result:
                return self._parse_ranked_categories({"categories": gemini_result})
        return []


def predict_categories(description):
    service = GroqClassificationService()
    return service.predict_categories(description)