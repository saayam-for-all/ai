import pandas as pd
import numpy as np

VOL_PATH = "data/volunteers.csv"
REQ_PATH = "data/requests.csv"


def load_volunteers():
    """Load volunteers CSV and clean NaN values"""
    df = pd.read_csv(VOL_PATH)

    # Replace NaN with appropriate defaults for each column type
    string_columns = [
        "VolunteerId", "VolunteerName", "ContactInformation", "Location",
        "Skills", "LanguagesSpoken", "PreferredServiceAreas",
        "Status", "TransportationAvailability", "WillingnessToTravel", "VOL_ID"
    ]

    for col in string_columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    # Handle Rating column (numeric)
    if "Rating" in df.columns:
        df["Rating"] = pd.to_numeric(df["Rating"], errors='coerce').fillna(0)

    return df


def load_requests():
    """Load requests CSV and clean NaN values"""
    df = pd.read_csv(REQ_PATH)

    # Replace NaN with appropriate defaults for each column type
    string_columns = [
        "RequestId", "RequestCategory", "Location", "RequestType",
        "PriorityLevel", "LeadVolunteerNeeded", "ForSelfOrOthers",
        "IsCalamity", "Subject", "Description", "LanguagePreferred",
        "RequestorId", "Status", "AssignedVolunteer", "REQ_ID"
    ]

    for col in string_columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    # Handle Duration column (numeric)
    if "Duration" in df.columns:
        df["Duration"] = pd.to_numeric(df["Duration"], errors='coerce').fillna(0)

    return df


def save_volunteers(df):
    """Save volunteers CSV"""
    df.to_csv(VOL_PATH, index=False)


def save_requests(df):
    """Save requests CSV"""
    df.to_csv(REQ_PATH, index=False)