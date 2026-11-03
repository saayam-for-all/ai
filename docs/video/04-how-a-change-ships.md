---
episode: 4
title: "How a change ships"
status: draft
script_verified_against: "271a40216cd3469784bb462536cfc4d05ff42bd4"
recorded_against: "TBD — set immediately before recording"
source_files:
  - tests/conftest.py
  - docs/testing/QA_RUNBOOK.md
  - docs/testing/TEST_CATALOGUE.md
  - .github/workflows/python-ci-cd.yml
  - .github/workflows/deploy_aws_lambda.yml
wiki_owner:
  - "GenAI Services Specification"
  - "Testing documentation"
last_verified: "2026-11-02"
target_runtime: "under 6 minutes"
---

# Episode 4 — How a change ships

## Purpose

Show a developer the path a GenAI code change follows before it reaches AWS:
local verification, CI guardrails, packaging, deployment, and a final
running-system check.

The episode explains the **stable shape of the delivery path and why each gate
exists**. It deliberately does not narrate configuration values that belong to
the wiki or deployment environment.

## Governing rule

Do **not** say model names, Lambda memory or timeout settings, category counts,
test counts, line numbers, endpoint lists, coverage percentages, package-size
limits, or other volatile values aloud.

When a changing value is visible on screen, refer to its role instead:

- "the regression suite"
- "the coverage gate"
- "the deployment workflow"
- "the Lambda configuration"
- "the current test catalogue"

The episode ends by directing viewers to the **GenAI Services Specification**
and the repository's **testing documentation** for current values.

## Recording prerequisites

Before recording, confirm that you can safely show:

- a real local regression-suite run;
- a real GitHub Actions run for the relevant workflow;
- a live request to the deployed service and its actual response body;
- one normal CloudWatch log line for that request.

Do not record credentials, secret values, authorization headers, environment
files, or GitHub/AWS secret configuration.

If approved AWS/log access is not available, stop after script review and treat
recording as blocked rather than substituting slides or fabricated output.

## Recording plan

### Scene 1 — A change starts in the repository
**Timing budget:** 0:00–0:35

**On screen**

Open the repository, show a small code/documentation change, then open
`.github/workflows/`.

**Narration**

> A change does not go straight from a developer's branch to a running Lambda.
> It passes through validation, build, and deployment stages first. In this
> episode, I will follow that path and show why each gate exists.

### Scene 2 — Run the regression suite
**Timing budget:** 0:35–1:20

**On screen**

Open `docs/testing/QA_RUNBOOK.md`, then run:

~~~bash
python -m pytest
~~~

Show the actual result. Do not call out the test count.

**Narration**

> The first gate is the regression suite. It checks that behaviours the rest of
> Saayam depends on have not changed unexpectedly. A green run means the tested
> contracts still hold. It does not by itself prove that AWS is healthy,
> because the default suite intentionally isolates external systems.

### Scene 3 — Explain the no-network guard
**Timing budget:** 1:20–2:05

**On screen**

Open `tests/conftest.py` and highlight the autouse network guard fixture.

**Narration**

> The default test run is deliberately hermetic. Unmarked tests are prevented
> from making accidental live network calls. That keeps a model provider,
> geocoder, or another external service from turning a regression test into an
> uptime check for somebody else's system. Tests that genuinely need the
> network have to opt into that behaviour explicitly.

### Scene 4 — Show CI quality gates
**Timing budget:** 2:05–3:10

**On screen**

Use `.github/workflows/deploy_aws_lambda.yml` as the main end-to-end delivery
story: test, build, then deploy.

Briefly show `.github/workflows/python-ci-cd.yml` for additional repository
quality checks such as static security analysis and broader validation.

Show the test-catalogue consistency check in the deployment workflow. Prefer a
real GitHub Actions run over describing the YAML alone.

**Narration**

> GitHub Actions repeats the important checks in a clean environment, so a
> change does not depend only on what happened on one developer's machine.
> The deployment workflow runs its validation gates before build and deploy,
> while the repository CI also performs additional quality checks.

> One useful gate keeps the generated test catalogue aligned with the actual
> suite. The important idea is simple: if validation fails, the delivery path
> stops before AWS is touched.

### Scene 5 — Build one deployment artifact
**Timing budget:** 3:10–4:05

**On screen**

Show the build steps in `.github/workflows/deploy_aws_lambda.yml`:
Lambda-compatible dependency installation, copying application code, trimming
unneeded files, creating the deployment archive, and uploading the build
artifact.

Do not narrate numeric size limits or configuration values.

**Narration**

> After validation succeeds, the workflow builds the Lambda artifact in an
> environment compatible with the runtime. The application code and
> dependencies are assembled, unnecessary files are removed, and the result is
> packaged as the artifact that will be deployed.

> The important property here is build once, deploy that build. The deploy
> stage receives the artifact produced by the successful build instead of
> rebuilding something different later.

### Scene 6 — Deploy, then prove the running path
**Timing budget:** 4:05–5:15

**On screen**

Show the deploy job and the deployment helper it invokes.

Then show, with approved access:

1. a successful workflow run;
2. a live `curl` or equivalent request to the deployed service;
3. the actual response body;
4. one matching, non-sensitive CloudWatch log line.

Do not reveal credentials, tokens, request authorization headers, secret
values, or changing configuration values.

**Narration**

> Deployment only runs after the earlier stages succeed. The workflow
> authenticates to AWS, takes the validated build artifact, and updates the
> Lambda functions through the repository's deployment path.

> After deployment, I verify the running path rather than assuming that a
> successful workflow means the service answers correctly. Here is a real
> request, its response, and the corresponding application log.

> The stable lesson is the dependency chain: validate first, build once, deploy
> the validated artifact, then verify the running service.

### Scene 7 — Redirect changing facts to maintained sources
**Timing budget:** 5:15–5:40

**On screen**

End on a repository/wiki view pointing to:

- Wiki — **GenAI Services Specification**
- `docs/testing/`

**Narration**

> This recording explains the stable delivery path. For current deployment
> configuration, the current test inventory, and other values that can change,
> use the GenAI Services Specification and the testing documentation. Those
> maintained sources own the details; this video owns the shape of the process
> and the reason each gate exists.

## Pre-recording checklist

- [ ] Rebase or compare against the latest `dev`.
- [ ] Update `script_verified_against` if the reviewed source files changed.
- [ ] Update `recorded_against` to the exact commit used for recording.
- [ ] Confirm every source file in the front matter still exists.
- [ ] Confirm the workflow order described above still matches current `dev`.
- [ ] Confirm the live request/log demonstration is approved and available.
- [ ] Remove any spoken model name, timeout/memory value, test count, coverage
      percentage, package-size limit, line number, or endpoint list.
- [ ] Use a real test run, real workflow run, real response, and real log.
- [ ] Check the recording frame-by-frame for secrets before publishing.
- [ ] Keep the final recording under the issue's target length.
- [ ] End on the wiki/testing reference card.
