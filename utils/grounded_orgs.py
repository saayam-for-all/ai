"""Grounded organization retrieval: retrieve, ground, cite (issue #197, stack 3).

Why this module exists
----------------------
``utils/search_orgs.py`` asks a language model for six "verified" organizations,
each with a size and a 0.0-5.0 rating, written from the model's memory. Nothing
checks those organizations against anything, and the Organizations tab sorts by
the rating.

This module answers the same question the other way round. It returns only
organizations that a person has verified and committed to
``services/organizations.json``, with a source URL behind every claim, and it
returns nothing when nothing matches. No model is called, so the result is
deterministic and instant, and it cannot have a provider outage. These are the
rules ``docs/emergency_numbers_provenance.md`` sets for the emergency numbers,
applied to organizations (see ``docs/organizations_provenance.md``).

How it works
------------
1. ``load_records`` reads the dataset and drops every record that fails
   ``problems`` (unverified, or a claim with no source). Unverified data is
   never served, however well it matches.
2. ``Taxonomy`` turns the classifier's dotted category IDs ("4.3.1") into a
   graph, so a request for "plumbing" can also reach an organization that
   serves the broader "repair and maintenance" area. A flat exact-match lookup
   cannot do that.
3. ``find_organizations_grounded`` scores records against the request, filters
   by location, and returns rows in the same shape as
   ``utils.search_orgs.find_organizations`` plus a ``grounding`` block that says
   where each row came from.
4. ``audit`` checks organizations from any other source (for example the model)
   against the verified records.

Run it by hand (from the repo root):
    python -m utils.grounded_orgs --demo        # six sample requests, printed readably
    python -m utils.grounded_orgs "shelter" "I need a place to stay" "Chicago, IL" HOUSING_ASSISTANCE
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

from utils import search_orgs as SO

#: The shipped dataset. For now PROXY data (made-up, labelled "(proxy data)"), as
#: agreed for this experiment; real records must be verified by a person.
DATA_PATH = Path(__file__).resolve().parent.parent / "services" / "organizations.json"

#: Contract fields that make a claim about the world. A non-empty value in any
#: of these must have a source URL, because a claim nobody can check is exactly
#: what this module exists to avoid.
CLAIM_FIELDS = (
    "organization_name", "org_type", "size", "rating", "location",
    "contact", "email", "web_url", "mission", "description",
)

#: Scores for how a record's category relates to the category requested.
#: An exact match beats a broader one, which beats a narrower one, which beats
#: a bare keyword hit.
SCORES = {"exact": 1.0, "broader": 0.6, "narrower": 0.5, "keyword": 0.4}

#: The handler sends "United States" when the caller gave no location, so that
#: value (and an empty one) means "unknown", not "somewhere in the US only".
_UNSPECIFIED_LOCATIONS = {"", "united states", "united states of america", "usa", "us"}
_NATIONAL_AREAS = _UNSPECIFIED_LOCATIONS | {"national"}

#: Words ignored when matching a category name against free text.
_STOPWORDS = {"and", "or", "of", "for", "the", "a", "an", "to", "in", "with",
              "other", "support", "assistance", "help", "general"}


# ---------------------------------------------------------------------------
# The dataset and its rules
# ---------------------------------------------------------------------------

def problems(record):
    """Return what is wrong with a dataset record; an empty list means servable.

    The rules mirror ``docs/organizations_provenance.md``: a record needs an id,
    a name, the taxonomy categories it serves, a named verifier and date, and a
    source URL for every claim it makes. Blank values make no claim, so a
    record may leave ``rating`` at 0.0 or ``size`` empty without a source.
    """
    if not isinstance(record, dict):
        return ["record is not an object"]
    found = []
    for key in ("source_id", "organization_name", "verified_by"):
        if not str(record.get(key) or "").strip():
            found.append(f"missing {key}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(record.get("verified_on") or "")):
        found.append("verified_on must be a YYYY-MM-DD date")
    categories = record.get("categories")
    if not isinstance(categories, list) or not categories:
        found.append("categories must be a non-empty list of taxonomy IDs")
    sources = record.get("sources")
    if not isinstance(sources, dict):
        sources, found = {}, found + ["sources must be an object"]
    for field in CLAIM_FIELDS:
        value = record.get(field)
        if value in (None, "", 0, 0.0):
            continue  # nothing claimed, nothing to source
        if not str(sources.get(field) or "").startswith("https://"):
            found.append(f"{field} has no https source")
    return found


def load_records(path=None):
    """Read the dataset and return only the records ``problems`` accepts.

    A missing default file returns an empty list: no data means no results,
    never invented ones. An explicit ``path`` that does not exist is an error.
    """
    target = Path(path) if path else DATA_PATH
    if path is None and not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    records = raw.get("organizations", []) if isinstance(raw, dict) else raw
    return [r for r in records if not problems(r)]


# ---------------------------------------------------------------------------
# The taxonomy as a graph
# ---------------------------------------------------------------------------

def _stem(word):
    """Strip a plural so "groceries" meets "grocery". Deliberately crude."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _words(text):
    return {_stem(w) for w in re.findall(r"[a-z]+", str(text).casefold())}


