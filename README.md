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

[`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md) turns that list into a map: how a request travels, which Lambda owns which modules, and where the whole thing tends to fail. Mission 2.5 is where you read it.

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

**If you get back an empty list, that is real, not a broken setup.** For a prompt carrying this many categories, the model occasionally returns nothing at all, the same phenomenon described under "Structured output" further down. The sandbox prints a warning and returns `[]` rather than inventing three categories to fill the gap. Run it again and it will usually answer. Noticing the difference between "no answer" and "a confident wrong answer" is most of the job here.

---

## Mission 2: Run the real thing

**Win condition:** you get a category, a confidence score and a hierarchy path for your own sentences.
**Time:** about an hour.

The sandbox is a toy. Switch to `dev` for the real code. The services normally read keys from AWS Parameter Store, which you do not have access to, so the harness injects your Groq key the same way and the rest of the code path is unchanged.

**Bring the self check with you.** `onboarding_check.py` is tracked on the `NewJoineeTask` lineage, not on `dev`, so `git checkout dev` deletes it. That is deliberate: `dev` is the protected branch carrying the deployed service, and joiner tooling does not belong in the package that ships to Lambda. Switch first and copy it back afterwards, doing it the other way round does not work, because the checkout removes the copy you just made. It then sits in your working directory as an untracked file for the rest of onboarding.

```bash
git checkout dev
git show NewJoineeTask:onboarding_check.py > onboarding_check.py
pip install -r requirements.txt
python onboarding_check.py -i
```

`git status` on `dev` will now list `onboarding_check.py` and `onboarding_answers.py` as untracked. Expected. Do not commit them, and delete them when you are finished. Everything else in this README you can read from the GitHub page for the `NewJoineeTask` branch while you work on `dev`.

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

## Mission 2.5: Draw the system

**Win condition:** you can say where a change goes, and what it can break, without opening five files to find out.
**Time:** about an hour.

Running one classifier tells you one service works. It does not tell you how a request reaches it, which other services share its fate, or where the failure modes live. [`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md) is the map: the request path as a diagram, a table of which Lambda owns which modules, the two hosting paradigms and why both exist, a table of where things fail, and the one path a secret takes from Parameter Store into `utils/client.py`.

Like this README, the map is tracked on `NewJoineeTask`, so read it from the GitHub page for that branch while your checkout sits on `dev`.

Read it, then use the tests to check it against reality:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

No API keys and no AWS credentials are needed. Then pick one **contract** test, `docs/testing/TEST_CATALOGUE.md` says which files those are, and `tests/test_response_contract.py` is the best first one, and read it end to end. Contract tests mirror what the browser actually sees, so they are the fastest correct answer to "what does this endpoint return?".

**Work out the answers to these, you will need them for the self check:**

1. `lambda_handler` in `lambda_function.py` dispatches to how many services?
2. Which contract test did you read, and what behaviour does it protect? What would break for the web client if it started failing?

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

