from fastapi import FastAPI
from app.models import VolunteerModel, HelpRequestModel
from app.crud_volunteers import add_volunteer
from app.crud_requests import add_request
from app.matcher import match_volunteers

app = FastAPI()


@app.post("/add_volunteer")
def add_new_volunteer(volunteer: VolunteerModel):
    return add_volunteer(volunteer)


@app.post("/add_request")
def add_new_request(request: HelpRequestModel):
    return add_request(request)


@app.get("/match/{request_id}")
def get_matches(request_id: str, top_k: int = 3):
    matches = match_volunteers(request_id, top_k)
    return {"matches": matches.to_dict(orient="records")}
