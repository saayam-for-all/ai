from fastapi import FastAPI, HTTPException, Query
from app.models import VolunteerModel, HelpRequestModel
from app.crud_volunteers import add_volunteer
from app.crud_requests import add_request
from app.matcher import match_volunteers, match_volunteer_group

app = FastAPI()


@app.post("/volunteers")
def add_new_volunteer(volunteer: VolunteerModel):
    """Add a new volunteer to the system"""
    try:
        return add_volunteer(volunteer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding volunteer: {str(e)}")


@app.post("/requests")
def add_new_request(request: HelpRequestModel):
    """Add a new help request to the system"""
    try:
        return add_request(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding request: {str(e)}")


@app.get("/match/{request_id}")
def get_matches(
        request_id: str,
        top_k: int = Query(3, ge=1, le=10, description="Number of volunteers to return"),
        group: bool = Query(False, description="Set to true if you need a team of volunteers")
):
    """
    Smart volunteer matching - automatically uses the best algorithm.

    Just provide:
    - request_id: Which request needs volunteers (e.g., REQ_1)
    - top_k: How many volunteers you need (default: 3)
    - group: Set to true if you need a coordinated team (default: false)

    The system automatically:
    ✓ Understands the MEANING of requests (not just keywords)
    ✓ Matches "tutoring" with "teaching", "coding" with "programming"
    ✓ Finds volunteers with right skills, languages, and location
    ✓ Returns the BEST matches, sorted by relevance
    """
    try:
        # Auto-select best matching strategy
        if group:
            matches = match_volunteer_group(request_id, group_size=top_k)
        else:
            matches = match_volunteers(request_id, top_k=top_k)

        if matches.empty:
            return {
                "matches": [],
                "count": 0,
                "message": "No suitable volunteers found. Make sure volunteers exist and are 'Active'."
            }

        return {
            "matches": matches.to_dict(orient="records"),
            "count": len(matches),
            "message": f"Found {len(matches)} best volunteer(s) using semantic matching"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error matching volunteers: {str(e)}")


@app.get("/volunteers")
def list_volunteers():
    """List all volunteers in the system"""
    try:
        from app.data_loader import load_volunteers
        volunteers = load_volunteers()
        return {
            "volunteers": volunteers.to_dict(orient="records"),
            "count": len(volunteers)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading volunteers: {str(e)}")


@app.get("/requests")
def list_requests():
    """List all help requests in the system"""
    try:
        from app.data_loader import load_requests
        requests = load_requests()
        return {
            "requests": requests.to_dict(orient="records"),
            "count": len(requests)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading requests: {str(e)}")