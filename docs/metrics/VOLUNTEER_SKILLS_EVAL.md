# Volunteer skill suggestions: accuracy

Issue [#216](https://github.com/saayam-for-all/ai/issues/216) accepts
`"mode": "volunteer_skills"` at **recall ≥ 80% and precision ≥ 80% on two
consecutive runs**. This is that measurement.

**Verdict: both runs clear the bar.**

| Run | Cases | TP | FP | FN | Recall | Precision |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 59 | 89 | 3 | 7 | **92.7%** | **96.7%** |
| 2 | 59 | 86 | 1 | 10 | **89.6%** | **98.9%** |

No errors and no rate-limit retries in either run. Model: `openai/gpt-oss-20b`
on Groq at low reasoning effort, the first entry in `config/model_routing.json`.
Gemini was never reached, so the fallback leg of the chain is unmeasured here.

Raw per-case output: [`volunteer_skills_eval.json`](volunteer_skills_eval.json).

## Reproducing it

```bash
python tools/measure_skill_suggestion_accuracy.py
```

About 40 minutes. The development Groq key is capped at 8,000 tokens/minute and
a call costs ~2,700, so the harness sleeps 20s between cases and backs off on a
429. Running it faster does not produce a different number, it produces
throttling that scores as model failure.

## What is being counted

The unit is a **skill**, not a category ID. Each case in
[`volunteer_skills_eval_set.json`](volunteer_skills_eval_set.json) labels the
skills the volunteer stated, and each skill carries a set of acceptable IDs,
because parts of the taxonomy say the same thing twice — 5.1.1 General
Consultation against 5.1.11 Other Medical Concern, 6.5 Errands Events
Transportation against 6.6 Transportation Appointments Events, 5.4 Medication
Reminders against 6.3 Medication Management. A model that picks either is
right, and scoring it wrong would measure the taxonomy rather than the model.

- **true positive** — a labelled skill matched by a predicted ID
- **false negative** — a labelled skill no prediction matched
- **false positive** — a predicted ID left over once skills are matched

Skills are paired to predictions by maximum bipartite matching, so the score
does not depend on the order the labels happen to be written in. Totals are
micro-averaged. The rules are in `tools/skill_eval_scoring.py` and are unit
tested in `tests/test_skill_eval_scoring.py`.

## The set

59 descriptions, 96 labelled skills, written for this measurement. **None of
them is one of the ten V1–V10 cases in the issue.** Those cases were the inputs
the prompt was designed against — commit `f28d9ed` removed the dentist example
from the prompt for exactly this reason — so scoring against them would measure
the prompt against itself. Situations are deliberately echoed; wording is not
reused. `tests/test_skill_eval_dataset.py` enforces this and the composition
below.

| Trait | Cases | R1 recall | R1 prec. | R2 recall | R2 prec. |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `short` | 7 | 100.0% | 100.0% | 100.0% | 100.0% |
| `multi_area` | 11 | 94.4% | 97.1% | 91.7% | 100.0% |
| `contains_retired` | 6 | 90.0% | 100.0% | 90.0% | 100.0% |
| `non_english` | 7 | 92.3% | 92.3% | 92.3% | 100.0% |
| `long` | 3 | 80.0% | 92.3% | **73.3%** | 91.7% |
| `no_match` | 5 | n/a | n/a | n/a | n/a |
| `unmatched_skills` | 5 | 100.0% | 100.0% | 100.0% | 100.0% |

Buckets overlap and do not sum. `no_match` cases have no labelled skills, so
recall and precision are undefined for them — see below.

### The three findings worth acting on

**Short professional statements are fixed.** The issue's root cause 4 was that
"I'm a dentist" fell to General at 0.99 confidence. All 7 `short` cases score
100% on both runs. Root cause 2 is fixed too: all 6 `contains_retired` cases
return the volunteer's actual skills, none are routed into Elderly Care.

**Nothing is invented for a description that states no skill.** 0 of 5
`no_match` cases produced a suggestion, across both runs. This is tracked
separately because neither headline number can see it: a no-match case has no
labelled skills, so it cannot lower recall, and its false positives would be
diluted across 59 cases. "I am free most weekends" returning three confident
suggestions is what a volunteer would actually be shown, so it gets its own
number.

**Long descriptions are the weak bucket.** `long` is the only trait under 80%
on either run (73.3% in run 2). With 3 cases this is a weak signal, not a
finding — but it is the one place the set says "look here", and the mechanism
is visible in the failures below: the model returns 4 solid suggestions for a
description that supports 5, and stops.

## Every failure

Six of the eight failing cases fail in **both** runs, so these are systematic,
not sampling noise.

| Case | Run | What was missed | What came back instead |
| :--- | :--- | :--- | :--- |
| `senior-carpenter-handyman` | both | handyman (3.3.2) | 3.3.4 only — "carpentry and small repairs" consolidated into one skill |
| `de-pflege-termine` | both | nursing (5.1.1/5.1.11) | transport only; "Ich bin Krankenpfleger" not mapped |
| `long-teacher-career` | both | test prep (4.3.5) | 4 of 5 skills, cleanly; the fifth just not returned |
| `long-community-health` | both | general consultation, emotional support (+ health education in R2) | 5.1.5 Cardiac Or Blood Pressure |
| `nurse-listener-prescriptions-driver` | both | R1: nothing; R2: emotional support, transport | R1 returned both 6.5 *and* 6.6 |
| `physio-meal-plans-visits` | both | R1: social connection; R2: meal planning | 2 of 3 either way, a different 2 each run |
| `mason-maths-groceries` | R1 | grocery shopping (1.2) | 2 of 3 |
| `selling-furniture` | R2 | selling things (3.10) | **nothing at all** |

Three things these failures say:

1. **The dominant failure is under-returning, not mis-returning.** Precision is
   96.7% and 98.9%; almost every miss is a skill the model simply did not list,
   on a description where it listed the others correctly. The cap of 6 is not
   binding — the longest answer returned was 5.

2. **The near-duplicate categories cut both ways.** In run 1 the nurse case
   returned *both* 6.5 and 6.6 for one stated skill; one matched and the other
   scored as a false positive. The model is not wrong — the taxonomy offers the
   same thing twice — but it cannot win: hedging costs precision, choosing
   costs nothing only if it guesses the labelled side. 2 of the 4 false
   positives across both runs come from this.

3. **`selling-furniture` returned an empty list in run 2** for "I help people
   sell furniture they no longer need", having answered it correctly in run 1.
   A total non-answer on a one-skill case is a different failure from an
   incomplete answer, and worth watching if the prompt changes.

## Caveats, stated plainly

- **59 self-labelled cases show a direction; they do not prove an accuracy
  figure.** I wrote both the descriptions and the expected answers.

- **Accept-sets make the score more forgiving than strict matching would be.**
  Widening them further would raise the number without changing the behaviour
  the volunteer sees.

- **One failure is arguably a label problem, and I have deliberately not fixed
  it.** In `long-community-health` the model returned 5.1.5 Cardiac Or Blood
  Pressure, and the description does say "I take blood pressure readings and
  talk people through what the numbers mean". That is a defensible suggestion
  that my label scores as a false positive, and it is the same case that misses
  two skills, so correcting it would improve both numbers. Changing a label
  after seeing the output is how an evaluation set stops measuring anything, so
  it stands as written. If the team agrees 5.1.5 belongs, the change should be
  made and **both runs re-run**, not retro-scored.

- **The Gemini fallback is unmeasured.** No run reached it. These numbers
  describe `gpt-oss-20b` alone.

- **Recall rests entirely on the first model.** `suggest_skills` treats any
  well-formed response as valid, including `{"skills": []}`, so a weak answer
  is never retried against the next model in the chain. That is a deliberate
  choice — an empty list is a legitimate "no match" — but it means the figures
  above are a property of one model, and `selling-furniture` returning nothing
  in run 2 is a case where a retry would have helped.

## Cost

| | |
| :--- | ---: |
| Mean tokens per case | 2,684 |
| Per run (59 cases) | ~158,000 |
| Model calls per request | 1 |

In line with the ~2,430 the issue estimated. The prompt is the bulk of it: the
69-category list is fixed and identical on every request, which is why it sits
in a separate system message where provider-side caching can reach it.
