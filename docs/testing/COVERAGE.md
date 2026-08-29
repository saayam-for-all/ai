# Coverage

Measured with `pytest-cov` over branch coverage. Reproduce with:

```bash
python -m pytest --cov --cov-report=term-missing
```

Configuration lives in `.coveragerc`.

## Current numbers

This branch — `dev` plus the regression infrastructure from issue #171 — with
**63 tests**:

| Module | Statements | Missed | Branch coverage |
| --- | ---: | ---: | ---: |
| `lambda_function.py` | 162 | 66 | **57%** |
| `services/emergency.py` | 152 | 61 | **56%** |
| `services/classification_service.py` | 234 | 182 | **19%** |
| `utils/search_orgs.py` | 37 | 14 | **56%** |
| `utils/request_db.py` | 75 | 61 | **15%** |
| `utils/subject_generator.py` | 67 | 34 | **47%** |
| `utils/client.py` | 63 | 30 | **51%** |
| `utils/__init__.py` | 53 | 34 | **28%** |
| `utils/routing_for_categories.py` | 10 | 6 | **29%** |
| `utils/generate_answer_service.py` | 4 | 2 | **50%** |
| **Total** | **857** | **490** | **39%** |

## Threshold

CI fails below **35%**. That is deliberately just under the current number
rather than an aspiration: a threshold nobody can meet gets raised in a hurry
or deleted, and either way it stops meaning anything. Its job today is to catch
a **regression** — a change that deletes tests or adds a large unexercised
module — not to force new tests on unrelated code.

Raise it as coverage genuinely rises. Do not lower it.

## Where this goes once the in-flight fixes land

Each of #146, #169 and #170 brings its own tests. Measured on a local branch
that merges all three onto this infrastructure — **190 tests**, which is the
union with nothing dropped:

| Module | This branch | With #146 + #169 + #170 |
| --- | ---: | ---: |
| `lambda_function.py` | 57% | **91%** |
| `services/emergency.py` | 56% | **79%** |
| `utils/search_orgs.py` | 56% | **84%** |
| **Total** | **39%** | **56%** |

The three services those issues cover end up well exercised. The total is
dragged down by modules none of the three touch, listed below.

## Known-uncovered paths, and why

**`services/classification_service.py` (19%)** — the largest gap. Category
prediction loads model artefacts and calls a provider; the current tests cover
the resilience paths (what happens when the model or its artefacts are absent)
but not the prediction logic itself. This is the most valuable place to add
tests next, and it is not covered by any of the three in-flight fixes.

**`utils/request_db.py` (15%)** — everything past the connection call needs a
live Postgres. The module is reached only through `_lookup_request`, which the
`generate_answer` tests fake. The parts that matter to the API contract — the
`error_kind` classification that separates "no such request" from "the store is
down" — are covered on the #169 branch through that fake. Genuinely exercising
the driver requires a database in CI, which is a larger piece of work.

**`utils/client.py` (51%) and `utils/__init__.py` (28%)** — the uncovered lines
are the SSM Parameter Store lookup and provider client construction, which run
at import time and need AWS credentials. `tests/test_client_imports.py` covers
the property that actually matters: the module imports cleanly with no keys and
exports every name its consumers rely on.

**`utils/prompts*.py`, `utils/categories*.py`, `utils/predict_category_list.py`**
— omitted from measurement entirely in `.coveragerc`. They are data: long
string and list constants with no branches. Counting them moves the percentage
around without saying anything about whether the code using them is exercised.

**AWS-only paths** — anything that only runs inside Lambda (the deployment
packaging in `.github/scripts/`, runtime configuration) is not measured here
and cannot be, without a deployed environment.

## What the number does not mean

Coverage says a line executed, not that it was checked. A module at 90% can
still return the wrong status code if nothing asserts on it. Use
[TEST_CATALOGUE.md](TEST_CATALOGUE.md) — which lists the behaviour each test
protects — to judge whether coverage is adequate. Use this page only to spot
code that no test reaches **at all**.
