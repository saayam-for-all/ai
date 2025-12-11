from pydantic import BaseModel
from typing import Optional

class VolunteerModel(BaseModel):
    VolunteerName: str
    ContactInformation: str
    Location: str
    Skills: str
    LanguagesSpoken: str
    PreferredServiceAreas: str
    Rating: float
    Status: str
    TransportationAvailability: str
    WillingnessToTravel: str


class HelpRequestModel(BaseModel):
    RequestCategory: str
    Location: str
    RequestType: str
    PriorityLevel: str
    LeadVolunteerNeeded: str
    ForSelfOrOthers: str
    IsCalamity: str
    Subject: str
    Description: str
    LanguagePreferred: str
    RequestorId: str
    Status: str
    Duration: int
