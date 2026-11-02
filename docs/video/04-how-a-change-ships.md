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
local verification, CI guardrails, packaging, and deployment.

This episode explains the **shape of the delivery path and why each gate exists**.
It deliberately does not narrate configuration values that are owned by the
wiki or deployment environment.

## Governing rule

Do **not** say model names, Lambda memory or timeout settings, category counts,
test counts, line numbers, endpoint lists, coverage percentages, or other
volatile values aloud.

When a changing value is visible on screen, refer to its role instead:

- "the regression suite"
- "the coverage gate"
- "the deployment workflow"
- "the Lambda configuration"
- "the current test catalogue"

The episode ends by directing viewers to the **GenAI Services Specification**
and the repository's **testing documentation** for current values.

## Recording plan

### Scene 1 — Start from a code change

**On screen**

Open the repository on a small documentation or code change and then show the
GitHub Actions workflows under `.github/workflows/`.

**Narration**

> A change does not go straight from a developer's branch to a running Lambda.
> It moves through a series of checks designed to catch contract, safety, and
> packaging problems before deployment. In this episode, I will follow that
> path from the test suite through the deployment workflow.

### Scene 2 — Run the regression suite

**On screen**

Open `docs/testing/QA_RUNBOOK.md`, then run:

```bash
python -m pytest
```

Show the actual command and its real result. Do not call out the test count.

**Narration**

> The first gate is the regression suite. Its job is to prove that the
> behaviours the rest of Saayam depends on have not changed unexpectedly.
> A green suite means the repository's tested contracts still hold. It does
> not, by itself, prove that the deployed AWS endpoint is healthy, because
> external systems are intentionally isolated from the default test run.

### Scene 3 — Explain the network guard

**On screen**

Open `tests/conftest.py` and highlight the autouse network guard fixture.

**Narration**

> The default test run is deliberately hermetic. Tests are not allowed to make
> accidental live network calls. That prevents a model provider, geocoder, or
> another external service from turning a code regression test into an uptime
> check for somebody else's system. Tests that genuinely need the network are
> separated and must opt into that behaviour explicitly.

### Scene 4 — Show the CI quality gates

**On screen**

Open the relevant validation steps in
`.github/workflows/python-ci-cd.yml` and
`.github/workflows/deploy_aws_lambda.yml`.

Show the steps for security/static analysis where applicable, tests, coverage,
and the test-catalogue consistency check. If a recent Actions run exists, show
the real run rather than a slide.

**Narration**

> GitHub Actions repeats the important checks in a clean environment. The
> workflow runs the regression suite, applies its quality gates, and verifies
> that the generated test catalogue still agrees with the tests in the
> repository. These checks are there so a change cannot rely only on what
> happened on one developer's machine.

> The key idea is that deployment depends on validation. If an earlier gate
> fails, the delivery path stops before AWS is touched.

### Scene 5 — Build the deployment artifact

**On screen**

Show the build steps in `.github/workflows/deploy_aws_lambda.yml`:
dependency installation in the Lambda-compatible build environment, copying
application code, trimming runtime-provided or build-only files, creating the
deployment archive, and publishing the build artifact.

Do not narrate package-size limits or other numeric configuration.

**Narration**

> Once validation succeeds, the workflow builds the Lambda artifact in an
> environment compatible with the runtime. Application code and dependencies
> are assembled, files that do not need to ship are removed, and the result is
> packaged as the deployment artifact.

> Keeping build and deployment separate is useful: the deploy stage receives
> the exact artifact produced by the successful build instead of rebuilding
> something different later.

### Scene 6 — Deploy after the gates pass

**On screen**

Show the deploy job and the deployment helper it invokes. If you have approved
AWS access during recording, show the real successful workflow run and one
normal CloudWatch log line from the deployed service. Do not reveal secrets or
read changing configuration values aloud.

**Narration**

> Deployment runs only after the earlier stages have succeeded. The workflow
> authenticates to AWS, takes the approved build artifact, and updates the
> Lambda functions through the deployment path defined by the repository.

> The important point is not a particular configuration value. It is the
> dependency chain: test first, build once, then deploy the validated artifact.
> That gives reviewers a clear place to stop a bad change before it reaches the
> running service.

### Scene 7 — Close on the maintained references

**On screen**

End on a simple repository view that points to:

- Wiki — **GenAI Services Specification**
- `docs/testing/`

**Narration**

> This video explains the stable delivery path. For the current deployment
> configuration, current test inventory, and other values that can change,
> use the GenAI Services Specification and the testing documentation. Those
> maintained sources own the details; this recording owns the shape of the
> process and the reason each gate exists.

## Pre-recording checklist

- [ ] Rebase or compare against the latest `dev`.
- [ ] Update `recorded_against` to the exact commit used for the recording.
- [ ] Confirm every source file in the front matter still exists.
- [ ] Confirm the workflow order described above still matches the current code.
- [ ] Remove any spoken model name, timeout/memory value, test count, coverage
      percentage, package-size limit, line number, or endpoint list.
- [ ] Use a real test run and real workflow evidence, not slides.
- [ ] Check the recording for secrets before publishing.
- [ ] Keep the final recording under the issue's target length.
- [ ] End on the wiki/testing reference card.
