# File contains all the help categories mapped to their string constants.
help_categories = {
    # General (0)
    "0.0.0.0.0": "GENERAL_CATEGORY",
    # Food & Essentials (1)
    "1": "FOOD_AND_ESSENTIALS",
    "1.1": "FOOD_ASSISTANCE",
    "1.2": "GROCERY_SHOPPING_AND_DELIVERY",
    "1.3": "COOKING_HELP",
    "1.3.1": "MEAL_PREP_BASIC",
    "1.3.2": "FESTIVE_OR_BULK_COOKING",
    "1.3.3": "NUTRITIONAL_MEAL_PLANNING",
    "1.3.4": "CULTURAL_CUISINE_GUIDANCE",
    "1.3.5": "OTHER_COOKING_HELP",
    # Clothing (2)
    "2": "CLOTHING_ASSISTANCE",
    "2.1": "DONATE_CLOTHES",
    "2.2": "BORROW_CLOTHES",
    "2.3": "EMERGENCY_CLOTHING_ASSISTANCE",
    "2.4": "TAILORING",
    # Housing (3)
    "3": "HOUSING_ASSISTANCE",
    "3.1": "LEASE_SUPPORT",
    "3.2": "TENANT_RENT_SUPPORT",
    "3.3": "REPAIR_MAINTENANCE_SUPPORT",
    "3.3.1": "PLUMBING",
    "3.3.2": "HANDYMAN",
    "3.3.3": "ELECTRICIAN",
    "3.3.4": "CARPENTRY",
    "3.3.5": "GARDEN",
    "3.3.6": "HVAC_AIR_CONDITIONING",
    "3.3.7": "ROOFING",
    "3.3.8": "LOCKSMITH",
    "3.3.9": "PAINTING",
    "3.3.10": "MASONRY_OR_CONCRETE",
    "3.3.11": "METALWORK_OR_WELDING",
    "3.3.12": "POOL_AND_SPA_MAINTENANCE",
    "3.3.13": "OTHER_REPAIR_MAINTENANCE_SUPPORT",
    "3.4": "UTILITIES_SETUP_SUPPORT",
    "3.5": "LOOKING_FOR_RENTAL",
    "3.6": "FIND_ROOMATE",
    "3.7": "MOVE_IN_HELP",
    "3.8": "BOOKING_PACKERS_MOVERS_SUPPORT",
    "3.9": "BUY_THINGS",
    "3.10": "SELL_THINGS",
    # Education & Career (4)
    "4": "EDUCATION_CAREER_SUPPORT",
    "4.1": "COLLEGE_APPLICATION_HELP",
    "4.2": "SOP_ESSAY_REVIEW",
    "4.3": "TUTORING",
    "4.3.1": "MATH",
    "4.3.2": "ENGLISH",
    "4.3.3": "SCIENCE",
    "4.3.4": "COMPUTER_SCIENCE",
    "4.3.5": "TEST_PREP",
    "4.3.6": "OTHER_SUBJECTS",
    "4.4": "SCHOLARSHIP_KNOWLEDGE",
    "4.5": "STUDY_GROUP_FORMATION",
    "4.6": "CAREER_GUIDANCE",
    "4.7": "EDUCATION_RESOURCE_SHARING",
    # Healthcare & Wellness (5)
    "5": "HEALTHCARE_AND_WELLNESS",
    "5.1": "MEDICAL_CONSULTATION",
    "5.1.1": "GENERAL_CONSULTATION",
    "5.1.2": "ENT(EAR_NOSE_AND_THROAT)",
    "5.1.3": "DENTAL_OR_ORAL_HEALTH",
    "5.1.4": "EYE_OR_VISION_CARE",
    "5.1.5": "CARDIAC_OR_BLOOD_PRESSURE",
    "5.1.6": "ORTHOPEDIC_OR_PHYSIOTHERAPY",
    "5.1.7": "SKIN_OR_DERMATOLOGY",
    "5.1.8": "WOMENS_OR_REPRODUCTIVE_HEALTH",
    "5.1.9": "VACCINATIONS_AND_PREVENTIVE_SCREENINGS",
    "5.1.10": "PEDIATRICS_OR_CHILD_HEALTH",
    "5.1.11": "OTHER_MEDICAL_CONCERN",
    "5.2": "MEDICINE_DELIVERY",
    "5.3": "MENTAL_WELLBEING_SUPPORT",
    "5.4": "MEDICATION_REMINDERS",
    "5.5": "HEALTH_EDUCATION_GUIDANCE",
    # Elderly & Community (6)
    "6": "ELDERLY_COMMUNITY_ASSISTANCE",
    "6.1": "SENIOR_RELOCATION_SUPPORT",
    "6.2": "DIGITAL_SUPPORT_FOR_SENIORS",
    "6.3": "MEDICATION_MANAGEMENT",
    "6.4": "MEDICAL_DEVICES_SETUP",
    "6.5": "ERRANDS_EVENTS_TRANSPORTATION",
    "6.6": "TRANSPORTATION_APPOINTMENTS_EVENTS",
    "6.7": "SCHEDULING_APPOINTMENTS_OR_TASKS",
    "6.8": "SOCIAL_CONNECTION",
    "6.9": "MEAL_SUPPORT",
}


# Reverse mapping: category name -> category number
def get_category_number(category_name: str) -> str | None:
    """Get the category number for a given category name."""
    for number, name in help_categories.items():
        if name == category_name:
            return number
    return None


def get_top_level_categories() -> list[str]:
    """Return top-level category IDs plus the general category."""
    top_level = []
    for category_id in help_categories.keys():
        if category_id == "0.0.0.0.0" or "." not in category_id:
            top_level.append(category_id)
    return top_level


def get_direct_children(parent_id: str) -> list[str]:
    """Return immediate children of the given category ID."""
    children = []
    parent_prefix = f"{parent_id}."
    parent_depth = parent_id.count(".")
    for category_id in help_categories.keys():
        if not category_id.startswith(parent_prefix):
            continue
        if category_id.count(".") == parent_depth + 1:
            children.append(category_id)
    return children


def get_category_hierarchy(category_id: str) -> str:
    """Build a human-readable hierarchy path for a given category ID.

    Example: "4.3.1" -> "Education Career Support > Tutoring > Math"
    """
    parts = category_id.split(".")
    path = []
    for i in range(1, len(parts) + 1):
        ancestor_id = ".".join(parts[:i])
        name = help_categories.get(ancestor_id, "")
        if name:
            path.append(name.replace("_", " ").title())
    return " > ".join(path)


# Create a dictionary for faster lookups
category_name_to_number = {name: number for number, name in help_categories.items()}
