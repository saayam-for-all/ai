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
    organization_name: str = Field(description="Name of the nonprofit organization")
    location: str = Field(description="Address of the organization")
    contact: str = Field(description="Phone number of the organization")
    email: str = Field(description="Email address of the organization")
    source: str = Field(description="URL of the organization's website or a reputable source verifying its legitimacy")
    web_url: str = Field(description="URL of the organization's website")
    mission: str = Field(description="A 3-line summary of the organization's mission")
    description: str = Field(description="A 3-line summary of what the organization does")
    relevance: str = Field(description="A 3-line summary of why the organization is relevant to the request")

class NonProfitList(BaseModel):
    organizations: list[Organization] = Field(description="List of 2-3 reputable nonprofit organizations"
    )

parser = JsonOutputParser(pydantic_object=NonProfitList)

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
        groq_api_key=groq_key
    )

# -----------------------------
# 3. Prompt Builder Function
# -----------------------------
def build_prompt(subject: str, description: str, location: str):
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a safety-focused assistant. Provide only reputable, verified nonprofit organizations at the provided address/location: {location}. "
            "Exclude unverified forums, low-trust sites, or questionable sources."
        ),
        (
            "human",
            (
                "Subject: {subject}\n"
                "Description: {description}\n"
                "Location: {location}\n\n"
                "Return a JSON object following this schema:\n"
                "{format_instructions}\n\n"
                "List 2-3 reputable nonprofit organizations that work on the subject and description; priortize organizations which are closest to the provided location"
                "Include organization name, address, phone number, email, source URL of the information, web URL of the organization, mission statement, description of what the organization does, and another 3-line summary of why the organization is relevant to the request."
            )
        )
    ])
    return prompt

# -----------------------------
# 4. Main Function
# -----------------------------
def find_nonprofits(subject: str, description: str, location: str):
    llm = load_llm()
    prompt = build_prompt(subject, description, location)

    chain = prompt | llm | parser
    return chain.invoke({
        "subject": subject,
        "description": description,
        "location": location,
        "format_instructions": parser.get_format_instructions()
    })

# -----------------------------
# 5. Example Usage
# -----------------------------
# if __name__ == "__main__":
#     result = find_nonprofits(
#         subject="shelter",
#         description="i am on the streets now i dont have a place to stay please help",
#         location="tampa"
#     )
#     print(result)