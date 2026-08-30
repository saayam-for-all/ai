# QA runbook — GenAI services

Everything needed to run the regression suite and read the result, assuming no
prior knowledge of this repository. If a step here does not work as written,
that is a bug in this document; please say so on
[issue #171](https://github.com/saayam-for-all/ai/issues/171).

## 1. What this suite does and does not prove

**It proves** that the Lambda handlers return the documented status codes and
response shapes, that the shipped emergency numbers directory is internally
consistent, that a failure in one service cannot take down the others, and that
no error response leaks an API key or a database connection string.

**It does not prove** that anything works in AWS. Every external boundary — the
model providers, Postgres, the geocoders — is faked. A green suite means "we
did not break the contract"; it does not mean "the deployed endpoint answers".
Deployed smoke tests need AWS access this team does not currently have, and are
tracked separately.

## 2. Setup

Python **3.11** — the same minor version the Lambda functions run. A different
minor version will usually still pass, but `psycopg2` wheels are built per
version and a mismatch is exactly the failure that took production down once
already.

```bash
python -m venv .venv
```

Activate it — `.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
on macOS or Linux — then:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

**No API keys and no AWS credentials are required.** If you have none
configured you will see this on startup, and it is expected:

```
INIT LOG: Groq API Key is missing. Groq will be disabled.
INIT LOG: Gemini API Key is missing.
```

Those lines are the model clients resolving to `None`. Every test fakes the
model boundary, so the suite does not care.

## 3. Run it

```bash
python -m pytest
```

A clean run ends with a single line. **63 tests, all passing, in about a
second:**

```
63 passed in 0.74s
```

If the count is lower than expected, tests were deselected rather than deleted
— check for a stray `-m` or `-k` argument.

## 4. Run one slice

Every test carries exactly one kind marker, so QA can run the part that matters
for a given change.

```bash
python -m pytest -m contract
```

| Command | What it runs | When to use it |
| --- | --- | --- |
| `python -m pytest -m contract` | Request and response shapes | **Start here for any web-client bug report.** These mirror what the browser sees. |
| `python -m pytest -m unit` | Single functions, mocked | A logic change inside one service. |
| `python -m pytest -m dataset` | The shipped data files | Any change to `services/emergency_numbers.json`. |
| `python -m pytest -m integration` | Routing and cross-service wiring | A change to `lambda_function.py`, or a dependency bump. |
| `python -m pytest tests/test_router.py` | One file | Narrowing down a failure. |
| `python -m pytest -k emergency` | Anything matching a name | Exploring. |

## 5. Coverage

```bash
python -m pytest --cov --cov-report=term-missing
```

The `Missing` column lists the line numbers no test reached. See
[COVERAGE.md](COVERAGE.md) for the current numbers, the CI threshold, and which
uncovered paths are uncovered deliberately.

## 6. Reading a failure

pytest prints the failing assertion with the actual values. Three patterns are
worth recognising:

**A contract test failed.** The response shape changed. This is the serious
one — a client is probably broken in production. The test name says which
field or status code.

**`This test made a live network call.`** A test tried to reach the internet.
The default run forbids it (`tests/conftest.py`), because a test that depends
on ipinfo.io or a model provider fails for reasons unrelated to our code. Fix
by mocking the call, or mark the test `needs_network` if reaching out is the
actual point of it.

**`E ModuleNotFoundError`** — the dev requirements are not installed, or the
virtual environment is not active. Re-run step 2.

## 7. Tests that need the network

Excluded from the default run and from CI. To run them deliberately:

```bash
python -m pytest -m needs_network
```

These call live services and can fail because a third party is rate-limiting
you rather than because anything is wrong here. Never gate a release on them.

## 8. What to file when a test fails

The test id (`tests/test_router.py::test_unknown_service_returns_the_documented_shape`),
the full assertion output, your Python version (`python -V`), and whether the
same test passes on `dev`. That last one separates "this branch broke it" from
"it was already broken".
