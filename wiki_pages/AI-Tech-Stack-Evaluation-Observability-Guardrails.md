# AI Tech Stack: Evaluation, Observability and Guardrails

*Stack 5 of issue [#197](https://github.com/saayam-for-all/ai/issues/197). Code on branch `ai-tech-stack/issue-197/eval-guardrails`. Applies to the Predict Category service.*

**In one line:** we can now measure whether category prediction gives the right answers, see in CloudWatch what it decided for every request, and catch two kinds of bad model output. The first measurement found that our own routing code makes three answers impossible to get right.

## What the three words mean

- **Evaluation** checks answer *quality* against a standard. We use a **golden set**: a fixed list of help requests, each with the category a person agreed is right. Run the classifier over it, count the right answers, compare with a pass mark. Normal tests check that code does what it was written to do. Evaluation checks that the model, driven by our prompt, still gives the right answers. A one-word prompt edit can pass every normal test and still break answers.
- **Observability** means seeing what the system did in production. We had logs of what each request *cost* (`TOKEN_USAGE`, from #159), but not of what it *decided*. So a long period where every request landed in General went unnoticed: an outage and a General answer looked the same.
- **Guardrails** are checks placed around the model. **Inbound** ones check what goes in; **outbound** ones check what comes out.

## How it works in our code

### Evaluation

| Piece | What it does |
| --- | --- |
| `evaluation/golden/classification.jsonl` | 45 requests. 41 are scored and cover every branch. 4 are **known gaps**, such as paying a bill or a car repair, which have no category in our taxonomy. They are run and shown, but never scored. |
| `tools/run_golden_set.py` | Sends every case through the **real** `predict_categories`: prompts, taxonomy walk, elderly routing and model fallback. It writes the score to `docs/metrics/`. About 90 model calls. |
| Pass mark | 90% of scored cases must have their first answer in the right branch, with no errors. A model is not deterministic, so the mark allows a borderline case to flip between runs. |
| **Fingerprint** | A hash of everything that decides the answer: every prompt, the model chain, sampling settings, the elderly-routing words, the code that parses the model's reply, and the labels. It is saved with each live result. |

The fingerprint is what makes this work in CI without calling a model. If someone edits the prompt, the saved score no longer matches the code, and `test_live_result_was_measured_on_the_current_classifier` fails until someone runs the evaluation again. We tested this: with `electrician` removed from the routing hint, every other test passes and this one fails.

### Observability

Every prediction, including one that fails, prints one `CLASSIFICATION_OUTCOME` line. It records:

- the outcome: `categorised`, `general`, `empty` or `error`;
- the top category and how deep it is;
- whether a fallback model answered;
- whether the elderly router fired;
- latency, model calls and tokens;
- the length of the description, **never its text**.

The line uses CloudWatch **Embedded Metric Format**, so CloudWatch creates the metrics itself, with no extra AWS call in the request. Three alarms are defined on top:

| Alarm | Fires when |
| --- | --- |
| General-or-empty rate | Over 50% of requests in an hour (minimum 10 requests) |
| Error rate | Over 20% of requests, three 5-minute periods in a row |
| Fallback rate | Over 50% of requests in an hour needed a model other than the primary |

There are also five saved Logs Insights queries: outcomes by hour, top categories, failures and fallbacks, latency and cost, and the share of requests the elderly router takes. `tools/setup_observability.py` creates all of these. It is a dry run unless given `--apply`.

### Guardrails

| Guardrail | Kind | What it does |
| --- | --- | --- |
| Duplicate category | Outbound | Keeps the first of any repeated category. The model once answered `[General, General, General]`. |
| Category not offered | Outbound | Drops an id that was not in the list we sent. This already existed; it is now counted. |
| Prompt injection | Inbound | Five narrow patterns: "ignore the previous instructions", a fake `System:` line, a forged `Categories:` block, a ready-made JSON answer, "you are now a…". **It only records.** The request goes ahead unchanged. |

Each firing prints a `GUARDRAIL` line, which CloudWatch counts per guardrail.

## What we found

1. **Our elderly router caps any model at 93%.** `is_elderly_context` in `utils/routing_for_categories.py` matches *substrings*, and when it matches, the model is offered only Elderly sub-categories. Three real-sounding requests are sent there:
   - "I am a **senior** in high school…"
   - "Our **aging** roof leaks"
   - "fix the **fall**ing gutter"

   We proved this offline. A perfect fake model, which always picks the right answer from what it is offered, still scores only 38 of 41. No model can fix this; the router has to.
2. **Live score: 36 of 41 (88%), below the 90% mark.** Three misses are the router. Two are model choices:
   - "house burned down, kids have no clothes" went to Housing;
   - "learn to cook healthy meals for my diabetic son" went to Health.

   For now, the test that checks the 90% pass mark is marked as a known failure, with the router given as the reason, so the suite stays green. Once the router is fixed and the evaluation rerun, that test will pass. The suite then fails on purpose until someone removes the "known failure" label, so the label can't be left behind.
3. **Fallback happens.** In the latest run, 3 of 87 model calls were answered by `gpt-oss-120b` instead of the primary model.
4. **The taxonomy has no finance or general transport category.** Bills, car repairs, taxes and a ride to a job interview land in Utilities, General or Career.
5. **Keyword rules misfire on real requests.** Our first injection rules flagged "can someone *act as* a mentor?" and "*pretend to be* my landlord so I can practise". That is why the injection check records instead of blocking. We need real traffic data before blocking anyone.

## Limitations

- **The labels need agreeing.** Two are debatable: `food-03` (cooking for a diabetic son: Food or Health?) and `general-01` ("going through a hard time": General or Mental wellbeing?). The gate is only as good as its labels.
- **41 cases is small.** One flipped answer moves the score by about 2.4 points.
- **The alarms are defined but not created.** Creating them needs AWS access and the Predict Category log group name.
- **Only Predict Category is covered.** Subject, answer and organisation search have no golden set yet.

## Next steps

1. Fix the elderly router: match whole words, and let the top-level model choose instead of skipping it. Then rerun the evaluation and remove the expected-failure marker.
2. Agree the labels, and grow the set to about 100 cases from real, anonymised requests.
3. Create the alarms in AWS and connect them to an SNS topic.
4. Watch the `GUARDRAIL` counts for a few weeks, then decide whether any injection rule should block.
5. Add a golden set for answer generation, which needs a different kind of scoring.

## Recording

*Link to the recording goes here once it is made.*
