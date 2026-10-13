import ast
from pathlib import Path
from timeit import timeit

SOURCE = Path(__file__).parents[3] / "utils" / "categories.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
help_categories = next(
    ast.literal_eval(node.value)
    for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "help_categories" for t in node.targets)
)

def scan_children(parent_id):
    prefix = f"{parent_id}."
    depth = parent_id.count(".")
    return [c for c in help_categories
            if c.startswith(prefix) and c.count(".") == depth + 1]

graph = {}
for category_id in help_categories:
    if "." in category_id:
        parent = category_id.rsplit(".", 1)[0]
        graph.setdefault(parent, []).append(category_id)

parent = "1.1"
scan = scan_children(parent)
direct = graph.get(parent, [])
assert scan == direct

runs = 1000
scan_time = timeit(lambda: scan_children(parent), number=runs)
graph_time = timeit(lambda: graph.get(parent, []), number=runs)

request_edges = [
    ("request", "needs", "6.6"),
    ("request", "needs", "5.2.A.2"),
]

print("Taxonomy entries:", len(help_categories))
print("Children of 1.1:", direct)
print(f"Scan {runs}x: {scan_time:.6f}s")
print(f"Graph {runs}x: {graph_time:.6f}s")
print("Request:", "I need a ride to my doctor’s appointment and help picking up my prescription afterward.")
print("Typed edges:", request_edges)