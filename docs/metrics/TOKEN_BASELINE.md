# Token Usage Audit and Baseline

Issue #159, step 1 of #6 (cost efficiency). Measures where tokens are spent
across every LLM call, consolidates counting into one util, and proposes
per-service budget targets.

- **Counting util:** `utils/token_usage.py`
- **Measurement harness:** `tools/measure_token_baseline.py`
- **Raw results:** `docs/metrics/token_baseline.json`
- **Measured:** 2026-09-06, `openai/gpt-oss-20b` (Groq) + `gemini-2.5-flash`
- **Corpus:** 8 fixed help requests spanning six categories and 31-500 character
  descriptions, defined in the harness so two runs stay comparable

---

## 1. Inventory: every LLM call, and how it counted tokens before this work

Seven call sites across four services and two providers. Groq is primary,
Gemini is the fallback everywhere.

| Service | Where | SDK | Counted before? |
|---|---|---|---|
| Classification | `services/classification_service.py:245,292` | raw Groq | yes, hand-rolled |
| Classification (fallback) | `services/classification_service.py:150,179` | raw `google.genai` | yes, hand-rolled |
| Answer generation | `utils/__init__.py:146,159` | LangChain | **no** |
| Subject generation | `utils/subject_generator.py:51`, 4 branches | LangChain | **no** |
| Organization search | `utils/search_orgs.py:250` | LangChain chain | **no** |
| Emergency contacts | `services/emergency.py` | — | n/a, no LLM |

Three response shapes reach us, which is why counting kept getting skipped:

```
raw Groq          response.usage.prompt_tokens
raw google.genai  response.usage_metadata.prompt_token_count
LangChain         message.usage_metadata["input_tokens"]
```

The raw Gemini response and a LangChain `AIMessage` both expose an attribute
literally named `usage_metadata` with completely different shapes, so anything
sniffing on the name alone silently reads one as the other.

Organization search was structurally unable to report usage: the chain was
`prompt | llm | parser`, which hands back the parsed dict and discards the
`AIMessage` carrying the counts in between. It is now invoked in two steps.

`utils/token_usage.py` owns all three shapes behind `extract_usage()`, so no
caller branches on the provider. Counting never raises - a request that would
have succeeded must not fail because telemetry did.

### Thinking tokens

Both current models bill reasoning tokens as output while reporting them apart
from the visible answer (`thoughts_token_count`, `output_token_details.reasoning`).
The util adds them back. Without that, the numbers below would understate real
spend by roughly 3x on the two worst services.

---

## 2. Baseline: mean tokens per interaction, per service

8 samples per service. Medians are given because the means carry real outliers.

| Service | Calls/req | Prompt | Completion | **Total** | Median | Range |
|---|---:|---:|---:|---:|---:|---:|
| `search_orgs` | 1.12 | 1,363 | 2,347 | **3,710** | 2,206 | 2,112-14,355 |
| `generate_subject` | 1.00 | 523 | 1,515 | **2,038** | 1,241 | 667-4,691 |
| `predict_category` | 2.25 | 1,172 | 258 | **1,430** | 1,422 | 527-2,167 |
| `generate_answer` | 1.00 | 528 | 410 | **938** | 817 | 714-1,299 |
| **All four** | | | | **8,116** | | |

A user who files one request and opens the Organizations tab costs about
**8,100 tokens**.

### What the shape of each service tells you

**`predict_category` is prompt-bound and call-bound.** 1,172 prompt tokens
against 258 completion, and 2.25 calls per request - it walks the taxonomy one
LLM call per level, re-sending every candidate category with its full
`TAXONOMY` description each time. Depth is decided by the model's own choice,
so cost varies 4x across the corpus (527 to 2,167) for identical-looking
requests. The one-call case (`elderly-medium`, 527 tokens) is the request
routed straight to a subtree by `is_elderly_context` - deterministic routing is
already saving a call there.

**`generate_subject` and `generate_answer` are completion-bound, and should not
be.** Subject generation spends 1,515 completion tokens on average to produce a
70-character string. Two corpus entries hit 4,094 completion tokens - a ceiling,
not a length. See §3.

**`search_orgs` is the single most expensive call** and the only one asking for
a large structured document: 6 organizations × 13 fields, three of which are
"3-line summaries". 2,347 completion tokens is the JSON it was asked for.

**Fixed prompt overhead dominates short requests.** The shortest description in
the corpus is 31 characters; `generate_subject` still spends 498 prompt tokens
on it, because the rules-and-examples preamble is ~450 tokens regardless of
input. For typical requests, most prompt spend is template, not user text.

---

## 3. Biggest consumers and the reduction shortlist

### 3.1 `reasoning_effort` is unset on the shared LangChain model — measured, one line

`GROQ_MODEL` is `openai/gpt-oss-20b`, a reasoning model that defaults to *high*
effort. Two places already know this and pin it low:

- `classification_service._groq_extra_kwargs()` → `reasoning_effort="low"`
- `search_orgs.load_llm()` → `reasoning_effort="low"`

The shared `groq_llm` in `utils/client.py:69-73` does not. That model is what
answer generation and subject generation use - and they are exactly the two
services whose completion tokens run away.

Confirmed directly: a subject-line call returned 134 output tokens of which
**112 were reasoning**. The visible answer was 22 tokens.

Measured over the full corpus, adding `reasoning_effort="low"`:

| Service | Before | After | Reduction | Output quality |
|---|---:|---:|---:|---|
| `generate_subject` | 2,108 | 666 | **-68%** | unchanged; max drops 4,691 → 1,078 |
| `generate_answer` | 1,059 | 636 | **-40%** | answers got *longer*, 309 → 353 chars |