class Taxonomy:
    """The category hierarchy as a graph of parent -> child edges.

    ``utils/predict_category_list.py`` keeps the hierarchy as dotted string
    keys and recovers it by scanning every key on each call
    (``get_direct_children``). Here the edges are built once. The ID "3.3.1"
    has the parent "3.3"; a key whose would-be parent is not in the dictionary
    (such as the special "0.0.0.0.0" general category) is a root.
    """

    def __init__(self, categories=None):
        if categories is None:  # the classifier's own dictionary
            from utils.predict_category_list import help_categories as categories
        self.names = dict(categories)
        self._ids_by_name = {n.casefold(): i for i, n in self.names.items()}
        self._parent = {}
        self._children = defaultdict(list)
        for cid in self.names:
            parent = cid.rsplit(".", 1)[0] if "." in cid else None
            if parent in self.names:
                self._parent[cid] = parent
                self._children[parent].append(cid)

    def parent(self, cid):
        return self._parent.get(cid)

    def children(self, cid):
        return list(self._children.get(cid, []))

    def ancestors(self, cid):
        """Parents from nearest to the root."""
        chain = []
        while cid in self._parent:
            cid = self._parent[cid]
            chain.append(cid)
        return chain

    def descendants(self, cid):
        """Every node below ``cid``, breadth first."""
        found, queue = [], deque(self._children.get(cid, []))
        while queue:
            node = queue.popleft()
            found.append(node)
            queue.extend(self._children.get(node, []))
        return found

    def resolve(self, text):
        """Return the category ID for an ID or an exact category name, else None."""
        text = str(text or "").strip()
        if text in self.names:
            return text
        return self._ids_by_name.get(re.sub(r"[\s-]+", "_", text).casefold())

    def infer(self, text):
        """Return the most specific categories whose every significant word is in ``text``.

        Conservative on purpose: a wrong category is worse than none. Callers
        that know the category should pass it to ``resolve`` instead.
        """
        present = _words(text)
        matched = []
        for cid, name in self.names.items():
            if cid == "0.0.0.0.0":
                continue
            tokens = {_stem(w) for w in re.findall(r"[a-z]+", name.casefold())
                      if w not in _STOPWORDS}
            if tokens and tokens <= present:
                matched.append(cid)
        return [c for c in matched
                if not any(c in self.ancestors(other) for other in matched)]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _relation(taxonomy, served, wanted):
    """How a category an organization serves relates to the one requested."""
    if served == wanted:
        return "exact"
    if served in taxonomy.ancestors(wanted):
        return "broader"    # the organization covers a wider area
    if wanted in taxonomy.ancestors(served):
        return "narrower"   # the organization covers a more specific area
    return None


