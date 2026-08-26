# GenAI Team Onboarding

Welcome. This is not a reading assignment. It is a set of missions that take you from "I cloned the repo" to "I understand what this team does and I can work on it".

When you think you are finished, run `python onboarding_check.py`. It tells you what you have completed and what is still outstanding. That is the whole assessment. **You are not required to open a pull request to finish onboarding.**

Work at your own pace. Most people take one to two weeks part time. Nothing here needs AWS access, which is deliberate, because you will not have it on day one and most of the team does not either.

---

## Part 0: Where we are and what we own

**We work on `dev`.** This is a live project but it is not a finished production system. Things break, branches are half built, and a lot of what you will read is work in progress. That is normal, and it is why there is real work for you.

### The team's scope is wider than it first looks

Five Lambda services are the most developed part, but they are not the whole team.

**Understanding what someone wrote**
- Predict Category, mapping a request onto a deep hierarchical taxonomy
- Generate Subject, turning a description into a faithful short title
- Intent interpretation, improving how accurately we read what a request actually needs

**Generating a response**
- Generate Answer, drafting helpful replies per category
- A conversational chatbot, in progress on its own branches
- Multilingual work, including translation and voiceover, still at evaluation stage

**Matching and search**
- Volunteer matching, connecting requests to the right volunteers, with both semantic and fuzzy matching approaches explored
- Universal and AI assisted search across requests, users and organizations

**Knowledge and data**
- More Organizations, suggesting real organizations that can help
- Summarizing user file attachments
- Data lake design
- Emergency Contacts, returning correct emergency numbers per country

**Platform and reliability**
- CI/CD and deploys
- Token usage and cost tracking
- Moving hardcoded configuration into config and Parameter Store
- Test coverage
- Evaluating newer tooling such as MCP

You are not expected to touch all of this. You are expected to know it exists, because the interesting problems usually sit between two of these areas.

### The thread running through all of it

Almost every service here has the same property: **a plausible sounding wrong answer is worse than no answer.** A made up organization, a wrong emergency number, a subject line that reads like a medical diagnosis, a volunteer matched to something they cannot help with. Hold onto that idea. It explains most of our design decisions.

### Where the code lives

```
lambda_function.py              the service handlers, one entry point each
services/classification_service.py   category prediction, hierarchical descent
services/emergency.py           emergency contacts lookup
utils/client.py                 model and API key setup, reads AWS Parameter Store
utils/subject_generator.py      subject line generation
utils/search_orgs.py            organization search
utils/prompts.py                answer generation prompts
utils/categories*.py            the category taxonomy
utils/predict_category_list.py  taxonomy helpers
```

`dev` is the branch that matters. `NewJoineeTask` is the simplified sandbox in Mission 1. Other branches are feature work in varying states of completeness. Browsing them is a legitimate way to see what the team is doing.

---

## Mission 1: Get something running

**Win condition:** you call an endpoint and get sensible output.
**Time:** about an hour.

You need Python 3.11+, git, and a free Groq API key from https://console.groq.com.

```bash
git clone https://github.com/saayam-for-all/ai.git
cd ai
git checkout NewJoineeTask
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then put your key in it
python app.py
```

```bash
curl -X POST http://localhost:8000/predict_categories \
  -H "Content-Type: application/json" \
  -d '{"subject":"Need help finding a job","description":"Looking for entry level software roles."}'
```

**Rules that matter from minute one.** Your key goes in `.env` and nowhere else. Never hardcode a key in a `.py` file. Never commit `.env`. This is not hypothetical: an AWS key was once committed to this repo, and cleaning that up is far more painful than doing it right the first time. The self check verifies both of these.

Try an ambiguous description, like "I need help with my car". Is the answer right? Is a right answer even available in the taxonomy?

---

## Mission 2: Run the real thing

**Win condition:** you get a category, a confidence score and a hierarchy path for your own sentences.
**Time:** about an hour.

The sandbox is a toy. Switch to `dev` for the real code. The services normally read keys from AWS Parameter Store, which you do not have access to, so a local harness injects your Groq key the same way and the rest of the code path is unchanged.

```bash
git checkout dev
pip install -r requirements.txt
python local_dev_harness.py -i
```

Try these, and note what happens:

- `I need help with math`
- `my apartment has a bad plumbing leak and no heat`
- `my car broke down and I cannot afford the repair`
- something ambiguous of your own

**Work out the answers to these, you will need them for the self check:**

1. Which file defines the category taxonomy?
2. How many top level categories are there? There is a helper in `utils/predict_category_list.py`.
3. Which function in `lambda_function.py` handles category prediction?
4. The plumbing example returns two categories with close confidence. Which, and why is that reasonable?
5. The car example returns General. Bug or correct behaviour? Defend your answer.

---

## Mission 3: The case file

**Win condition:** you can explain the root cause in your own words.
**Time:** two to three hours.

This is real. It happened in August 2026, it took the service down, and the postmortem is in the CAPA repository.

**The report:** "Every help request is being categorised as General. This used to work."

**What you know:**
- The frontend defaults to General when categorisation returns nothing
- No code in the categorisation path had changed for months
- Two other services were failing at the same time
- Nothing alerted anyone. A human noticed.

**Investigate before reading the answer.** Some starting points:

```bash
grep -rn "model" services/classification_service.py utils/client.py
git log -p -L 15,20:services/classification_service.py
```

Work out:
1. What was the trigger?
2. Why did one failure take down several services at once?
3. Why did it look like mild misclassification instead of an outage?
4. Why did the fix take weeks rather than minutes?
5. Which single change would have reduced the damage most?

Then read the CAPA entry and compare it with your analysis. Where you disagree, say so. We would rather have the argument than the agreement.

**Why this matters:** the interesting failures in applied AI are rarely the model being wrong. They are configuration living in code, silent fallbacks, missing observability, and deploy pipelines nobody tested.

---

## Mission 4: Measure something

**Win condition:** you changed one thing and can say, with numbers, whether it helped.
**Time:** two to four hours.

Read the prompt in `utils/subject_generator.py`. It is unusually specific, and every rule exists because a real output was wrong in a real way.

1. Write 15 to 20 descriptions with the subject you think each should produce. Include hard cases: two symptoms at once, an uncertain cause, a stated timeframe.
2. Run the current prompt over them and score it. Define your own metrics. Ours include: does it keep the stated details, does it invent anything, does it stay in the length limit, does it read as the person's concern rather than a diagnosis.
3. Change **one** thing.
4. Re run and compare.

**The trap.** Most people change five things at once, see improvement, and cannot say which change did it.

**A real example.** An early version of this prompt used an example written as `Subject: Ear Congestion`. That formatting alone taught the model to prepend "Subject:" to its output. It got worse, and only an A/B comparison caught it. There is now a `_clean_subject` function as a safety net and guard tests so it cannot silently regress.

A well measured negative result is a good result. Put what you found in your observations.

---

## Mission 5: Run the self check

```bash
python onboarding_check.py
```

The first run creates `onboarding_answers.py`. Fill it in, run again. It checks:

- **Setup**, Python version, packages, key available
- **Safety**, your `.env` is not tracked by git, no key hardcoded in any `.py` file
- **It runs**, a real model call succeeds and classification returns a real category
- **Reading the code**, your answers verified against the actual code, not against a stored answer key
- **Understanding**, your written root cause, prevention, observations and feedback

It prints a checklist and what is outstanding. Nothing is uploaded. When you reach the end, tell your onboarding buddy and bring your feedback answer to your first standup.

The feedback question is not a formality. You are the last person who will see this with fresh eyes, and every confusing thing you hit is a thing we can fix for the next person.

---

## After onboarding: pick a direction

These map to work we actually need done.

**Prompting and evaluation.** Output accuracy and safety, evaluation sets, catching regressions. Opening question: how would you detect a quality drop automatically, without a human noticing?

**Retrieval and matching.** Embeddings, semantic similarity, volunteer matching, search. Opening question: how would you match "I need groceries" to a volunteer whose listed skill is "food distribution"?

**Reliability and platform.** Fallback chains, configuration management, monitoring, CI/CD, cost tracking. There is an open ticket for automatic model fallback that came directly out of Mission 3.

When you are ready for a first change, look for a small issue and talk to your buddy before starting. Small and reviewed beats large and unreviewed.

---

## The concepts we actually use

**Prompting.** Specific beats polite. Every rule in a production prompt should trace to a real failure. Examples teach format as strongly as content, which cuts both ways.

**Structured output.** We ask for JSON so code can consume it. Providers offer a JSON mode that constrains output. It is not free: with some reasoning models, JSON mode plus a long prompt returns empty output unless you also lower the reasoning effort. We hit exactly this and it cost a day.

**Model selection.** Bigger is not automatically better. We benchmarked six models on our real prompts and chose a small one that was fully accurate at 0.27 seconds over a larger one at 0.50 seconds.

**Temperature.** Classification wants low and repeatable. Generation tolerates more variation.

**Fallbacks.** Every external call fails eventually. Silent fallbacks are dangerous: if one quietly returns nothing and the UI shows a default, users see a plausible wrong answer and nobody notices.

**Evaluation.** Without a held out set and a metric, prompt engineering is guesswork with confidence.

**Embeddings and semantic search.** Text as vectors, similarity as distance. Central to volunteer matching and search.

**RAG.** Grounding answers in retrieved documents rather than model memory. Directly relevant, since inventing an organization that does not exist is a serious failure.

**Cost and latency.** Both are user facing. A category prediction that takes eight seconds is a broken form however accurate it is. This is why token tracking is real work here.

---

## Reference

**Gotchas**

- Groq "Access denied, please check your network settings" is a regional or VPN block, not a bad key. A bad key returns 401. Toggle your VPN or switch networks. A VPN also adds latency and will ruin your benchmarks.
- `model_not_found` means the provider retired the model. That is Mission 3.
- If `dev` fails to import, ask before debugging your environment. It has been broken by bad merges before.
- Parameter Store lives inside AWS Systems Manager and everything is region specific. Ours is us-east-1.

**Getting help.** Ask early. A question after 30 minutes stuck is efficient. A day lost to something answerable in one sentence is not. There are no stupid questions in your first month.

**What we expect.** Curiosity about why something broke, not just that it broke. Measuring rather than assuming. Saying "I do not know" early. Nobody expects you to know generative AI, AWS and this codebase on day one. Everyone here learned it here.
