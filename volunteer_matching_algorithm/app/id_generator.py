import pandas as pd
import os

def generate_id(csv_path, prefix):
    # If file doesn't exist → return prefix_1
    if not os.path.exists(csv_path):
        return f"{prefix}_1"

    df = pd.read_csv(csv_path)

    # If ID column missing → start fresh
    id_col = f"{prefix}_ID"
    if id_col not in df.columns or df.empty:
        return f"{prefix}_1"

    # Get last non-empty ID
    df = df[df[id_col].notna()]
    if df.empty:
        return f"{prefix}_1"

    last_id = df[id_col].iloc[-1]

    # If incorrect format → reset
    if "_" not in last_id:
        return f"{prefix}_1"

    # Extract number
    try:
        number = int(last_id.split("_")[1])
    except:
        number = 0

    return f"{prefix}_{number + 1}"
