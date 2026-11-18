---
episode: 2
title: "One request, end to end (`predict_category`)"
status: draft
script_verified_against: "271a40216cd3469784bb462536cfc4d05ff42bd4"
recorded_against: "TBD — set immediately before recording"
source_files:
  - lambda_function.py
  - services/classification_service.py
wiki_owner:
  - "Help Request Classification Design"
last_verified: "2026-11-02"
target_runtime: "under 7 minutes"
---

# Episode 2 — One request, end to end (`predict_category`)

## Purpose

Follow one help-request description through the running category-prediction
path: from a live request, through routing and hierarchical classification, to
the response body and its matching CloudWatch usage record.

This episode explains the stable request flow and why classification descends
the taxonomy one level at a time. Changing implementation details belong to
the **Help Request Classification Design** wiki page.

## Governing rule

Do **not** say model or provider names, Lambda memory or timeout settings,
category counts, taxonomy depth, test counts, line numbers, endpoint lists,
token counts, or other volatile values aloud.

When a changing value is visible, refer to its role instead:

- "the configured model chain"
- "the current candidate categories"
- "the next taxonomy level"
- "the classification response"
- "the usage record"

End the episode by directing viewers to the **Help Request Classification
Design** wiki page for current taxonomy and model details.

## Recording prerequisites

Before recording, confirm with the team lead that you have:

- the approved development API URL and request format;
- the approved authentication method, if the endpoint requires one;
- read-only access to the relevant CloudWatch log group;
- permission to show the selected request and log record;
- the organisation's recording and publishing instructions.

Do not record credentials, authorization headers, secret values, environment
files, AWS account details, or private request data.

If approved API or CloudWatch access is unavailable, stop after script review.
Do not replace the required running-system evidence with slides or fabricated
output.

## Safe demonstration request

Use a fictional, non-sensitive description approved by the reviewer. The
examples below use:

> Need help with tutoring in math.

Set the approved URL outside the visible recording area. If authentication is
required, use the team's approved method without displaying the credential or
placing it in recorded shell history.

~~~bash
curl -sS -X POST "${PREDICT_CATEGORY_URL}" \
  -H "Content-Type: application/json" \
  --data '{"description":"Need help with tutoring in math"}' \
  | python -m json.tool
~~~

Adjust the request only if the approved development endpoint requires a routing
field or another documented envelope. Verify the exact command before
recording.

## Recording plan

### Scene 1 — Introduce the request path

**Timing budget:** 0:00–0:35

**On screen**

Show the fictional request text in the terminal, then briefly show
`lambda_function.py` and `services/classification_service.py` in the repository
tree.

**Narration**

> In this episode, I will follow one help request through category prediction.
> We will send a real request, follow the code that routes and classifies it,
> inspect the response body, and match it to the service's usage record in
> CloudWatch.

> The recording focuses on the stable path. The maintained wiki owns changing
> details such as the taxonomy and model configuration.

### Scene 2 — Send a live request

**Timing budget:** 0:35–1:15

**On screen**

Run the approved `curl` command against the development endpoint. Keep the
terminal output visible, but save the response walkthrough for Scene 6.

**Narration**

> This is a fictional help request sent to the running development service.
> The useful input for classification is its description. The response has
> arrived; before reading it, let us follow the path that produced it.

### Scene 3 — Route to the category handler

**Timing budget:** 1:15–2:05

**On screen**

Open `lambda_function.lambda_handler`. Highlight how it obtains the requested
service and dispatches category prediction to `predict_category_handler`.

Then open `lambda_function.predict_category_handler`.

Do not mention or highlight line numbers. Avoid narrating the complete service
list.

**Narration**

> The unified handler first determines which service the caller requested. For
> this request, it dispatches to the category-prediction handler.

> The handler accepts the API Gateway body in its supported forms, extracts the
> description, and rejects a request that has no description. A valid
> description is passed to the classification service.

### Scene 4 — Start with immediate candidates

**Timing budget:** 2:05–3:10

**On screen**

Open `GroqClassificationService.predict_categories`, then
`GroqClassificationService._walk_taxonomy` in
`services/classification_service.py`.

Highlight:

- creation of a per-request usage accumulator;
- retrieval of the top-level candidates;
- the loop over the current candidate set.

Do not narrate the concrete category IDs, number of categories, taxonomy depth,
or model configuration.