This incident is not a one-off anecdote. It is two rows of the failure table in [`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md) happening at once, a provider-layer failure, and a client-side default that renders the result as something milder than an outage. Find them, and check your answers against the rest of that table: which other rows could have produced the same report?

---

## Mission 4: Make the model call a tool

**Win condition:** the model answers "what do I dial for a fire in Japan" by calling your function, not by remembering.
**Time:** two to three hours.

Every service in this codebase is single shot: prompt in, text out, parse. That is not how the rest of the field works any more, and it is not how you would build the emergency lookup if you started today. The model does not need to know 73 countries. It needs to know when to ask.

`services/emergency_numbers.json` is keyed by ISO alpha-2 country code, and each country carries a `default` map of services:

```json
"AU": { "default": { "general_emergency": "000", "police": "000",
                     "ambulance": "000", "fire": "000" }, "states": {} }
```

Create `agent_tools.py` with a **tool schema**, a JSON Schema description of one function in the shape providers expect, and the **function itself**, `lookup_emergency_number(country, service)`, which reads the shipped dataset and never calls a model. The schema's description is a prompt: write it for a reader who has never seen your data.

Then wire the loop by hand, without a framework. Send the question plus your schema to Groq; if the response asks for a tool call, **validate the arguments before you execute anything**; run the function; send the result back as a tool message; let the model answer from it.

**The trap.** The model's arguments are untrusted input that happens to have arrived from a model instead of a browser. It will confidently pass `"Japan"` where your data expects `"JP"`, and it will invent country codes that do not exist. If your function reaches the dataset before you have checked the arguments, you have built an injection point.

**A real example.** Organization search asks a model for phone numbers it has no way to know, and it answers anyway: every number in a live run came back in the `555` block that North America reserves for fiction. A model will always rather answer than decline. Your validation layer is what turns that from a defect into a `404`.

**What the self check looks for.** `agent_tools.py` exporting `TOOL_SCHEMA`, a dict with `name`, `description` and `parameters`, where `parameters` is a JSON Schema object whose `properties` include `country` and `service` and whose `required` is non-empty; and `lookup_emergency_number(country, service)` returning a string or `None`. Two behaviours are easy to miss. **The function itself must never raise**, whatever it is handed, because validating inside your loop does not protect the function from its next caller. And **a service we do not model must return `None`** rather than another service's number: ask yours for `poison_control` and see. That second one is issue #146 in miniature.

**What to notice, and this is the real lesson.** Grounding the lookup does not ground the answer. A working run of this mission produced exactly the right tool call, `{"country": "JP", "service": "fire"}`, got the correct `119` back, and then wrote:

> In Japan, you dial **119** for fire emergencies (as well as for police and medical emergencies).

Japan's police number is **110**. The model was handed one verified fact and volunteered a second, wrong one alongside it, in the same confident sentence. Nothing in the tool layer can catch that, because the tool layer did its job. Read your own final answers, not just your tool calls.

Then compare the tokens and latency of the tool path against asking the model directly, and answer the question this mission is really about: for a lookup over 73 fixed rows, does a model belong in the request path at all?

---

## Mission 5: Measure something, then stop doing it by hand

**Win condition:** you can break a prompt on purpose, and your harness tells you it got worse before you look at any output.
**Time:** four to five hours.

`dev` has 278 tests and 68% coverage. Not one of them tests whether an answer is any **good**. Every quality regression this team has shipped was invisible to a green suite, because correctness of shape and correctness of content are different questions.

### Part 1: by hand, once

Read the prompt in `utils/subject_generator.py`. It is unusually specific, and every rule exists because a real output was wrong in a real way.

1. Write 15 to 20 descriptions with the subject you think each should produce. Include hard cases: two symptoms at once, an uncertain cause, a stated timeframe.
2. Run the current prompt over them and score it by hand. Define your own metrics. Ours include: does it keep the stated details, does it invent anything, does it stay in the length limit, does it read as the person's concern rather than a diagnosis.
3. Change **one** thing. Re run and compare.

**The trap.** Most people change five things at once, see improvement, and cannot say which change did it.

**A real example.** An early version of this prompt used an example written as `Subject: Ear Congestion`. That formatting alone taught the model to prepend "Subject:" to its output. It got worse, and only an A/B comparison caught it. There is now a `_clean_subject` function as a safety net and guard tests so it cannot silently regress.

By the end of part 1 you will have scored something by hand twice and found it tedious. That is the point.

### Part 2: make it repeatable

Create an `evals/` directory with a **golden set** of 30 or more inputs and expected outcomes, including the hard cases from part 1, a language other than English, and an input that should produce nothing at all; **metrics you can defend**, because exact match is rarely the right one; a **runner** that scores a prompt and prints a number; and a **control**, a deliberately worse prompt committed alongside the good one.

**The trap.** Building the golden set out of the examples you used while writing the prompt. You will score beautifully and learn nothing. Hold cases back before you start tuning.

**If you use a model as a judge**, validate the judge first. Score 20 items yourself, score them with the judge, and report the agreement rate. An unvalidated judge is a second unmeasured model in your measurement pipeline.

**What the self check looks for.** `evals/run.py`, or `evals_run.py` if you would rather not make a directory, exporting `GOLDEN` with 30 or more cases, `PROMPT` and `CONTROL_PROMPT`, and `run(prompt)` returning a dict with a numeric `score`. It runs your harness over both prompts and fails if the real one does not score higher than the control. That is the whole check: a harness that cannot tell a good prompt from a deliberately bad one is not measuring anything, however elegant the code.

A well measured negative result is a good result. Put what you found in your observations.

---

## Mission 6: Ground an answer in data you did not write

**Elective.** Skip it and the self check will say so rather than mark you down.
**Win condition:** every organization you return can be pointed at a specific line in a file you did not author.
**Time:** four to six hours.

`utils/search_orgs.py` asks a model for organization names, phone numbers, addresses, and a `source` URL that exists to demonstrate legitimacy. All of it is generated. In a live run it returned six organizations whose numbers were `(408) 555-0101` through `555-0606`, addresses at `123 Main St` and `456 Oak Ave`, and Charity Navigator links with `orgid=12345`. The `source` field, whose entire job is to prove the organization is real, is itself invented.

Create `grounded_orgs.py`. Get real data, a ProPublica Nonprofit Explorer extract or an IRS Business Master File slice, a few thousand rows is plenty; the team already has `ProPublica_data` and `irs_data_subcategorization` functions deployed, so ask your buddy before you build a fourth copy. Index it, with embeddings and cosine similarity or with keyword matching, and measure the difference; both are legitimate, and knowing which one you needed is the skill. Then retrieve first and generate second: the model selects and explains from what you retrieved, it does not add fields. Cite everything. And when nothing matches, return nothing.

**The trap.** Retrieving correctly and then letting the model tidy up the results. It will fill a blank phone number, correct a name it thinks is misspelled, and round a rating. Once generated text and retrieved text share a field, you cannot tell them apart, and neither can the volunteer who dials the number.

**What the self check looks for.** `grounded_orgs.py` exporting `search(query, location)`, returning a list of dicts each carrying at least `source_id` and `contact`, and `source_record(source_id)` returning the underlying record or `None`. It asserts every `source_id` resolves, that no `contact` carries a reserved-for-fiction `555` number, that a query your data can answer returns something, and that a nonsense query returns nothing. The first and last matter most: a search that always returns an empty list would satisfy every other rule, and a citation that does not resolve is a generated organization wearing a badge.

**What to notice.** Your grounded version will return fewer organizations than the current one, and some queries will return none. That is the correct outcome, and explaining why to somebody who wanted six results is part of the job.

---

## Mission 7: Run the self check

```bash
python onboarding_check.py
```

The first run creates `onboarding_answers.py`. Fill it in, run again. It checks:

- **Setup**, Python version, packages, key available
- **Safety**, your `.env` is not tracked by git, no key hardcoded in any `.py` file
- **It runs**, a real model call succeeds and classification returns a real category
- **Reading the code**, your answers verified against the actual code, not against a stored answer key, including the router's service count, parsed out of `lambda_function.py`, and the contract test you read, looked up in `tests/`
- **Missions 4 to 6**, the code you wrote, imported and run. Your tool schema and lookup, your eval harness scored against its own control, and your grounded search if you did the elective
- **Understanding**, your written root cause, prevention, observations and feedback

Run it on `dev`, with the copy you carried across in Mission 2. Ten of the checks read the real service or your own modules and can only run there; on the sandbox branch they report that, and say so in the same words.

It prints a checklist, then two lists: what you got wrong, and what you have not reached yet. Nothing is uploaded.

### One last thing, and it is the point of the whole flow

When the mission checks pass, read the worked example:

```bash
git show NewJoineeTask:worked_example/agent_tools.py
```

It satisfies every check in the self check. **It is also wrong in at least three ways.** Find them, and say which one you would fix first and why. The hint is the same one that runs through everything here: what can a user ask for that this cannot answer?

The answers are in `worked_example/README.md`, so do not open that first. Twenty minutes.

There is no gate on any of this and nobody is checking whether you looked early. It is worth very little in advance, because you cannot see what is wrong with an implementation until you have written one. What you should take from it is the thing three of our incidents had in common: **passing the tests is not the same as being right.**

When both lists are empty and you have hunted the defects, tell your onboarding buddy and bring your feedback answer to your first standup.

The feedback question is not a formality. You are the last person who will see this with fresh eyes, and every confusing thing you hit is a thing we can fix for the next person. Say what you tried that did not work, as well as what did.

---

## After onboarding: pick a direction

These map to work we actually need done.

**Prompting and evaluation.** Output accuracy and safety, evaluation sets, catching regressions. Opening question: how would you detect a quality drop automatically, without a human noticing?

**Retrieval and matching.** Embeddings, semantic similarity, volunteer matching, search. Opening question: how would you match "I need groceries" to a volunteer whose listed skill is "food distribution"?

**Reliability and platform.** Fallback chains, configuration management, monitoring, CI/CD, cost tracking. There is an open ticket for automatic model fallback that came directly out of Mission 3.

**Agent loops and budgets.** Some requests do not carry enough to classify. "I need help with my car" could be repair, transport or insurance. A loop can ask a clarifying question; the hard part is stopping. Issue #158 is this. Opening question: what stops your loop, and how do you know what it cost you? A run cut short by its budget must say so, because presenting a truncated run as a finished one is the Mission 3 failure in a new costume.

**Tools over MCP.** The Model Context Protocol is how a model gets tools from an external process rather than from your application code. Issue #161 is an open evaluation spike. Opening question: what does this buy over the in-process tool call you wrote in Mission 4, and what does it cost? A one word answer either way means you have not used it.

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