def location_fit(record, location):
    """How well a record's service area covers ``location``.

    3 = a city-level area inside the location, 2 = a state or region, 1 = a
    national area, 0 = the caller gave no usable location (no filtering), and
    None = the record does not serve this location. Whole-word matching stops
    "CA" matching "Chicago".
    """
    place = str(location or "").casefold().strip()
    if place in _UNSPECIFIED_LOCATIONS:
        return 0
    best = None
    for area in record.get("service_area") or []:
        area = str(area).casefold().strip()
        if area in _NATIONAL_AREAS:
            fit = 1
        else:
            parts = [p.strip() for p in area.split(",") if p.strip()]
            if not parts or not all(re.search(rf"\b{re.escape(p)}\b", place) for p in parts):
                continue
            fit = 3 if len(parts) > 1 else 2
        best = fit if best is None else max(best, fit)
    return best


def retrieve(records, taxonomy, wanted, location, text="", limit=6):
    """Score, filter and rank records. Returns hits, best first.

    ``wanted`` is a list of category IDs. With none, records are matched by
    their own ``keywords`` against ``text``. A hit is a dict with the record,
    its score, how it matched, and the location fit.
    """
    words = _words(text)
    hits = []
    for record in records:
        fit = location_fit(record, location)
        if fit is None:
            continue
        best = None
        for served in record.get("categories", []):
            for want in wanted:
                relation = _relation(taxonomy, served, want)
                if relation and (best is None or SCORES[relation] > SCORES[best[0]]):
                    best = (relation, served, want)
        if best is None and not wanted:
            if any(_stem(str(k).casefold()) in words for k in record.get("keywords", [])):
                best = ("keyword", (record["categories"] or [""])[0], "")
        if best:
            hits.append({"record": record, "matched_via": best[0], "served": best[1],
                         "wanted": best[2], "score": SCORES[best[0]], "fit": fit})
    hits.sort(key=lambda h: (-h["score"], -h["fit"],
                             h["record"]["organization_name"].casefold()))
    return hits[:limit]


def _relevance(hit, taxonomy):
    """A plain, deterministic reason; no model writes this."""
    served = taxonomy.names.get(hit["served"], hit["served"])
    wanted = taxonomy.names.get(hit["wanted"], hit["wanted"])
    return {
        "exact": f"Listed as serving {served}, the category of this request.",
        "broader": f"Serves {served}, a broader area that includes {wanted}.",
        "narrower": f"Serves {served}, a more specific area within {wanted}.",
        "keyword": "Its listed keywords match words in this request.",
    }[hit["matched_via"]]


def find_organizations_grounded(subject, description, location, category=None, *,
                                records=None, taxonomy=None, limit=6):
    """Return ``{"organizations": [...], "grounding": {...}}`` from verified records.

    Same arguments as ``utils.search_orgs.find_organizations``, so it can stand
    in for it. Rows go through the same ``normalize_result``, so every field the
    aggregator and the tab read is present. The request's location and
    category are deliberately NOT passed to the normalizer, which would
    otherwise fill a blank ``location`` or ``causes`` with the request's own
    values: fine for model output, but here it would print a claim no source
    supports. Returns an empty list when nothing matches.
    """
    taxonomy = taxonomy or Taxonomy()
    records = [r for r in (load_records() if records is None else records)
               if not problems(r)]
    text = f"{subject or ''} {description or ''} {category or ''}"
    resolved = taxonomy.resolve(category) if category else None
    wanted = [resolved] if resolved else taxonomy.infer(text)
    hits = retrieve(records, taxonomy, wanted, location, text, limit)

    rows = []
    for hit in hits:
        record = hit["record"]
        row = {f: record.get(f, "") for f in SO.ORGANIZATION_FIELDS}
        row["source"] = record["sources"]["organization_name"]
        row["causes"] = ", ".join(record.get("causes") or [])
        row["relevance"] = _relevance(hit, taxonomy)
        rows.append(row)

    result = SO.normalize_result({"organizations": rows})
    result["grounding"] = {
        "mode": "grounded-retrieval",
        "dataset_records": len(records),
        "query_categories": wanted,
        "results": [{"source_id": h["record"]["source_id"], "score": h["score"],
                     "matched_via": h["matched_via"], "location_fit": h["fit"],
                     "field_sources": h["record"]["sources"]} for h in hits],
    }
    return result


