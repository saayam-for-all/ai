import pandas as pd

VOL_PATH = "data/volunteers.csv"
REQ_PATH = "data/requests.csv"


def load_volunteers():
    return pd.read_csv(VOL_PATH)


def load_requests():
    return pd.read_csv(REQ_PATH)


def save_volunteers(df):
    df.to_csv(VOL_PATH, index=False)


def save_requests(df):
    df.to_csv(REQ_PATH, index=False)
