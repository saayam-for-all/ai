# Episode 4 — How a change ships

## Episode details

| Detail | Value |
| --- | --- |
| Status | Draft |
| Script verified against | `b0f99c16fa64d3df66c76c404ef2813b354a064f` |
| Recorded against | TBD — set immediately before recording |
| Source files | `tests/conftest.py`; `docs/testing/QA_RUNBOOK.md`; `docs/testing/TEST_CATALOGUE.md`; `.github/workflows/python-ci-cd.yml`; `.github/workflows/deploy_aws_lambda.yml` |
| Maintained detail owner | **GenAI Services Specification** and `docs/testing/` |
| Last verified | 2026-11-18 |
| Target runtime | Under 6 minutes |

## Purpose

Show a developer how a GenAI change moves from a pull request through validation, packaging, deployment, and a final running-system check.

This episode explains the **stable shape of the delivery path and why each gate exists**. Changing configuration and other volatile values are maintained on the **GenAI Services Specification** page and in the testing documentation.

## Governing rule

Do **not** say model names, Lambda memory or timeout settings, category counts, test counts, line numbers, endpoint lists, coverage percentages, package-size limits, or other volatile values aloud.

When a changing value is visible on screen, refer to its role instead:

- "the regression suite"
- "the coverage gate"
- "the deployment workflow"
- "the Lambda configuration"
- "the current test catalogue"

The episode ends by directing viewers to the **GenAI Services Specification** and the repository's **testing documentation** for current values.

## Recording prerequisites

Before recording, confirm that you can safely show:

- a real local regression-suite run;
- a real GitHub Actions run for the relevant workflow;
- a live request to the deployed service and its actual response body;
- one normal CloudWatch log line for that request.

Because the recording will be public, do not show:

- credentials, tokens, authorization headers, or secret values;
- environment files or GitHub/AWS secret configuration;
- the AWS account ID;
- API Gateway invoke URLs;
- Lambda function ARNs;
- S3 bucket names;
- real user or beneficiary information.

Crop or blur any of those values if they appear in the interface. Use a made-up request with no real person's details for the live demonstration.

If approved AWS or CloudWatch access is not available, stop after script review and treat recording as blocked rather than substituting slides or fabricated output.

## Recording plan

### Scene 1 — A change starts in the repository
**Timing budget:** 0:00–0:35

**On screen**

Open the repository, show a small code change, and then show the GitHub Actions workflows.

**Narration**

> A change does not go straight from a developer's branch to a running Lambda. It first moves through validation, build, and deployment stages. In this episode, I will follow that path and explain why each gate exists.

### Scene 2 — Run the regression suite
**Timing budget:** 0:35–1:20

**On screen**

Open `docs/testing/QA_RUNBOOK.md`, then run:

```bash
python -m pytest
```

Show the actual result. Do not call out the test count.

**Narration**

> The first gate is the regression suite. It checks that behaviours the rest of Saayam depends on have not changed unexpectedly. A green run means the tested contracts still hold. It does not by itself prove that AWS is healthy, because the default suite intentionally isolates external systems.

### Scene 3 — Explain the no-network guard
**Timing budget:** 1:20–2:05

**On screen**

Open `tests/conftest.py` and highlight the autouse network guard fixture.

**Narration**

> The default test run is deliberately hermetic. Unmarked tests are prevented from making accidental live network calls. That keeps a model provider, geocoder, or another external service from turning a regression test into an uptime check for somebody else's system. Tests that genuinely need the network have to opt into that behaviour explicitly.

### Scene 4 — PR validation and the two pipelines
**Timing budget:** 2:05–3:15

**On screen**

Show the event guards and jobs in `.github/workflows/deploy_aws_lambda.yml`.

Then briefly show `.github/workflows/python-ci-cd.yml` and its deploy job.

Show the test-catalogue consistency check in the deployment workflow. Prefer a real GitHub Actions run over describing the YAML alone.

**Narration**

> Opening a pull request runs validation, but it does not deploy through the Lambda deployment workflow. Merging into the deployment branch is what makes the build and deploy stages eligible to run. For a new joiner, the useful distinction is simple: opening a pull request is the review and validation step; merging is what ships the change.

> This repository also has a second CI/CD pipeline. It performs additional checks, but it can also package and deploy after the appropriate branch event. That is why a merge can produce more than one workflow run.

> One useful gate keeps the generated test catalogue aligned with the actual suite. If validation fails, the delivery path stops before AWS is touched.

### Scene 5 — Build the deployment artifact
**Timing budget:** 3:15–4:05

**On screen**

Show the build steps in `.github/workflows/deploy_aws_lambda.yml`: Lambda-compatible dependency installation, copying application code, trimming unneeded files, creating the deployment archive, and uploading the build artifact.

Do not narrate numeric size limits or configuration values.

**Narration**

> After validation succeeds, the workflow builds the Lambda artifact in an environment compatible with the runtime. The application code and dependencies are assembled, unnecessary files are removed, and the result is packaged as the artifact that will be deployed.

> The important property here is build once, deploy that build. The deploy stage receives the artifact produced by the successful build instead of rebuilding something different later.

### Scene 6 — Deploy, then prove the running path
**Timing budget:** 4:05–5:20

**On screen**

Show the deploy job and the deployment helper it invokes.

Then show, with approved access:

1. a successful workflow run;
2. a live `curl` or equivalent request using made-up data;
3. the actual response body;
4. one matching, non-sensitive CloudWatch log line.

Before recording, crop or blur any AWS account IDs, invoke URLs, Lambda ARNs, S3 bucket names, credentials, tokens, authorization headers, or other sensitive values.

**Narration**

> Deployment only runs after the earlier stages succeed. The workflow authenticates to AWS, takes the validated build artifact, and updates the Lambda functions through the repository's deployment path.

> After deployment, I verify the running path rather than assuming that a successful workflow means the service answers correctly. Here is a demo request, its response, and the corresponding application log.

> The stable lesson is the dependency chain: validate first, build once, deploy the validated artifact, then verify the running service.

### Scene 7 — Redirect changing facts to maintained sources
**Timing budget:** 5:20–5:45

**On screen**

End on a repository/wiki view pointing to:

- **GenAI Services Specification**
- `docs/testing/`

**Narration**

> This recording explains the stable delivery path. For current deployment configuration, the current test inventory, and other values that can change, use the GenAI Services Specification and the testing documentation. Those maintained sources own the details; this video owns the shape of the process and the reason each gate exists.

## Pre-recording checklist

- [ ] Compare against the latest `dev`.
- [ ] Update **Script verified against** if any named source file changed.
- [ ] Set **Recorded against** to the exact commit used for recording.
- [ ] Confirm every source file in the Episode details table still exists.
- [ ] Confirm the PR-versus-merge behaviour still matches the current workflows.
- [ ] Confirm both CI/CD pipelines are described accurately.
- [ ] Confirm the live request/log demonstration is approved and available.
- [ ] Use made-up request data only.
- [ ] Crop or blur AWS account IDs, invoke URLs, Lambda ARNs, S3 bucket names, credentials, tokens, authorization headers, and other sensitive values.
- [ ] Remove any spoken model name, timeout/memory value, test count, coverage percentage, package-size limit, line number, or endpoint list.
- [ ] Use a real test run, real workflow run, real response, and real log.
- [ ] Review the recording before publishing to make sure no sensitive values are visible.
- [ ] Keep the final recording under the issue's target length.
- [ ] End on the GenAI Services Specification/testing reference card.
