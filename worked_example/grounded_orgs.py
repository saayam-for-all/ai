"""Reference solution for Mission 7."""
SOURCE = {
    "EIN-361/45678": {"name": "Greater Chicago Food Depository", "city": "Chicago",
                      "contact": "773-247-3663", "causes": "Food Security"},
    "EIN-362/99881": {"name": "Access Living", "city": "Chicago",
                      "contact": "312-640-2100", "causes": "Disability, Housing"},
    "EIN-364/10233": {"name": "Rebuilding Together Metro Chicago", "city": "Chicago",
                      "contact": "312-201-1188", "causes": "Home Repair, Accessibility"},
}

def source_record(source_id):
    return SOURCE.get(source_id)

def search(query, location):
    terms = {w[:5] for w in str(query).lower().split() if len(w) > 3}
    hits = []
    for sid, rec in SOURCE.items():
        hay = f"{rec['name']} {rec['causes']}".lower()
        if any(t in hay for t in terms) and str(location).lower() in rec["city"].lower():
            hits.append({"source_id": sid, "name": rec["name"],
                         "contact": rec["contact"], "causes": rec["causes"]})
    return hits
