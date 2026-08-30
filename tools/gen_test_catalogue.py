"""Generate docs/testing/TEST_CATALOGUE.md from the test suite itself.

A catalogue maintained by hand goes stale the first time someone is in a hurry,
and a stale catalogue is worse than none: QA reads it, believes a behaviour is
covered, and stops looking. This reads the actual test files and the actual
pytest collection, so the document can only ever describe tests that exist.

    python tools/gen_test_catalogue.py

Run it after adding or renaming tests. CI checks that the committed file
matches what this produces.
"""
from __future__ import annotations

import ast
import collections
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
OUTPUT = REPO / "docs" / "testing" / "TEST_CATALOGUE.md"

KIND = {
    "unit": "Unit",
    "contract": "Contract",
    "dataset": "Dataset",
    "integration": "Integration",
}

# Which issue each file protects, and the code it exercises. Add a row here
# when you add a test file; the script fails if one is missing, so the mapping
# cannot silently rot.
FILE_META = {
    "test_router.py": ("#171", "lambda_function.lambda_handler"),
    "test_response_contract.py": ("#146, #169, #170", "response envelopes"),
    "test_emergency_locale.py": ("#146", "services/emergency.py"),
    "test_emergency_dataset.py": ("#146", "services/emergency_numbers.json"),
    "test_generate_answer.py": ("#169", "generate_answer_handler"),
    "test_import_blast_radius.py": ("#169, #171", "module-scope imports"),
    "test_org_search_contract.py": ("#170", "utils/search_orgs.py"),
    "test_client_imports.py": ("#154", "utils/client.py"),
    "test_classification_resilience.py": ("-", "services/classification_service.py"),
    "test_subject_generator.py": ("-", "utils/subject_generator.py"),
}

HEADER = """# Test catalogue

**Generated from the suite by `tools/gen_test_catalogue.py`. Do not edit by
hand.** A catalogue maintained separately from the tests goes stale, and a
stale catalogue is worse than none, because it is believed.

This is the document to read when deciding whether a behaviour is adequately
covered. Each row names the behaviour a test protects, not merely what it
calls.

## Test kinds

| Kind | Meaning | Trust it for |
| --- | --- | --- |
| **Unit** | One function, collaborators mocked, no I/O. | Internal logic: fallback selection, field normalisation. |
| **Contract** | The shape of what crosses a boundary - the Lambda event in, the JSON envelope out. | Whether the web client will break. **These mirror what the browser actually sees, so trust these most.** |
| **Dataset** | Assertions over shipped data files. | Data quality, independent of code. |
| **Integration** | Several modules together, still hermetic. | Wiring, and blast radius between services. |

No test in the default run touches the network: `tests/conftest.py` fails any
unmarked test that opens a URL. Anything that genuinely needs the network must
be marked `needs_network`, which is excluded from the default run and from CI.
"""


def summarise(doc: str | None, fallback: str) -> str:
    if doc:
        first = " ".join(doc.strip().split("\n\n")[0].split())
        return first.rstrip(".") + "."
    return fallback.replace("test_", "").replace("_", " ").capitalize() + "."


def collected_counts() -> collections.Counter:
    """Ask pytest what it actually collects, including parametrised cases."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "--no-header"],
        capture_output=True, text=True, cwd=REPO,
    )
    counts: collections.Counter = collections.Counter()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" in line and line.startswith("tests"):
            counts[pathlib.Path(line.split("::")[0]).name] += 1
    if not counts:
        raise SystemExit("pytest collected nothing:\n" + result.stdout + result.stderr)
    return counts


def main() -> int:
    counts = collected_counts()
    rows = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name not in FILE_META:
            raise SystemExit(
                f"{path.name} has no entry in FILE_META in {__file__}. Add one so "
                "the catalogue records which issue it protects."
            )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mark = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "pytestmark":
                mark = ast.unparse(node.value).split(".")[-1]
        issue, covers = FILE_META[path.name]
        fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        rows.append({
            "name": path.name,
            "kind": KIND.get(mark, mark or "-"),
            "issue": issue,
            "covers": covers,
            "cases": counts.get(path.name, 0),
            "fns": fns,
            "summary": summarise(ast.get_docstring(tree), path.stem),
        })

    out = [HEADER, "## Files", "",
           "| File | Kind | Issue | Covers | Tests |",
           "| --- | --- | --- | --- | ---: |"]
    total = 0
    for r in rows:
        total += r["cases"]
        out.append(f"| [`tests/{r['name']}`](../../tests/{r['name']}) | {r['kind']} | "
                   f"{r['issue']} | `{r['covers']}` | {r['cases']} |")
    out += [f"| | | | **Total** | **{total}** |", "", "## Every test", ""]

    for r in rows:
        out += [f"### `{r['name']}`", "",
                f"*{r['kind']} · issue {r['issue']} · {r['cases']} tests*", "",
                r["summary"], "",
                "| Test | Behaviour it protects |", "| --- | --- |"]
        for fn in r["fns"]:
            out.append(f"| `{fn.name}` | {summarise(ast.get_docstring(fn), fn.name)} |")
        if r["cases"] > len(r["fns"]):
            out += ["", f"> {len(r['fns'])} test functions expand to {r['cases']} "
                        "cases through parametrisation."]
        out.append("")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)} - {total} tests across {len(rows)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