# ---------------------------------------------------------------------------
# Auditing organizations from another source (for example the model)
# ---------------------------------------------------------------------------

def _norm(field, value):
    text = str(value or "").strip().casefold()
    if field == "web_url":
        return re.sub(r"^https?://(www\.)?|/+$", "", text)
    if field == "contact":
        return re.sub(r"\D", "", text)
    if field == "rating":
        return "" if not value else f"{SO._normalize_rating(value):.1f}"
    return text


def audit(organizations, records=None):
    """Check organizations against verified records.

    Each organization is ``supported`` (a record has the same name and no
    differing field), ``contradicted`` (same name, a field differs) or
    ``unsupported`` (no record with that name, so nothing can be checked).
    This is how model-written organizations are measured against ground truth.
    """
    records = [r for r in (load_records() if records is None else records)
               if not problems(r)]
    by_name = {_norm("organization_name", r["organization_name"]): r for r in records}
    checked = ("web_url", "contact", "email", "location", "rating", "size", "org_type")
    report = []
    for org in organizations:
        record = by_name.get(_norm("organization_name", org.get("organization_name")))
        mismatched = [] if record is None else [
            f for f in checked
            if _norm(f, org.get(f)) and _norm(f, org.get(f)) != _norm(f, record.get(f))]
        status = ("unsupported" if record is None
                  else "contradicted" if mismatched else "supported")
        report.append({"organization_name": org.get("organization_name", ""),
                       "status": status, "mismatched_fields": mismatched})
    counts = {s: sum(r["status"] == s for r in report)
              for s in ("supported", "contradicted", "unsupported")}
    return {"organizations": report, "summary": {"total": len(report), **counts}}


#: Sample requests for ``demo``: (category, location, what the person might type).
#: They cover a local match, the category graph, a national fallback and two
#: requests nobody can answer, which must return nothing.
DEMO_CASES = (
    ("HOUSING_ASSISTANCE", "Chicago, IL", "I need a place to stay"),
    ("LOOKING_FOR_RENTAL", "Houston, TX", "looking for a rental"),
    ("DONATE_CLOTHES", "Seattle, WA", "I want to donate clothes"),
    ("HOUSING_ASSISTANCE", "Denver, CO", "I need a place to stay"),
    ("FOOD_ASSISTANCE", "Denver, CO", "I need food"),
    ("TUTORING", "Chicago, IL", "math tutoring"),
)


def demo(records=None, taxonomy=None):
    """Print what grounded retrieval returns for ``DEMO_CASES``, in plain text.

    For each request it prints the organizations served, how each one matched
    (exact, broader, narrower or keyword), how well its service area fits the
    location, and the source URL behind its name. A request nobody can answer
    prints "nothing returned". Uses the shipped dataset unless ``records`` is
    given; calls no model, network or AWS.
    """
    taxonomy = taxonomy or Taxonomy()
    records = [r for r in (load_records() if records is None else records)
               if not problems(r)]
    print(f"Dataset: {len(records)} records, each served only if verified and sourced\n")
    for category, location, text in DEMO_CASES:
        result = find_organizations_grounded(text, text, location, category,
                                             records=records, taxonomy=taxonomy)
        print(f'REQUEST  category={category}  location="{location}"  text="{text}"')
        grounding = result["grounding"]["results"]
        if not grounding:
            print("  -> nothing returned (no verified record matches)\n")
        for org, g in zip(result["organizations"], grounding):
            print(f"  -> {org['organization_name']}")
            print(f"     matched via: {g['matched_via']}  "
                  f"(score {g['score']}, location fit {g['location_fit']})")
            print(f"     name sourced from: {g['field_sources']['organization_name']}\n")


def main(argv=None):
    """Command line entry point: ``--demo``, or ``subject description location [category]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--demo"]:
        demo()
        return
    args += [""] * 4
    print(json.dumps(find_organizations_grounded(args[0], args[1], args[2] or "United States",
                                                 args[3] or None), indent=2))


if __name__ == "__main__":
    main()
