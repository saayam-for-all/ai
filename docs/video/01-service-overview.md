
# Episode 1 — What this service is, and where it sits

## Episode details

| Detail                  | Value                                                                                                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Status                  | Draft                                                                                                                        |
| Script verified against | `b0f99c16fa64d3df66c76c404ef2813b354a064f`                                                                                   |
| Recorded against        | TBD — set immediately before recording                                                                                       |
| Source files            | `lambda_function.py`; `.github/workflows/deploy_aws_lambda.yml`; `tests/test_router.py`; `tests/test_import_blast_radius.py` |
| Maintained detail owner | Wiki **Home**; **GenAI Integration Reference**; **GenAI Services Specification**                                             |
| Last verified           | 2026-11-18                                                                                                                   |
| Target runtime          | Under 5 minutes                                                                                                              |

## Purpose

Show where the GenAI service sits in Saayam: what it adds to a help request,
who calls it, and how one codebase runs as separate services behind one router.
Episodes 2 to 4 zoom in from here.

This episode explains the **stable shape of the service and the reasons for
it**. Current values are maintained on the wiki **Home**, **GenAI Integration
Reference** and **GenAI Services Specification** pages.

## Governing rule

Do **not** say model or provider names, Lambda memory or timeout settings,
category counts, test counts, token counts, line numbers, endpoint paths, URLs,
or the AWS region aloud.

When a changing value is visible on screen, refer to its role instead:

- "the configured model chain"
- "the router"
- "the deploy workflow"
- "the Lambda configuration"
- "the router tests"
- "the usage record"

The episode ends by directing viewers to the wiki **Home**, **GenAI Integration
Reference** and **GenAI Services Specification** pages for current values.

## Recording prerequisites

Before recording, confirm with the team lead that you have:

- the approved development URL, request format and sign-in method for
  Predict Category;
- read-only access to the relevant CloudWatch log group;
- permission to show the selected request, response and log record;
- a `dev` checkout with `requirements.txt` and `requirements-dev.txt`
  installed (the router tests need no keys).

Because the recording will be public, do not show:

- credentials, tokens, authorization headers or secret values;
- `.env` files or GitHub/AWS secret configuration;
- the AWS account ID, API Gateway invoke URLs, Lambda function ARNs or S3
  bucket names;
- real user or beneficiary information.

Crop or blur any of these if they appear.

If approved API or CloudWatch access is not available, stop after script
review. Do not replace the running-system evidence with slides or fabricated
output.

## Safe demonstration request

Use the same fictional request as Episode 2, so Episode 2 picks up where this
one stops:

> Need help with tutoring in math.

Set the approved URL outside the visible recording area. Keep credentials out
of the recorded shell history.

```bash
curl -sS -X POST "${PREDICT_CATEGORY_URL}" \
  -H "Content-Type: application/json" \
  --data '{"description":"Need help with tutoring in math"}' \
  | python -m json.tool
```

Adjust the request only if the approved endpoint needs a different documented
envelope. Verify the exact command before recording.

## Recording plan

### Scene 1 — We enrich, we don't block

**Timing budget:** 0:00–0:40

**On screen**

Open the wiki **Home** page at §1.2 *Scope*, showing "It is not on the critical
path of a help request".

**Narration**

> On Saayam, a person posts a help request and volunteers help them. The
> Request service owns that request.

> This service sits beside it and adds extras: a category, a subject line,
> guidance, organisations that can help, and emergency numbers. We enrich; we
> never block. If category prediction fails, the form shows "General" and the
> request still goes through.

> In this episode: what the service does, who calls it, how it is split up,
> and proof that it runs.

### Scene 2 — Two callers, two paths

**Timing budget:** 0:40–1:10

**On screen**

Open the wiki **GenAI Integration Reference** at §2 *Where GenAI sits*.
Highlight *Callers* and *Auth*. Do not read URLs or function names aloud.

**Narration**

> The web client calls us while someone writes a request, and from the Request
> Details page. Those calls go through API Gateway and are signed in.

> The Data and ML service calls organisation search directly, without API
> Gateway. Nothing runs on a timer: code runs only when called.

### Scene 3 — One package, five functions

**Timing budget:** 1:10–1:50

**On screen**

