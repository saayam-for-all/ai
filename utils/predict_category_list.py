import json
from pathlib import Path


CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "category_with_desc.json"
)

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    taxonomy = json.load(f)


# File contains all the help categories mapped to their string constants.
help_categories = {
    category_id: details["name"]
    for category_id, details in taxonomy.items()
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
