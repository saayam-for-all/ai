# Volunteer-Task Matching

## Overview
It is a simple volunteer-task matching system designed to assign volunteers to tasks based on compatibility across multiple dimensions, such as availability, skills, languages, and location. It uses a rules-based approach to ensure volunteers meet task requirements efficiently. The system is implemented in Python and uses CSV files to store mock data for demonstration purposes.

## Project Goals
- **Match Volunteers to Tasks**: Assign volunteers to tasks based on key attributes like availability, skill levels, language proficiency, and location.
- **Scalable Design**: Provide a foundation that can be extended with more data or advanced matching logic (e.g., machine learning).
- **Ease of Use**: Offer a straightforward setup and execution process for users.

## Project Structure
The project consists of three files:
1. **`volunteers.csv`** - Contains mock data for volunteers, including their attributes.
2. **`task_table.csv`** - Contains mock data for tasks, including their requirements.
3. **`volunteer_match.py`** - Python script that reads the CSV files, performs the matching logic, and outputs the results.

### File Details
- **`volunteers.csv`**:
  - Columns: `id, name, availability_days, availability_frequency, skills, languages, location, preferred_task_type, past_hours, certifications, age`
  - Example: `V001,Alice Smith,"Saturday,Sunday",weekly,"logistics:3,communication:2,tech_support:1","English,Spanish","New York",logistics,50,"First Aid",28`
  - Skills are formatted as `skill:level` (e.g., `logistics:3`), and multi-value fields (e.g., `availability_days`) are comma-separated.

- **`task_table.csv`**:
  - Columns: `id, type, requirements_skills, requirements_languages, location, time_commitment_days, time_commitment_frequency, priority`
  - Example: `T001,logistics,"logistics:2",Spanish,"New York",Saturday,weekly,high`
  - Similar formatting to `volunteers.csv` for skills and multi-value fields.

- **`volunteer_match.py`**:
  - Loads data from both CSV files.
  - Implements matching logic based on availability, location, skills, and languages.
  - Outputs a list of compatible volunteers for each task.

## Prerequisites
- **Python 3.x**: Ensure Python is installed on your system. You can download it from [python.org](https://www.python.org/downloads/).
- No additional libraries are required beyond the standard Python library (`csv` module is used).

## Setup Instructions
1. **Download the Project**:
   - Clone or download this repository to your local machine. You can use the following command if using Git:
     ```
     git clone https://github.com/saayam-for-all/ai.git
     ```
   - Alternatively, download the ZIP file and extract it.

2. **Verify Files**:
   - Ensure the following files are in the same directory:
     - `volunteers.csv`
     - `task_table.csv`
     - `volunteer_match.py`

3. **Check Python Installation**:
   - Open a terminal and run:
     ```
     python --version
     ```
   - If Python is not installed, follow the link above to install it.

## Usage
1. **Navigate to Project Directory**:
   - Open a terminal and change to the directory containing the project files:
     ```
     cd Issue42
     ```

2. **Run the Script**:
   - Execute the Python script:
     ```
     python volunteer_match.py
     ```
   - The script will load the CSV files, match volunteers to tasks, and print the results.

3. **Example Output**:
   ```
   Mock Database Loaded:
   Volunteers: 3 entries
   Tasks: 3 entries

   Matching Volunteers to Tasks:
   Task T001 (logistics): Compatible Volunteers - ['V001']
   Task T002 (tech_support): Compatible Volunteers - ['V002']
   Task T003 (communication): Compatible Volunteers - ['V003']
   ```

## How It Works
- **Data Loading**: The script reads `volunteers.csv` and `task_table.csv`, parsing comma-separated fields and skill levels into usable Python dictionaries.
- **Matching Logic**: For each task, the script checks each volunteer against:
  - **Availability**: Days and frequency must match.
  - **Location**: Must match unless the task is remote.
  - **Skills**: Volunteer must meet or exceed required skill levels.
  - **Languages**: Volunteer must speak at least one required language.
- **Output**: Displays which volunteers are compatible with each task.

## Extending the Project
- **Add More Data**: Edit the CSV files to include additional volunteers or tasks.
- **Enhance Matching**: Modify `volunteer_match.py` to weigh factors like volunteer preferences, past hours, or task priority.
- **Database Integration**: Replace CSV files with a database (e.g., SQLite) for larger datasets.
- **Machine Learning**: Train a model on historical assignment data for smarter matches.

## Troubleshooting
- **File Not Found**: Ensure all three files are in the same directory as the script.
- **CSV Format Issues**: Verify that the CSV files match the expected structure (e.g., no extra commas or missing headers).
- **Python Errors**: Check your Python version and ensure it’s 3.x.

## License
This project is open-source and free to use under the MIT License. Feel free to modify and distribute it as needed.