Each row above is an A/B measured back-to-back in one run, so compare within a
row. The "before" figures differ slightly from the §2 table because the models
are non-deterministic and these were separate runs; the ratio is the signal.

Answers get longer while costing less, because what is removed is invisible
reasoning, not content. Combined saving is roughly **1,900 tokens per full
request, ~23% of total spend**, from one keyword argument.

Not applied here - it changes model behavior on two user-facing services and
deserves its own PR and review. It is a one-line change to `utils/client.py`.

### 3.2 Classification re-sends the taxonomy at every level

Each level's prompt embeds every candidate category *and its full description*.
Walking three levels sends three overlapping category blocks. Options, roughly
in order of effort:

- Trim `TAXONOMY` descriptions in the prompt to a short discriminating clause.
  The descriptions are written for humans and are the bulk of the 1,172 prompt
  tokens.
- Drop the routing hint block once candidates are no longer top-level - it is
  only meaningful at depth 0 and is currently appended whenever the candidate
  set matches the top level.
- Extend deterministic pre-routing (`is_elderly_context`) to other unambiguous
  cues. It already cuts `elderly-medium` to a single call, the cheapest result
  in the corpus.

Estimated: 30-50% of classification prompt tokens, no behavior change if the
trimmed descriptions preserve the distinctions.

### 3.3 `search_orgs` asks for more prose than the tab renders

Three separate "3-line summary" fields (`mission`, `description`, `relevance`)
per organization, times 6 organizations, is most of the 2,347 completion
tokens. Worth confirming with the frontend and the aggregator team which of
those the Organizations tab actually displays in full before trimming, since
`ORGANIZATION_FIELDS` is a cross-team contract (issue #170) - the field must
keep existing even if the prompt asks for one line instead of three.

Estimated: 20-40% of the most expensive service, pending that confirmation.

### 3.4 Fallback double-bills, and it fires more often than an outage would

A Groq failure re-runs the whole request on Gemini and both halves are billed.
It showed up twice in a handful of `search_orgs` runs: 2 calls and 14,355
tokens against a 2,206 median in the corpus, and 2 calls / 12,794 tokens in a
follow-up run. Roughly a 6x request.

The cause is not an outage. Retrying that exact request against Groq alone
succeeds, and `find_organizations` falls through to the next provider on *two*
conditions - an exception, and a valid response that simply contained no
organizations (`utils/search_orgs.py`, "returned no organizations"). The
expensive path is the second one: Groq answers, we discard the answer, and
Gemini is asked the same question again.

Worth a look on its own, because it is both a cost and a latency problem. Two
things to establish first, now that the per-call provider list is in the logs:

- how often the empty-result fallback fires in production, versus a real error;
- whether Groq's empty results correlate with a prompt problem we could fix,
  in which case the fallback is masking a bug rather than covering an outage.

No change proposed until those numbers exist.

### 3.5 Short descriptions pay full prompt price

For a 31-character request, `generate_subject` spends ~450 tokens of fixed
preamble. A length threshold below which the description is used directly, or a
shortened prompt variant for short inputs, avoids the call. Note the existing
`len(description) <= max_length` branch does *not* skip the LLM - it calls the
model anyway and only falls back to truncation on error.

---

## 4. Proposed per-service budget targets

Targets are medians, not means, so one runaway request does not mask a
regression. All are achievable with §3.1 and §3.2 alone.

| Service | Today (median) | Target | Basis |
|---|---:|---:|---|
| `generate_subject` | 1,241 | **700** | §3.1 measured at 666 |
| `generate_answer` | 817 | **650** | §3.1 measured at 636 |
| `predict_category` | 1,422 | **900** | §3.2, prompt trim at constant depth |
| `search_orgs` | 2,206 | **1,800** | §3.3, pending frontend confirmation |
| **Full request** | ~5,700 | **~4,050** | ~29% reduction |

Suggested alert thresholds, for when budgeting lands: warn at 2x target on a
single request, page on a daily mean above target.

---

## 5. Reproducing this

```bash
pip install -r requirements.txt -r requirements-dev.txt
python tools/measure_token_baseline.py              # all services, 8 requests
python tools/measure_token_baseline.py --limit 3    # cheaper pass
python tools/measure_token_baseline.py --service classify subject
```

Reads `GROQ_API_KEY` / `GEMINI_API_KEY` from `.env`. `utils/client.py` loads
keys from SSM only, which is correct for Lambda and unusable on a laptop, so
the harness builds and injects its own clients rather than changing how the
deployed function loads credentials.

Costs roughly 45 live calls per full run. Re-run when a prompt or a model
changes, and commit the regenerated `token_baseline.json`.

Numbers are 8 samples against non-deterministic models; treat differences under
about 15% as noise and re-run before acting on them.

## 6. Reading usage in production

Every service now emits one line per request:

```
TOKEN_USAGE {"service": "generate_answer", "total_calls": 1, "total_prompt_tokens": 496, ...}
```

CloudWatch Logs Insights:

```
fields @timestamp, @message
| filter @message like /TOKEN_USAGE/
| parse @message "TOKEN_USAGE *" as body
| stats avg(total_tokens), max(total_tokens), count(*) by service
```

Usage is reported to logs only, deliberately. `search_orgs` returns a body the
org-aggregator team parses as a contract, so nothing was added to any response
shape. `predict_category` keeps the `body.token_usage` field it already
returned before this work.
