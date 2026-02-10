"""File contains all the help categories mapped to their display names."""

help_categories = {
    # 0. General
    "0.0.0.0.0": "General",

    # 1. Food & Essentials
    "1": "Food & Essentials",
    "1.1": "Food Assistance",
    "1.2": "Grocery Shopping & Delivery",
    "1.3": "Cooking Help",

    # 2. Clothing Assistance
    "2": "Clothing Assistance",
    "2.1": "Donate Clothes (In-person)",
    "2.2": "Borrow Clothes (In-person)",
    "2.3": "Emergency Clothing Assistance",
    "2.4": "Tailoring or Alteration Assistance",

    # 3. Housing Assistance
    "3": "Housing Assistance",
    "3.1": "Lease Support",
    "3.2": "Tenant Rent Support",
    "3.3": "Repair & Maintenance Support",
    "3.4": "Utilities Setup Support",
    "3.5": "Looking for a rental",
    "3.6": "Find a roommate",
    "3.7": "Move-in Help",
    "3.8": "Packers & Movers Support",
    "3.9": "Buy Used/New things",
    "3.10": "Sell used/new things",

    # 4. Education & Career Support
    "4": "Education & Career Support",
    "4.1": "College Applications Help",
    "4.2": "SOP & Essay Reviews",
    "4.3": "Tutoring",
    "4.4": "Scholarship Knowledge",
    "4.5": "Study Group Formation",
    "4.6": "Career Guidance (Mock Interviews, Referrals)",
    "4.7": "Education Resource Sharing (Book Lending)",

    # 5. Healthcare & Wellness
    "5": "Healthcare & Wellness",
    "5.1": "Medical Consultation",
    "5.2": "Medicine Delivery",
    "5.3": "Medical Well-being Support",
    "5.4": "Medication Reminders",
    "5.5": "Health Education Guidance",

    # 6. Elderly & Community Assistance
    "6": "Elderly & Community Assistance",
    "6.1": "Senior Relocation support",
    "6.2": "Digital Support For Seniors",
    "6.3": "Medication Management and Schedule",
    "6.4": "Medical Devices Setup",
    "6.5": "Errands, Events, and Transportation",
    "6.6": "Transportation support for Appointments, and Events",
    "6.7": "Scheduling of Appointments or Tasks",
    "6.8": "Social Connection",
    "6.9": "Meal Support"
}

# Reverse mapping: category name -> category number
def get_category_number(category_name: str) -> str | None:
    """Get the category number for a given category name."""
    for number, name in help_categories.items():
        if name == category_name:
            return number
    return None

# Create a dictionary for faster lookups
category_name_to_number = {name: number for number, name in help_categories.items()}
