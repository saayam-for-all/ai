import pandas as pd
import os
from app.id_generator import generate_id

CSV_PATH = "data/requests.csv"

def add_request(req):
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
    else:
        df = pd.DataFrame(columns=[
            "REQ_ID", "RequestCategory", "Location", "RequestType",
            "PriorityLevel", "LeadVolunteerNeeded", "ForSelfOrOthers",
            "IsCalamity", "Subject", "Description", "LanguagePreferred",
            "RequestorId", "Status", "Duration"
        ])

    new_id = generate_id(CSV_PATH, "REQ")

    new_row = { "REQ_ID": new_id, **req.dict() }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)

    return {"message": "Request added", "request_id": new_id}
