"""
Organization search service using Gemini's built-in web search (no LangChain).
Outputs a structured list of reputable organizations relevant to the user's need.
"""
from __future__ import annotations

import os
from typing import Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure .env is loaded
load_dotenv()


class OrganizationItem(BaseModel):
    name: str = Field(description="Organization name")
    website: str | None = Field(default=None, description="Primary website URL")
    summary: str = Field(description="Short description of services")
    phone: str | None = Field(default=None, description="Public contact number if available")
    relevance: str = Field(description="Why this org is relevant to the request")


class OrganizationsResponse(BaseModel):
    organizations: list[OrganizationItem] = Field(description="List of recommended organizations")


class GeminiOrganizationSearchService:
    """Use Gemini web search to surface relevant organizations.

    The service asks Gemini to call its google_search tool and to respond
    in JSON for easy consumption by the API layer.
    """

    def __init__(self, model: str = "gemini-2.5-flash"):
        # Import and configure Gemini here to avoid import-time issues
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ValueError("google-genai package not installed. Run: pip install google-genai")
        
        # Get API key from environment
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API is not available. Please set GEMINI_API_KEY in .env file.")
        
        # Configure Gemini client with the API key and keep references to types
        self.client = genai.Client(api_key=api_key)
        self.types = types
        self.model = model

    def _build_prompt(self, subject: str, description: str, location: str | None) -> str:
        """Construct a concise instruction for the model."""
        location_clause = f" for people in {location.strip()}" if location else ""
        return (
            "You are a safety-focused assistant."
            " Recommend reputable, non-profit or official organizations"
            f" that can help with: {description}."
            f" Subject: {subject}."
            f" Prioritize organizations{location_clause}."
            " Return 3-5 results in the JSON schema provided."
            " Exclude unverified forums or low-trust sites."
        )

    def find_organizations(self, subject: str, description: str, location: str | None = None) -> list[dict[str, Any]]:
        """Find organizations using Gemini web search and return structured results."""
        prompt = self._build_prompt(subject, description, location)

        # Ask Gemini to return strict JSON conforming to Pydantic schema
        config = self.types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=OrganizationsResponse.model_json_schema(),
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        text_response = (response.text or "").strip()

        # Validate against schema; raise if invalid so route can return error
        validated = OrganizationsResponse.model_validate_json(text_response)
        return [org.model_dump() for org in validated.organizations]
