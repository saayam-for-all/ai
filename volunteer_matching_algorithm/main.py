from fastapi import FastAPI, HTTPException
from app.models import VolunteerModel, HelpRequestModel
from app.crud_volunteers import add_volunteer
from app.crud_requests import add_request
from app.matcher import match_volunteers


app = FastAPI()


@app.post("/add_volunteer")
def add_new_volunteer(volunteer: VolunteerModel):
    """Add a new volunteer to the system"""
    try:
        return add_volunteer(volunteer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding volunteer: {str(e)}")


@app.post("/add_request")
def add_new_request(request: HelpRequestModel):
    """Add a new help request to the system"""
    try:
        return add_request(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding request: {str(e)}")


@app.get("/match/{request_id}")
def get_matches(request_id: str, top_k: int = 3):
    """Get top matching volunteers for a request"""
    try:
        matches = match_volunteers(request_id, top_k)

        if matches.empty:
            return {"matches": [], "message": "No active volunteers found or request not found"}

        # Convert to dictionary for JSON response
        return {"matches": matches.to_dict(orient="records")}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error matching volunteers: {str(e)}")