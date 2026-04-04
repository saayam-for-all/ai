import os
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq

load_dotenv()

# -----------------------------
# 1. JSON Schema Definition
# -----------------------------
class Organization(BaseModel):
    organization_name: str = Field(description="Name of the organization")
    org_type: str = Field(description="Type of organization: 'nonprofit' or 'for-profit'")
    size: str = Field(description="Size of the organization: 'small', 'medium', or 'large'")
    rating: str = Field(description="Rating or reputation score of the organization (e.g., Charity Navigator rating for nonprofits, Google/BBB rating for for-profits). Use 'N/A' if not available.")
    location: str = Field(description="Address of the organization")
    contact: str = Field(description="Phone number of the organization")
    email: str = Field(description="Email address of the organization")
    source: str = Field(description="URL of a reputable source verifying the organization's legitimacy")
    web_url: str = Field(description="URL of the organization's website")
    mission: str = Field(description="A 3-line summary of the organization's mission")
    description: str = Field(description="A 3-line summary of what the organization does")
    relevance: str = Field(description="A 3-line summary of why the organization is relevant to the request")


class OrganizationList(BaseModel):
    organizations: list[Organization] = Field(
        description="List of 6 reputable organizations: 3 nonprofit and 3 for-profit"
    )


parser = JsonOutputParser(pydantic_object=OrganizationList)

# -----------------------------
# 2. Model Loader
# -----------------------------
def load_llm():
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("Missing GROQ_API_KEY in environment variables.")
    print("Using Groq model")
    return ChatGroq(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.1,
        groq_api_key=groq_key,
    )

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
            "and a rating (Charity Navigator score for nonprofits, Google or BBB rating for for-profits; use 'N/A' if unavailable)."
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
                "rating (Charity Navigator for nonprofits, Google/BBB for for-profits, or N/A), "
                "address, phone number, email, source URL, web URL, mission statement, "
                "description of services, and a 3-line summary of relevance to this request."
            ),
        ),
    ])
    return prompt

# -----------------------------
# 4. Main Function
# -----------------------------
def find_organizations(subject: str, description: str, location: str):
    llm = load_llm()
    prompt = build_prompt(subject, description, location)
    chain = prompt | llm | parser
    return chain.invoke({
        "subject": subject,
        "description": description,
        "location": location,
        "format_instructions": parser.get_format_instructions(),
    })

# -----------------------------
# 5. Example Usage
# -----------------------------
# if __name__ == "__main__":
#     result = find_organizations(
#         subject="shelter",
#         description="i am on the streets now i dont have a place to stay please help",
#         location="tampa"
#     )
#     print(result)
