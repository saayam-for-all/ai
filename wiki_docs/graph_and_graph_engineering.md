# Graphs and Graph Engineering

## 1. Definition

A **graph** is a data structure used to represent entities and the relationships between them.

A graph contains:

- **Nodes** — entities or concepts.
- **Edges** — relationships connecting nodes.
- **Typed edges** — edges that describe what kind of relationship exists, such as `needs`, `related_to`, `followed_by`, or `depends_on`.

Example:

```text
Request --needs--> Transportation
```

`Request` and `Transportation` are nodes, while `needs` is the relationship.

A **tree** is a restricted kind of graph. In a tree, information is mainly organized through parent-child relationships.

```text
Support
└── Transportation
    └── Ride Assistance
```

A general graph is more flexible because a node can connect to multiple other nodes, even when those nodes are in different parts of the taxonomy.

```text
Request
├── needs --> Transportation
└── needs --> Medicine Pickup
```

Graphs do not require a graph database. They can be represented using normal Python structures such as dictionaries and lists. One common representation is an **adjacency list**, where each node stores the nodes connected to it.

---

## 2. Mechanism

Saayam currently stores its taxonomy in `utils/categories.py` using dotted identifiers.

For example:

```text
1       FOOD_AND_ESSENTIALS_SUPPORT
1.1     FOOD_ASSISTANCE
1.1.A   PREFERRED_MEAL_TYPE
1.1.A.1 MEAL_TYPE_VEGETARIAN
```

The hierarchy is encoded inside the identifier itself. For example, `1.1.A` is understood to belong under `1.1`, but that parent-child relationship is not stored separately.

In `utils/predict_category_list.py`, `get_direct_children()` finds children by scanning the taxonomy:

```python
parent_prefix = f"{parent_id}."
parent_depth = parent_id.count(".")

for category_id in help_categories.keys():
    if not category_id.startswith(parent_prefix):
        continue
    if category_id.count(".") == parent_depth + 1:
        children.append(category_id)
```

For every lookup, the function checks category IDs and reconstructs the relationship from the string format.

An explicit graph can build those relationships once:

```python
graph = {}

for category_id in help_categories:
    if "." in category_id:
        parent = category_id.rsplit(".", 1)[0]
        graph.setdefault(parent, []).append(category_id)
```

This creates an in-memory structure such as:

```text
1     -> 1.1
1.1   -> 1.1.A
1.1.A -> 1.1.A.1
```

The graph is not permanently stored in the proof-of-concept. It is created in memory when the script runs.

In a future production implementation, the same structure could be created when Saayam loads its taxonomy configuration and then reused across user requests.

After the graph is built, looking up the children of `1.1` becomes:

```python
graph.get("1.1", [])
```

instead of scanning all category IDs again.

---

## 3. Worked Example

The proof-of-concept is located at:

```text
docs/concepts/examples/graph_taxonomy.py
```

It loads the real Saayam taxonomy from `utils/categories.py` using Python's `ast` module. This avoids importing the Saayam application and allows the example to run without AWS credentials, API keys, or network access.

The taxonomy contained:

```text
717 entries
```

The existing prefix-based lookup and the graph lookup were tested using category:

```text
1.1 = FOOD_ASSISTANCE
```

Both returned:

```text
['1.1.A', '1.1.B', '1.1.C']
```

The script verifies that both methods return the same result.

The repeated lookup test produced:

```text
Scan 1000x:  0.064492s
Graph 1000x: 0.000083s
```

The graph was already built before the timing began. Therefore, this comparison measures repeated lookup cost, not the time required to construct the graph.

The important result is that the current method repeatedly scans the taxonomy, while the graph performs a direct lookup after the relationships have been built once.

### Multi-category example

The second experiment uses this request:

```text
I need a ride to my doctor’s appointment
and help picking up my prescription afterward.
```

This request maps to two real Saayam categories:

```text
6.6
TRANSPORTATION_APPOINTMENTS_EVENTS

5.2.A.2
MEDICINE_DELIVERY_PICKUP_ASSISTANCE
```

Medicine pickup exists under the medicine-delivery branch.

Transportation for appointments and events exists under the elderly/community-support branch.

The graph can represent the request as:

```text
Request
├── needs --> 6.6
└── needs --> 5.2.A.2
```

This is a **cross-category relationship** because one request connects to categories from two different branches of the taxonomy.

Graphs can also represent **non-hierarchical relationships**, where two concepts are related but neither is the parent of the other.

For example:

```text
APARTMENT_ROOM_SEARCH
    --followed_by-->
MOVING_ASSISTANCE
```

Both are existing Saayam categories, but one is not naturally the child of the other. 

A graph can represent relationships such as:

```text
related_to
needs
followed_by
depends_on
may_require
```

without changing the hierarchy.

---

## 4. Finding

The experiment produced a **positive but targeted** result.

Saayam's current dotted-string taxonomy works well for a small hierarchical classification system. With 717 entries, the current implementation is still manageable and does not require a graph purely for performance reasons.

However, the hierarchy is implicit. `get_direct_children()` reconstructs parent-child relationships by scanning category IDs whenever a lookup is performed.

An explicit adjacency graph provides two main benefits.

First, the taxonomy can be converted once into explicit parent-child relationships and then reused for later lookups. This avoids repeatedly deriving the same relationships from dotted strings.

Second, graphs allow Saayam to represent relationships that do not fit naturally into a strict tree. One request can connect to multiple categories, and categories can relate to each other without becoming parent and child.

For example:

```text
Request
├── needs --> Transportation
└── needs --> Medicine Pickup
```

or:

```text
Apartment Search
    --followed_by-->
Moving Assistance
```

This does not mean Saayam currently needs a graph database. A simple in-memory adjacency structure is enough for the demonstrated use case.

The most relevant areas for future work are:

```text
utils/categories.py
utils/predict_category_list.py
```

Future implementation can be considered alongside **issue #160**, which focuses on making the classifier taxonomy configuration-driven.

**Conclusion:** an explicit graph is not currently necessary for Saayam's 717-node hierarchy, but it becomes useful when hierarchy lookups are frequent, the taxonomy grows, or Saayam needs to represent cross-category and non-hierarchical relationships.