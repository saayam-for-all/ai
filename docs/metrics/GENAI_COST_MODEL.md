# GenAI Cost Model

**Rates Verified On:** 28 October 2026  
**Last Reviewed:** 28 October 2026  
**Model Currency Check:** 28 October 2026 (Live Audit)  
**Status:** Active  

---

## 1. Executive Summary

This document establishes the cost, capacity, and model lifecycle governance for the Saayam Generative AI microservices in response to leadership direction:
> *"We should be using the latest and the greatest LLM model services at the cheapest price. Please keep this as our goal... Please come up with our cost model — how much we are spending now, how much we may have to pay based on some approximate number of end users. We need to monitor this expense regularly."*

### Key Figures at a Glance

Following the telemetry double-counting fix and reasoning effort pin (PR #212) and the integration of the four-model fallback chain for answer generation (PR #213), token consumption was empirically re-measured on commit `271a402`. The figures below contrast historical estimates, the pre-fix ceiling, the measured baseline mean (including fallbacks), and normal Groq-only operation.

| Metric | Initial Estimate (16 Sep) | Pre-Fix Ceiling (#189) | Measured Baseline (`271a402` Mean)* | Groq-Only (Normal Operation) | Impact / Implication |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Tokens per Help Request** | 3,434 | 8,116 | **6,405** | **4,800** | Telemetry inflation corrected; Groq effort pinned to `low`. |
| **Cost per Help Request (Groq)** | $0.000433 | ~$0.00163 | **~$0.00108** | **~$0.00067** | Highly cost-effective (~$1.08 per 1,000 requests at mean). |
| **Cost per 1,000 Help Requests** | $0.43 | ~$1.63 | **$1.08** | **$0.67** | Predictable, low-cost scaling. |
| **Free-Tier Daily Capacity** | 58 / day | ~24 / day | **~31 / day** | **~41 / day** | **Strictly token-bound (200k TPD). Limits trigger failover.** |
| **Failover Multiplier (Gemini)** | 6.34× | Up to 15×+ | **~7.2× (Mean)** | **~6.8× (Lower Bound)** | Empty results in `search_orgs` trigger costly Gemini fallback. |
| **Self-Hosting Breakeven** | ~875,000 / mo | ~233,000 / mo | **~350,000 / mo** | **~565,000 / mo** | Fixed EC2 GPU instance remains unviable vs serverless API. |

*\*Note: The Measured Baseline Mean reflects a 25% Gemini fallback rate on `search_orgs` in the benchmark corpus due to empty results. In normal operation where all primary calls succeed, token usage is 4,800 tokens at $0.00067 per request.*

---

## 2. Token Baseline per Help Request

Tokens are measured against live model calls in `docs/metrics/token_baseline.json` across benchmark scenarios. A standard help request workflow invokes model-backed microservices across four core capabilities.

### Measured Service Breakdown (Commit `271a402`)

| Service | Calls / Req | Prompt Tokens (Measured) | Completion Tokens (Measured) | Total Tokens (Measured) | Operational & Architectural Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `predict_category` | 2.25 *(2–3)* | 1,172 | 266 | 1,438 | Hierarchical taxonomy descent across 49 leaf categories. Uses 4-model routing chain (#199) with `reasoning_effort="low"`. |
| `search_orgs` *(Mean)* | 1.12 *(1–2)* | 1,508 | 2,259 | 3,767 | Structured extraction of 6 organizations × 13 fields. 2 of 8 benchmark runs fell back to Gemini due to empty Groq results. |
| `search_orgs` *(Groq-Only)* | 1.00 | ~1,200 | ~963 | 2,163 | Flat vs pre-fix runs (−1%). Represents normal execution when primary Groq call returns valid results. |
| `generate_subject` | 1.00 | 524 | 58 | 582 | Summarizes description into a 70-character title. Pinned to `reasoning_effort="low"`; eliminates pre-fix 4,094-token ceilings. |
| `generate_answer` | 1.00 | 528 | 90 | 618 | Empathetic guidance turn. Powered by the 4-model chain (`run_model_chain`, #213) with `low` reasoning effort. |
| `emergency_contacts`| 0.00 | 0 | 0 | 0 | Deterministic country contact lookup (zero LLM calls). |
| **Total Measured Mean (incl. fallbacks)** | **~5.4** | **3,732** | **2,673** | **6,405** | Empirical mean on `271a402` with 25% Gemini fallback on org search. |
| **Total Groq-Only (no fallbacks)** | **~5.2** | **~3,424** | **~1,376** | **4,800** | Normal production path when all services succeed on primary Groq calls. |

### Accuracy & Measurement Notes

1. **Classification Descent Depth:** Of the 717 entries in the taxonomy, only **49 are actionable help categories**; the remaining 668 are form fields and questionnaires. Traversal stops once a leaf category is selected (e.g., `1 -> 1.1` terminates in 2 calls; `3 -> 3.3 -> 3.3.1` terminates in 3 calls). Deterministic pre-routing cuts unambiguous domains (e.g. elderly assistance) to a single call.
2. **LangChain Reasoning Token Accounting (PR #212):** In standard LangChain (`langchain-groq`, `langchain-google-genai`), `output_tokens` already includes reasoning/thought tokens; `output_token_details.reasoning` is an itemized breakdown. Prior to PR #212, `utils/token_usage.py` added reasoning a second time. The counting logic now correctly handles itemized breakdowns without double-counting.
3. **Reasoning Effort Control:** Groq's `openai/gpt-oss-20b` defaults to `medium` reasoning effort in provider API specifications. Explicitly pinning `reasoning_effort="low"` across `ModelTarget` and `config/model_routing.json` prevents runaway completion tokens while maintaining high summary quality.
4. **Observed Reduction Consistency:** The −21% reduction in total request token consumption on `271a402` (6,405 vs 8,116 ceiling) is consistent with the ~23% saving estimated from the reasoning effort pin alone.
5. **The `search_orgs` Fallback Finding:** In the benchmark suite, `food-short` (8,135 tokens) and `clothing-short` (9,024 tokens) encountered empty organization responses from Groq, triggering failover to Gemini. The other 6 runs completed on Groq at 2,089–2,246 tokens. Therefore, **the empty-result fallback rate to Gemini, rather than token count drift, is the primary operational cost driver**.

---

## 3. Provider Rates & Fallback Architecture

*Rates confirmed live on 28 October 2026.*

### Rate Table

| Provider | Model | Tier / Role | Input / 1M Tokens | Output / 1M Tokens | Rate Limits & Quotas |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Groq** | `openai/gpt-oss-20b` | Primary (All Services) | **$0.075** | **$0.30** | 30 req/min, 1,000 req/day, 8,000 tok/min, 200,000 tok/day |
| **Groq** | `openai/gpt-oss-120b` | Tier 2 (Chain Fallback) | **$0.150** | **$0.60** | 30 req/min, 1,000 req/day, 8,000 tok/min, 200,000 tok/day |
| **Groq** | `openai/gpt-oss-safeguard-20b`| Tier 3 (Chain Fallback, **Preview**) | **$0.075** | **$0.30** | Evaluation preview; subject to withdrawal at short notice. |
| **Google Gemini** | `gemini-2.5-flash` | Fallback Tier | **$0.300** | **$2.50** | 15 req/min, 1,500 req/day, 1,000,000 tok/min *(Gemini API)* |

*Note on Groq Prompt Caching:* Prompt caching is automatic on GPT-OSS 20B, 120B, and Safeguard 20B with a 50% discount on cached inputs ($0.0375/M). Cached tokens do not count against rate limits.

### Service Fallback Path Matrix

Following PR #199 and PR #213, fallback routing is organized as follows:

| Service | Fallback Routing Architecture | Implementation Module |
| :--- | :--- | :--- |
| `predict_category` | `gpt-oss-20b` → `gpt-oss-120b` → `gpt-oss-safeguard-20b` → `gemini-2.5-flash` | `services/classification_service.py` via `run_model_chain` |
| `generate_answer` | `gpt-oss-20b` → `gpt-oss-120b` → `gpt-oss-safeguard-20b` → `gemini-2.5-flash` | `utils/__init__.py` via `run_model_chain` (#213) |
| `generate_subject` | Groq `gpt-oss-20b` (`low` effort) → Gemini fallback | `utils/subject_generator.py` (inline fallback) |
| `search_orgs` | Groq `gpt-oss-20b` (`low` effort) → Gemini fallback | `utils/search_orgs.py` (inline fallback) |

*Architectural Note:* Following PR #213, `groq_llm`'s only remaining consumer in the repository is `generate_subject` (`utils/subject_generator.py`). All other services route through `run_model_chain` or custom client builders.

### Cost Calculation per Help Request (Reproducible Arithmetic)

```text
1. Measured Baseline Mean (3,732 Prompt / 2,673 Completion tokens):
   Prompt Cost:     3,732 tokens × ($0.075 / 1,000,000) = $0.0002799
   Completion Cost: 2,673 tokens × ($0.300 / 1,000,000) = $0.0008019
   ------------------------------------------------------------------
   Total Measured Mean Cost (Groq Primary):             = $0.0010818 ≈ $0.00108 / request ($1.08 / 1k reqs)

2. Groq-Only Normal Operation (3,424 Prompt / 1,376 Completion tokens):
   Prompt Cost:     3,424 tokens × ($0.075 / 1,000,000) = $0.0002568
   Completion Cost: 1,376 tokens × ($0.300 / 1,000,000) = $0.0004128
   ------------------------------------------------------------------
   Total Groq-Only Cost:                                = $0.0006696 ≈ $0.00067 / request ($0.67 / 1k reqs)

3. Gemini Sustained Fallback Cost (Priced at Measured Mean Tokens):
   Prompt Cost:     3,732 tokens × ($0.300 / 1,000,000) = $0.0011196
   Completion Cost: 2,673 tokens × ($2.500 / 1,000,000) = $0.0066825
   ------------------------------------------------------------------
   Total Gemini Fallback Cost (at Mean Tokens):         = $0.0078021 ≈ $0.00780 / request
   Nominal Multiplier at Mean: $0.0078021 / $0.0010818 ≈ 7.21x (~7.2x)

4. Gemini Sustained Fallback Cost (Lower Bound Basis: 3,442 Prompt / 1,548 Completion):
   Prompt Cost:     3,442 tokens × ($0.300 / 1,000,000) = $0.0010326
   Completion Cost: 1,548 tokens × ($2.500 / 1,000,000) = $0.0038700
   ------------------------------------------------------------------
   Total Gemini Fallback Cost (Lower Bound):            = $0.0049026 ≈ $0.00490 / request
   Nominal Multiplier at Lower Bound: $0.0049026 / $0.0007226 ≈ 6.78x (~6.8x)
```

> [!WARNING]
> **Operational Failover Multiplier:** While the nominal multiplier is **~6.8× at the lower bound and ~7.2× at the mean**, operational failover to Gemini can reach **10× to 15×+**. In Gemini 2.5 Flash, thinking tokens are billed as output at $2.50/M. In pre-fix baseline runs, an unconstrained Gemini fallback on `search_orgs` produced over 12,000 completion tokens (~$0.030 for a single call). Because failover triggers on empty results as well as provider outages, managing fallback rates is vital to budget stability.

---

## 4. Volume Projections

Monthly model expenditure projected across representative user volumes:

| Monthly Help Requests | Spend on Groq-Only ($0.00067) | Spend on Measured Mean ($0.00108) | Spend on Sustained Gemini Fallback ($0.00780) | Implied Active Users (at 1 req/user/mo)* |
| ---: | ---: | ---: | ---: | ---: |
| **1,000** | $0.67 | $1.08 | $7.80 | 1,000 |
| **10,000** | $6.70 | $10.82 | $78.02 | 10,000 |
| **50,000** | $33.48 | $54.09 | $390.11 | 50,000 |
| **100,000** | $66.96 | $108.18 | $780.21 | 100,000 |
| **500,000** | $334.80 | $540.90 | $3,901.05 | 500,000 |
| **1,000,000** | $669.60 | $1,081.80 | $7,802.10 | 1,000,000 |

*\*Note: 1.0 request per active user per month is a documented placeholder pending empirical user analytics from the Product and Request teams.*

---

## 5. Capacity Constraints & Operational Risks

### 5.1 The Free-Tier Cliff
* **Daily Token Limit:** Groq's free tier permits 200,000 tokens/day organization-wide.
* **Effective Daily Platform Capacity:**
  ```text
  Daily Capacity (Measured Mean): 200,000 tokens/day ÷ 6,405 tokens/req ≈ 31 help requests/day
  Daily Capacity (Groq-Only):     200,000 tokens/day ÷ 4,800 tokens/req ≈ 41 help requests/day
  ```
* **Operational Behavior of the Cliff:** Groq SDK errors (`HTTP 429` rate limit exceeded) are caught by upstream exception guards (`_try_groq`). Therefore, **reaching the free-tier limit does not fail the user's request; it silently migrates traffic to Gemini at ~7× the cost**.
* **Mitigation:** Upgrade to Groq's Pay-As-You-Go tier prior to public launch. At 5,000–10,000 requests/month, total primary spend is **under ~$11 to ~$17/month**, completely removing the capacity cliff.

### 5.2 Caller-Controlled Follow-up Transcripts
* `generate_answer` supports multi-turn follow-ups bounded by `MAX_HISTORY_MESSAGES = 20` and `MAX_MESSAGE_CHARS = 4000` (`utils/__init__.py`).
* **Typical turn:** 5 short messages ≈ 666 prompt tokens (prompt-only cost: $0.000050 Groq / $0.000200 Gemini).
* **Worst-case turn:** 20 × 4,000 characters ≈ **16,781 prompt tokens**.
* **Operational Consequence:** A single worst-case turn exceeds Groq's 8,000 TPM limit. When Groq returns an error, the request falls back to Gemini (prompt cost ~$0.0050) and succeeds rather than failing, but increases operational spend.

### 5.3 Fallback Architecture & Empty-Result Triggering
* When Groq fails or returns empty data, services automatically fail over to Gemini 2.5 Flash.
* In `utils/search_orgs.py`, failover triggers not only on API outages, but whenever Groq returns zero organizations (`len(results) == 0`). In the baseline run, 2 of 8 cases triggered this behavior, pulling the service mean from 2,163 to 3,767 tokens. Addressing empty-result triggering is the highest-leverage token optimization available.

---

## 6. Self-Hosting Feasibility (Resolution of Issue #23)

Issue #23 proposed self-hosting open models (e.g., on AWS EC2) to eliminate per-token API charges. The economics indicate this is currently unviable:

* **EC2 GPU Instance (`g4dn.xlarge` - 1x NVIDIA T4, 16GB VRAM):** On-demand price is ~$0.526/hour in `us-east-1`, totaling **~$378.72/month** regardless of traffic volume.
* **Breakeven Calculation:**
  ```text
  Breakeven Volume (Measured Mean: $0.0010818/req):
    $378.72 / $0.0010818 ≈ 350,074 requests/month (~11,670 requests/day)

  Breakeven Volume (Groq-Only: $0.0006696/req):
    $378.72 / $0.0006696 ≈ 565,591 requests/month (~18,850 requests/day)

  Historical Baseline Comparison ($0.00043305/req):
    $378.72 / $0.00043305 ≈ 874,541 requests/month (~29,150 requests/day)
  ```
* **Conclusion:** Self-hosting remains substantially more expensive than serverless API calls until platform traffic surpasses **~350,000 to ~565,000 help requests per month**. Furthermore, self-hosting introduces cold starts, GPU driver patching, auto-scaling overhead, and high-availability management that is impractical for a non-profit engineering team.

---

## 7. Model Strategy: Tiering vs. Single Frontier Model

Leadership requested: *"We should be using the latest and the greatest LLM model services at the cheapest price."*

Frontier models cost substantially more (10× to 50×) than open-weight lightweight tiers. A single frontier model across all microservices is financially inefficient because each microservice performs a fundamentally distinct task:

| Service | Real Task | Frontier Required? | Recommended Tier |
| :--- | :--- | :---: | :--- |
| `predict_category` | Choose from 7–13 options; JSON output | **No** | Small, fast open-weights (`gpt-oss-20b`) or classical ML classifier. |
| `generate_subject` | 1-line summary under 70 chars | **No** | Small, fast open-weights (`gpt-oss-20b`). |
| `emergency_contacts`| Country directory lookup | **No LLM** | Deterministic static dataset (zero hallucination risk). |
| `search_orgs` | Structured organization extraction | **No** | Small open-weights with retrieval grounding. |
| `generate_answer` | Empathetic, nuanced guidance | **Yes (conditional)** | Frontier or mid-tier model with reasoning capabilities. |

**Standing Policy:**
> Route each microservice to the lowest-cost model that satisfies its deterministic quality bar. Reserve frontier models strictly for services where reasoning and empathy directly touch the beneficiary (`generate_answer`).

---

## 8. Open Access Gaps

Operational inputs requiring cross-team coordination:

| Gap | Responsible Team / Reference | Current Status / Details |
| :--- | :--- | :--- |
| **Requests per User per Month** | Product & Request Teams | Tracked with a placeholder of **1.0 request/user/month** pending user analytics. |
| **AWS Lambda Configurations** | DevOps / AWS Cloud Administrator | Mustakim recorded live AWS Console readings on #153 (9 Sep 2026):<br>• `Predict Category`: 128 MB, 3 s<br>• `Generate Subject`: 128 MB, 30 s<br>• `Generate Answer`: 128 MB, 120 s<br>• `Search Orgs`: 512 MB, 30 s<br>• `Emergency Contacts`: 128 MB, 3 s<br>*Status:* Readings documented; formal DevOps re-confirmation pending. |
| **Provider Billing Tiers & Nonprofit Pricing** | DevOps / Account Administrator | Investigated in weekly AI meetings (Nov 2025; Saurabh's LLM comparison sheet with nonprofit pricing). Status: confirming whether educational/nonprofit grant credits are currently applied to Groq and Google accounts. |

---

## 9. Model Currency & Deprecation Audit

Every model named in code must be checked quarterly against provider deprecation logs:
* **Google Gemini API Deprecations:** [https://ai.google.dev/gemini-api/docs/deprecations](https://ai.google.dev/gemini-api/docs/deprecations)
* **Groq Supported Models:** [https://console.groq.com/docs/models](https://console.groq.com/docs/models)
* **Groq Deprecations List:** [https://console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations)

### Quarterly Currency Audit Log

#### Audit 1: 13 October 2026 (Reported by @shivam131284)

| Model Name | Code Location | Status as of 13 Oct 2026 | Deprecation / Sunset Schedule |
| :--- | :--- | :---: | :--- |
| `openai/gpt-oss-20b` | `config/model_routing.json`, `utils/client.py` | Active / Production | Production model; not on Groq deprecation list. |
| `openai/gpt-oss-120b` | `config/model_routing.json` | Active / Production | Production model; not on Groq deprecation list. |
| `openai/gpt-oss-safeguard-20b`| `config/model_routing.json` | Active / **Preview** | Listed under Preview Models on Groq; subject to sudden withdrawal. |
| `gemini-2.5-flash` | `config/model_routing.json`, `utils/client.py` | Active / GA | GA; no shutdown date announced on Gemini API deprecations page. |

#### Audit 2: 28 October 2026 (Live Provider Re-check)

| Model Name | Code Location (Commit `271a402`) | Status as of 28 Oct 2026 | Deprecation / Sunset Schedule |
| :--- | :--- | :---: | :--- |
| `openai/gpt-oss-20b` | `config/model_routing.json`, `utils/client.py:20` | Active / Production | Production model; verified active. |
| `openai/gpt-oss-120b` | `config/model_routing.json` | Active / Production | Production model; verified active. |
| `openai/gpt-oss-safeguard-20b`| `config/model_routing.json` | Active / **Preview** | Preview status unchanged. **Preview risk heightened:** PR #213 placed this model 3rd in the chain for answer generation as well as classification. |
| `gemini-2.5-flash` | `config/model_routing.json`, `utils/client.py:23` | Active / GA | "No shutdown date announced". |

*API Platform Clarification:* Saayam consumes Google models via the **Gemini API** (`ChatGoogleGenerativeAI` / `genai.Client` with an AI Studio API key stored in AWS SSM), **not** Google Vertex AI / Agent Platform. Retirement schedules specific to Vertex AI do not apply.

---

## 10. Governance & Review Rhythm

1. **Monthly Review Agenda:** A standing agenda item during the final weekly AI meeting of each calendar month:
   * Total token usage by service (extracted from CloudWatch `TOKEN_USAGE` logs).
   * Actual monthly spend versus volume projections.
   * Primary vs. fallback invocation split (detecting silent Groq degradation to Gemini).
   * Free-tier / rate-limit headroom.
2. **Quarterly Model Currency Review:** Review all model identifiers against provider deprecation schedules. Any model scheduled for retirement within 60 days must have a replacement PR opened immediately.
3. **Audit Freshness:** This documentation must display a **Last Reviewed** date. If the date is older than 30 days, the monthly review has lapsed.

---

## 11. Cost-Reduction Shortlist

The following optimization candidates are tracked. Reference the companion wiki guide: *[Cut Wasted AI Token Spend — Optimize AI spend](https://github.com/saayam-for-all/ai/wiki/Cut-Wasted-AI-Token-Spend-%E2%80%90-Optimize-AI-spend)*.

| Optimization Candidate | Expected Impact | Status | Notes |
| :--- | :--- | :---: | :--- |
| **Pin `reasoning_effort="low"` on Groq** | Eliminates reasoning token runaway | **Implemented (PR #212)** | Landed in production; contributing to ~21% whole-request token savings. |
| **Fix Empty-Result Fallback in `search_orgs`** | Reduces `search_orgs` mean from 3,767 to 2,163 tokens (~4× cost drop) | **Top Measured Target** | 25% of benchmark runs fell back to Gemini due to empty Groq result lists rather than API failure. |
| **Trim Organization Description Fields** | Reduces 20–40% of `search_orgs` completion tokens | **Unmeasured** | Requires cross-team alignment on the `ORGANIZATION_FIELDS` contract (#170). |
| **Enforce `MAX_MESSAGE_CHARS` Server-Side** | Prevents 25× caller-controlled prompt ballooning | **Risk measured, change pending** | Worst-case prompt turn measured at 16,781 tokens. Boundary check in `utils/__init__.py` pending. |
| **Deterministic Pre-Routing Expansion** | Cuts 2–3 model calls down to 1 call | **Unmeasured** | Measured on `elderly-medium` (1 call, 527 tokens). Can expand to other unambiguous domain terms. |
| **Groq Prompt Caching on Classification** | 50% discount on cached input ($0.075 → $0.0375/M) | **Unmeasured** | Automatic on `gpt-oss-20b`. Level-1 prompt (~330 tokens) exceeds minimum cacheable threshold. |

---

## 12. Telemetry Query (CloudWatch Logs Insights)

Token metrics are written to CloudWatch Logs under the `TOKEN_USAGE` prefix by `utils/token_usage.py` (Issue #159). To inspect usage across services in CloudWatch Logs Insights:

```sql
fields @timestamp, @message
| filter @message like /TOKEN_USAGE/
| parse @message "TOKEN_USAGE *" as body
| stats 
    count(*) as total_requests,
    avg(total_tokens) as avg_tokens,
    max(total_tokens) as max_tokens,
    sum(total_tokens) as sum_tokens
  by service
```

---

## 13. Scope Boundaries & Out of Scope

* **Token Instrumentation (Issue #159):** Instrumentation of services is owned by `utils/token_usage.py`. This document consumes that telemetry.
* **Model Fallback Implementation (Issue #193):** Fallback chain implementations are owned by PR #199 (`predict_category`) and PR #213 (`generate_answer`).
* **Implementation of Reduction Shortlist:** Optimizations in §11 are documented candidates for future review; each requires independent measurement and its own PR.
* **Commercial & Account Operations:** Negotiating nonprofit grant pricing with Groq or Google.
* **Non-AI Services:** Applies exclusively to Lambda functions in the `ai` repository.

---

## 14. Recommendations & Future Scope

1. **Fallback Traffic Alerting:** Configure a CloudWatch metric alarm alerting when Gemini fallback traffic exceeds **>5% of total requests** in any 1-hour window (detecting silent Groq outages or empty-result fallback cascades).
2. **Automated CloudWatch Custom Metrics via EMF:** Upgrading `TOKEN_USAGE` log emission to native CloudWatch Custom Metrics using `aws-lambda-powertools` Metrics utility, enabling out-of-the-box alerting without running parse queries.
3. **Dynamic Quality-Gated Model Routing:** Feeding cost and latency telemetry into the tiering policy outlined in §7 using curated golden evaluation sets.
4. **Empirical User Activity Forecasting:** Replacing the 1.0 request/active user/month placeholder with empirical analytics from the Request microservice once available.
