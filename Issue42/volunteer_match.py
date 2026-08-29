import csv

# Helper functions to parse CSV data
def parse_skills(skill_string):
    if not skill_string:
        return {}
    return {skill.split(":")[0]: int(skill.split(":")[1]) for skill in skill_string.split(",")}

def parse_list(list_string):
    return list_string.split(",") if list_string else []

# Load data from CSV files
def load_volunteers(file_path):
    volunteers = []
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            volunteers.append({
                "id": row["id"],
                "name": row["name"],
                "availability": {
                    "days": parse_list(row["availability_days"]),
                    "frequency": row["availability_frequency"]
                },
                "skills": parse_skills(row["skills"]),
                "languages": parse_list(row["languages"]),
                "location": row["location"],
                "preferred_task_type": row["preferred_task_type"],
                "past_hours": int(row["past_hours"]),
                "certifications": parse_list(row["certifications"]),
                "age": int(row["age"])
            })
    return volunteers

def load_tasks(file_path):
    tasks = []
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            tasks.append({
                "id": row["id"],
                "type": row["type"],
                "requirements": {
                    "skills": parse_skills(row["requirements_skills"]),
                    "languages": parse_list(row["requirements_languages"])
                },
                "location": row["location"],
                "time_commitment": {
                    "days": parse_list(row["time_commitment_days"]),
                    "frequency": row["time_commitment_frequency"]
                },
                "priority": row["priority"]
            })
    return tasks

# Matching Logic
def match_volunteer_to_task(volunteer, task):
    # Check availability compatibility
    v_days = set(volunteer["availability"]["days"])
    t_days = set(task["time_commitment"]["days"])
    if not v_days.intersection(t_days) or volunteer["availability"]["frequency"] != task["time_commitment"]["frequency"]:
        return False
    
    # Check location compatibility
    if task["location"] != "Remote" and volunteer["location"] != task["location"]:
        return False
    
    # Check skill requirements
    for skill, level in task["requirements"]["skills"].items():
        if skill not in volunteer["skills"] or volunteer["skills"][skill] < level:
            return False
    
    # Check language requirements
    v_languages = set(volunteer["languages"])
    t_languages = set(task["requirements"]["languages"])
    if not v_languages.intersection(t_languages):
        return False
    
    return True

# Assign Volunteers to Tasks
def assign_volunteers(volunteers, tasks):
    assignments = {}
    for task in tasks:
        assignments[task["id"]] = []
        for volunteer in volunteers:
            if match_volunteer_to_task(volunteer, task):
                assignments[task["id"]].append(volunteer["id"])
    return assignments

# Main Execution
if __name__ == "__main__":
    # Load data
    volunteers = load_volunteers("volunteers.csv")
    tasks = load_tasks("task_table.csv")
    
    # Print database info
    print("Mock Database Loaded:")
    print(f"Volunteers: {len(volunteers)} entries")
    print(f"Tasks: {len(tasks)} entries")
    print("\nMatching Volunteers to Tasks:")
    
    # Perform matching
    assignments = assign_volunteers(volunteers, tasks)
    for task_id, volunteer_ids in assignments.items():
        task_type = next(t["type"] for t in tasks if t["id"] == task_id)
        print(f"Task {task_id} ({task_type}): Compatible Volunteers - {volunteer_ids if volunteer_ids else 'None'}")