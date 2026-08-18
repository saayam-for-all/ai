import time
import traceback

import pandas as pd

from app.data_loader import load_requests, load_volunteers
from app.matcher import match_volunteers, match_volunteer_group

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

COLS = [
    "VolunteerName", "Skills", "LanguagesSpoken", "Status",
    "TFIDF_Sim", "BERT_Sim", "SkillMatch", "LanguageMatch",
    "LocationScore", "TextSim", "Rating", "FinalScore",
]

reqs = load_requests()
vols = load_volunteers()

print("=" * 100)
print("DATA SUMMARY")
print("=" * 100)
print(f"requests.csv rows: {len(reqs)}   columns: {list(reqs.columns)}")
print(f"volunteers.csv rows: {len(vols)}")
print(f"REQ_ID non-empty: {(reqs['REQ_ID'].astype(str).str.strip() != '').sum()}")
print(f"VOL_ID non-empty: {(vols['VOL_ID'].astype(str).str.strip() != '').sum()}")
print(f"Volunteer Status counts:\n{vols['Status'].value_counts().to_string()}")
print(f"Active volunteers used by matcher: {(vols['Status'] == 'Active').sum()}")

for rid in ["REQ_1", "REQ_2", "REQ_3", "REQ_4"]:
    print()
    print("=" * 100)
    print(f"REQUEST {rid}")
    print("=" * 100)
    row = reqs[reqs["REQ_ID"] == rid]
    if row.empty:
        print("  NOT FOUND")
        continue
    r = row.iloc[0]
    for f in ["RequestCategory", "Subject", "Description", "LanguagePreferred",
              "RequestType", "PriorityLevel", "Status", "Location"]:
        print(f"  {f}: {r[f]}")

    t0 = time.time()
    res = match_volunteers(rid, top_k=5)
    elapsed = time.time() - t0
    print(f"\n  match_volunteers(top_k=5) -> {len(res)} rows in {elapsed:.1f}s")
    if not res.empty:
        print(res[COLS].round(4).to_string(index=False))

print()
print("=" * 100)
print("GROUP MATCH: match_volunteer_group('REQ_1', group_size=3)")
print("=" * 100)
try:
    t0 = time.time()
    g = match_volunteer_group("REQ_1", group_size=3)
    print(f"returned {len(g)} rows in {time.time() - t0:.1f}s")
    if not g.empty:
        cols = [c for c in COLS + ["GroupRole"] if c in g.columns]
        print(g[cols].round(4).to_string(index=False))
except Exception:
    print("RAISED:")
    traceback.print_exc()

print()
print("=" * 100)
print("EDGE CASE: unknown request id")
print("=" * 100)
try:
    e = match_volunteers("REQ_999", top_k=3)
    print(f"match_volunteers('REQ_999') -> empty={e.empty}, rows={len(e)}")
except Exception:
    traceback.print_exc()