Show the deploy job's `matrix` in `.github/workflows/deploy_aws_lambda.yml`.
Do not read secret names or the timeout value. Episode 4 explains how the
deploy works; this scene only shows the split.

**Narration**

> One build makes one package. The deploy installs it into a separate Lambda
> function per service: Predict Category, Generate Subject, Generate Answer,
> Emergency Contacts and More Organizations.

> Why separate? Each gets its own settings, and a failure in one stays in one.

### Scene 4 — The router

**Timing budget:** 1:50–2:40

**On screen**

Open `lambda_function.lambda_handler`. Highlight where `service` is read, the
default, the dispatch to each handler, the `400` for an unknown service and the
`except` block.

Do not mention or highlight line numbers.

**Narration**

> Normally, API Gateway calls each service's own handler. There is also one
> shared entry point, `lambda_handler`, also called the unified handler. I'll
> call it the router.

> It reads `service` from the query string, then the body, and calls the
> matching handler. No service named? It defaults to category prediction. An
> unknown name gets a 400 listing the valid ones. An unexpected error returns
> a plain message; the details go to the logs, not to the caller.

> One service replies differently. That's Episode 3.

### Scene 5 — Prove it runs

**Timing budget:** 2:40–3:40

**On screen**

1. Run the router tests:

   ```bash
   python -m pytest tests/test_router.py tests/test_import_blast_radius.py -q
   ```

   Show the actual result. Do not call out the test count.
2. Send the safe demonstration request. Show the actual response body without
   walking through its fields; Episode 2 does that.
3. Show the matching `TOKEN_USAGE` record in CloudWatch. Hide unrelated log
   lines and do not read token or call counts aloud.

**Narration**

> The router tests prove this. Every service name reaches its handler, unknown
> names get a 400, bad input never causes a server error, and errors never
> leak internals.

> And here is the live service answering the demo request, with its usage
> record in CloudWatch. Episode 2 follows this same request step by step.

### Scene 6 — Why the split matters

**Timing budget:** 3:40–4:15

**On screen**

Show the module docstring of `tests/test_import_blast_radius.py`, then
`lambda_function._lookup_request`, where the database helper is imported inside
the function.

**Narration**

> Because we only enrich, a failure must degrade the result. It must never
> block the request or pretend to succeed.

> For example, only Generate Answer needs the database library, so only it
> imports it. When that import sat at the top of the shared file, one broken
> install took every service down. Now it can only affect Generate Answer, and
> a test keeps it that way.

### Scene 7 — Redirect changing facts to maintained sources

**Timing budget:** 4:15–4:35

**On screen**

End on a card pointing to:

- Wiki **Home**, §1.2 *Scope*
- **GenAI Integration Reference**, §2 *Where GenAI sits*
- **GenAI Services Specification**, §1.2 *Deployment Model*

**Narration**

> That's the shape: what we do, who calls us, and how the parts stay separate.
> For current values, like models, settings and endpoints, see these wiki
> pages. Next, Episode 2 follows the request you just saw.

## Script-review checklist

- [ ] The flow matches the latest `dev`.
- [ ] Every technical claim is supported by a named source file or wiki page.
- [ ] The two caller paths (API Gateway and a direct invoke) are confirmed by a
  maintainer.
- [ ] The API request shape is confirmed with the team lead.
- [ ] No model or provider name, configuration value, count, line number,
  endpoint path, URL or region is spoken.
- [ ] Terms match the rest of the series ("the router", "the configured model
  chain", "the usage record").
- [ ] Recording has not started before script approval.

## Pre-recording checklist

- [ ] Compare against the latest `dev`.
- [ ] Update **Script verified against** if any named source file changed.
- [ ] Set **Recorded against** to the exact commit used for recording.
- [ ] Confirm every source file in the Episode details table still exists.
- [ ] Confirm the live request and CloudWatch demonstration are approved.
- [ ] Test the router-test command and the `curl` command before recording.
- [ ] Use made-up request data only.
- [ ] Prepare the CloudWatch view in advance and hide unrelated log data.
- [ ] Crop or blur account IDs, invoke URLs, ARNs, bucket names, credentials,
  tokens and authorization headers.
- [ ] Use a real test run, real response and real log record.
- [ ] Review the recording frame by frame before publishing.
- [ ] Keep the final recording under 5 minutes.
- [ ] End on the wiki reference card.
