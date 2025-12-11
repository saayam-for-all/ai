import pandas as pd
import os
from app.id_generator import generate_id

CSV_PATH = "data/volunteers.csv"

def add_volunteer(volunteer):
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
    else:
        df = pd.DataFrame(columns=[
            "VOL_ID", "VolunteerName", "ContactInformation", "Location",
            "Skills", "LanguagesSpoken", "PreferredServiceAreas",
            "Rating", "Status", "TransportationAvailability", "WillingnessToTravel"
        ])

    new_id = generate_id(CSV_PATH, "VOL")

    new_row = {
        "VOL_ID": new_id,
        "VolunteerName": volunteer.VolunteerName,
        "ContactInformation": volunteer.ContactInformation,
        "Location": volunteer.Location,
        "Skills": volunteer.Skills,
        "LanguagesSpoken": volunteer.LanguagesSpoken,
        "PreferredServiceAreas": volunteer.PreferredServiceAreas,
        "Rating": volunteer.Rating,
        "Status": volunteer.Status,
        "TransportationAvailability": volunteer.TransportationAvailability,
        "WillingnessToTravel": volunteer.WillingnessToTravel
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)

    return {"message": "Volunteer added", "volunteer_id": new_id}
