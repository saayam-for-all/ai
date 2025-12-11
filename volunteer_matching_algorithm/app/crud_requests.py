import pandas as pd
import os
from app.id_generator import generate_id

CSV_PATH = "data/requests.csv"

def add_request(req):
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
    else:
        # Match exact CSV column names
        df = pd.DataFrame(columns=[
            "RequestId", "RequestCategory", "Location", "RequestType",
            "PriorityLevel", "LeadVolunteerNeeded", "ForSelfOrOthers",
            "IsCalamity", "Subject", "Description", "LanguagePreferred",
            "RequestorId", "Status", "Duration", "AssignedVolunteer", "REQ_ID"
        ])

    new_id = generate_id(CSV_PATH, "REQ")

    # Create new row with proper mapping
    new_row = {
        "RequestId": "",  # Will be auto-generated or can use UUID
        "REQ_ID": new_id,
        "RequestCategory": req.RequestCategory,
        "Location": req.Location,
        "RequestType": req.RequestType,
        "PriorityLevel": req.PriorityLevel,
        "LeadVolunteerNeeded": req.LeadVolunteerNeeded,
        "ForSelfOrOthers": req.ForSelfOrOthers,
        "IsCalamity": req.IsCalamity,
        "Subject": req.Subject,
        "Description": req.Description,
        "LanguagePreferred": req.LanguagePreferred,
        "RequestorId": req.RequestorId,
        "Status": req.Status,
        "Duration": req.Duration,
        "AssignedVolunteer": ""  # Empty initially
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)

    return {"message": "Request added", "request_id": new_id}