**Narration**

> The classification service creates one usage accumulator for the request and
> starts with the taxonomy's immediate candidates.

> It does not ask the model to choose from every possible leaf in one step.
> Instead, each decision is constrained to the candidates at the current level.
> That preserves the taxonomy's parent-child structure and keeps each choice
> tied to a valid part of the maintained category tree.

### Scene 5 — Rank, choose, and descend

**Timing budget:** 3:10–4:35

**On screen**

In `_walk_taxonomy`, follow:

1. `_predict_ranked_level`;
2. selection of the highest-ranked valid choice;
3. `get_direct_children` for that choice;
4. either descending into those children or constructing the final ranked
   results when a leaf level is reached.

Briefly show `_normalize_category_id` or `_parse_ranked_categories` to
demonstrate that returned categories must belong to the offered candidate set.

**Narration**

> At each level, the service builds a prompt from only the current candidates.
> The configured model chain returns ranked choices, and the service validates
> those choices against the candidate set rather than trusting arbitrary
> category text.

> The strongest valid choice determines the branch. If that choice has
> children, those children become the next candidate set and the process
> repeats. When the selected level has no children, the service turns the
> ranked valid choices into response objects.

> Each object carries the category identifier, its display name, confidence,
> and hierarchy. The hierarchy lets the caller understand where the result
> sits without reconstructing the traversal.

### Scene 6 — Return the response contract

**Timing budget:** 4:35–5:30

**On screen**

Return to `predict_category_handler` and highlight the `_response` call. Then
return to the real terminal response and expand:

- `body.categories`;
- one category object's stable fields;
- `body.token_usage`.

Do not read category IDs, confidence values, call totals, or token values
aloud.

**Narration**

> The handler places the ranked category objects under `body.categories`.
> The client depends on each result carrying its name, identifier, confidence,
> and hierarchy, so this shape is a response contract rather than an internal
> detail.

> The body also carries usage information accumulated across the decisions
> made for this request. We can inspect the structure without treating today's
> values as permanent facts.

### Scene 7 — Match the CloudWatch record

**Timing budget:** 5:30–6:15

**On screen**

Open the approved CloudWatch log group and locate the `TOKEN_USAGE` entry for
the request. Show only the minimum safe context needed to establish that it is
the category-prediction record.

Hide account identifiers and unrelated request data. Do not read provider,
model, token, or call-count values aloud.

**Narration**

> The classification service also emits one structured usage record after the
> request, including when the taxonomy walk exits early. This gives operators
> a CloudWatch record for the service while the caller receives the usage
> structure in the response.

> The important connection is that this log and the response came from the
> same per-request accumulator. The log supports operational analysis; the
> response preserves the existing client contract.

### Scene 8 — Redirect volatile details to the wiki

**Timing budget:** 6:15–6:35

**On screen**

End on a simple card:

> Current taxonomy and classification details  
> Wiki: **Help Request Classification Design**

**Narration**

> We followed one description from the request, through routing and
> level-by-level classification, to the response and its usage record. For the
> current taxonomy, model configuration, and other details that can change,
> use the Help Request Classification Design page in the repository wiki.

## Script-review checklist

- [ ] The flow matches the latest `dev`.
- [ ] The API request shape has been confirmed with the team lead.
- [ ] The explanation of taxonomy descent has been reviewed by a maintainer.
- [ ] Every technical claim is supported by a named source file.
- [ ] No model/provider name, configuration value, category count, taxonomy
      depth, test count, token count, line number, or endpoint list is spoken.
- [ ] The final card names **Help Request Classification Design**.
- [ ] Recording has not started before script approval.

## Pre-recording checklist

- [ ] Rebase or compare the branch against the latest `dev`.
- [ ] Update `script_verified_against` if either named source file changed.
- [ ] Set `recorded_against` to the exact commit used for recording.
- [ ] Confirm the fictional request is safe to publish.
- [ ] Confirm the live API and CloudWatch demonstrations are approved.
- [ ] Test the complete `curl` command before recording.
- [ ] Prepare the CloudWatch view in advance and hide unrelated log data.
- [ ] Close or hide terminals and tabs that contain secrets.
- [ ] Record the live request, real response body, and matching real log.
- [ ] Review the recording frame-by-frame for credentials and private data.
- [ ] Keep the final recording under the issue's target length.
- [ ] End on the required wiki reference card.
