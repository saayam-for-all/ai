# Part 4: news-snippet processing (#191)

This is a useful, deliberately limited earthquake implementation on
`kartik/issue-191-news-snippet`, based on `4aa8098`. It does not complete the
whole issue or Part 5's Gemini verification.

## Request and response

See the [README](../README.md#news-snippet-requests-part-4) for the accepted
grammar, matching thresholds and response contract. General free-form news,
missing magnitude/location, relative times, date-only reports, negated reports,
multiple reports and unsupported disaster types cannot confirm an event here.
For example, the task's Tokyo report ending in “this morning” is unresolved.
An explicit ISO occurrence timestamp with timezone is required for matching.
Optional `published_at` records publication time; it never invents event time.
Seconds may be omitted; fractional seconds are not supported yet.

Unresolved results add a nullable `disaster_detected` value only on the new
news path. Coordinate responses retain their existing boolean contract.
Consumers should check `status`, `reason` and exact boolean true, and must not
interpret null or an empty event list as proof of safety.

## Design

- `services/disaster_news.py` extracts one supported report, validates temporal
  consistency, geocodes its place, and matches time, epicentral distance and
  magnitude. It uses the existing `usgs_earthquakes.fetch_events` and
  `disaster_check` distance/rendering helpers. A broad impact zone reaching a
  location does not establish that the report describes that earthquake.
- `services/disaster_geocoding.py` provides isolated forward geocoding. The
  emergency resolver cannot be reused safely: it selects the first result,
  suppresses failures, and returns administrative names instead of coordinates.
- `services/usgs_earthquakes.py` retains numeric `magnitude` in its internal
  record; the existing public event rendering is unchanged.
- `lambda_function.py` selects news processing when the snippet key is present,
  including validation of blank or non-string values. Coordinates use the same
  code as before. Errors retain 400/502/500 semantics and object response bodies.

Only one active matching record may confirm a report. Zero/multiple matches
remain unresolved and carry no event. Unknown geocoding and ambiguity also
remain unresolved. Provider errors and malformed provider data return 502,
never an empty successful finding. Matching thresholds are initial heuristics,
not calibrated confidence scores. Even a matched report has no LLM corroboration;
the confidence field describes only USGS solution review status.

## Geocoding setup

The adapter uses [maps.co's documented API](https://geocode.maps.co/docs/),
which hosts Nominatim backed by OpenStreetMap. It does not use the public
`nominatim.openstreetmap.org` endpoint. Create a provider account/key and store
it as a SecureString in AWS Systems Manager Parameter Store at
`/dev/saayam/GenAI/geocoding/key`. `DISASTER_GEOCODING_KEY_PARAMETER` can select
another parameter name; it is a path, not the secret. No key belongs in source
or an environment file. Grant the Lambda role `ssm:GetParameter` on that
parameter and `kms:Decrypt` if its encryption key requires it.

Loading is lazy and successful keys are cached per process. Rotate/restart
Lambda environments to invalidate cached credentials. SSM has 2-second connect
and read timeouts with one attempt; geocoding uses a 4-second socket timeout
and one request with no retries. These are socket timeouts, not a total Lambda
deadline. Only the extracted place is sent to the geocoder. The API key goes
in the Authorization header, and provider exception text is sanitized.

The search requests up to two candidates and accepts exactly one; it never
chooses the highest-ranked candidate. This can reject legitimate names with
duplicate results. Include a country/region to reduce ambiguity. An empty list
means unknown location; malformed data, 429/503, credential errors and timeouts
mean unavailable. No fallback to an IP address or a hardcoded city is used.

Provider quotas depend on the account plan. Configure caller throttling in the
deployment to fit that quota. HTTP 429 is surfaced as retryable 502 with the
existing service code, without immediate retry; clients should back off. This
change does not implement account-wide throttling or caching. Respect provider
terms and preserve OpenStreetMap attribution in downstream location displays.

## Deterministic manual check

Activate the existing virtual environment, then run these commands from the
repository root. They require no geocoding key, network or model credentials:

```bash
source .venv/bin/activate
pytest -q tests/test_disaster_news.py tests/test_disaster_news_contract.py tests/test_disaster_geocoding.py tests/test_disaster_check.py tests/test_disaster_check_contract.py tests/test_usgs_earthquakes.py
pytest -q
```

To inspect an actual routed response, replay the shipped USGS fixture with
the clock and geocoding boundary replaced:

```bash
python - <<'PY'
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import lambda_function as LF
from services import disaster_news as news

payload = {
    "service": "disaster_check",
    "news_snippet": "A magnitude 7.8 earthquake struck near Gaziantep, Turkey on 2023-02-06T01:17:34Z.",
    "published_at": "2023-02-06T04:00:00Z",
}
fixture = Path("tests/fixtures/usgs/kahramanmaras_2023-02-06.geojson").read_bytes()
with patch.object(news, "datetime", wraps=datetime) as clock, patch.object(
    news.disaster_geocoding, "geocode_place",
    return_value={"latitude": 37.0662, "longitude": 37.3833},
), patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(fixture)):
    clock.now.return_value = datetime(2023, 2, 6, 12, tzinfo=timezone.utc)
    print(json.dumps(LF.lambda_handler({"body": json.dumps(payload)}, None), indent=2))
PY
```

Expected: HTTP 200, object body with `status: "matched"`,
`disaster_detected: true`, `confidence: "high"`, event `usgs-us6000jllz`, USGS
evidence, and `llm_cross_check: null`. This replays a historical record; it is
not evidence of a current event or a live deployment test.

For a credential-free unresolved example, invoke:

```python
LF.lambda_handler({"service": "disaster_check", "news_snippet":
    "A magnitude 6.5 earthquake struck near Tokyo, Japan this morning."}, None)
```

The body includes:

```json
{
  "status": "unresolved",
  "reason": "missing_or_ambiguous_occurrence_time",
  "disaster_detected": null,
  "confidence": "unverified",
  "events": [],
  "sources_checked": []
}
```

The full body also includes `extracted` and an advisory. To test against live
providers, configure SSM as above and supply a real recent earthquake's place,
magnitude and exact occurrence timestamp. Call `lambda_handler` locally or
POST that payload to the team's configured unified-router endpoint. No
dedicated route or deployment is added by this change. Old examples are
unresolved outside the supported window and cannot trigger a current alert.

## Integration and follow-up

Investigation: [Issue #191 and comments](https://github.com/saayam-for-all/ai/issues/191),
[flood PR #218](https://github.com/saayam-for-all/ai/pull/218),
[caching PR #221](https://github.com/saayam-for-all/ai/pull/221), and
[wildfire PR #233](https://github.com/saayam-for-all/ai/pull/233).
GitHub CLI access failed locally; the issue/comments and PR #218/#233 were
read through web access, with cached local branches used to inspect code.
No other Part 4 branch was found among local fetched refs; this does not prove
that nobody has unpushed work.

Flood and wildfire adapters are absent from this base, so their news matching
is deferred rather than implemented against unmerged code. The caching branch
changes `fetch_events` from a list to `FeedAnswer` and changes rendering and
retrieval-time handling. Update the isolated news matcher to consume that
interface and actual fetch timestamps when Part 6 merges. Do not unwrap it
blindly or claim stale data is current. README edits may also need resolution
when the stacked parts land.

Part 5 should extend extraction through the repository's existing provider
chain, handle broader wording/timezone context, add corroboration and
disagreements, and fill `llm_cross_check`. It can consume `extracted` (type,
reported location, occurrence time/text, magnitude, publication time and resolved
coordinates) and authoritative event evidence. No artificial scores, Gemini
verification, alert delivery, deployment, or complete confidence model are
implemented here.

## Validation snapshot

Tested locally with Python 3.14.8; CI's Python 3.11 was not available in this
virtual environment. The default suite uses mocks and needs no live credentials.

- `pytest -q`: **638 passed**, compared with 548 on the starting commit.
- The focused command above: **217 passed**.
- `COVERAGE_FILE=/private/tmp/saayam-191-coverage .venv/bin/python -m pytest -q tests/ --cov=lambda_function --cov=services --cov=utils --cov-report=term --cov-fail-under=90`:
  **638 passed, 93.46%**, matching CI's application coverage scope. Both new
  modules have 100% line and branch coverage.
- `.venv/bin/python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=90`:
  all 638 tests passed, but the whole-tree coverage gate **failed at 87.11%**.
  That broader scope also includes the untested `mcp_poc` files.
- `.venv/bin/python -m bandit lambda_function.py services utils -ll -f screen`:
  **not run**, because Bandit is not installed (`No module named bandit`).
- The documented fixture replay returned HTTP 200, `matched`, and
  `usgs-us6000jllz`. No live provider or deployment smoke test was performed.
- Diff whitespace checks passed with `core.whitespace=cr-at-eol`, preserving
  the handler file's existing CRLF line endings. Generated coverage output is
  excluded from the commits.
