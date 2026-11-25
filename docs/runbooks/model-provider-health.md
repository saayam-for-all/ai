# Runbook: model provider health

**Alarm:** `saayam-genai-model-probe-failure` · **Issue:** [#195](https://github.com/saayam-for-all/ai/issues/195) (Parts C and D)

Once a day a probe calls every model in
[`config/model_routing.json`](../../config/model_routing.json) with one trivial
prompt, **including the fallbacks no request is using today**. If any model does
not answer, or the probe itself does not run, the alarm emails the GenAI team.

Why it exists: in August 2026 Groq retired every model we called and a person
noticed weeks later. On 1 June 2026 the Gemini model kept as the last resort was
shut down and nothing noticed, because nothing called it. Automatic fallback
keeps requests working while a model is down, which is also exactly why nobody
sees it go down. This alarm is how we find out first.

## 1. When the email arrives

**Who acts:** the GenAI dev leads own the alarm. Whoever picks it up says so in
the team chat, so two people don't chase the same thing.

**First, find out which model and why.** CloudWatch → Logs Insights → log group
`/aws/lambda/<probe function name>`:

```
fields @timestamp, @message
| filter @message like /MODEL_PROBE/ and @message like /reachable=false/
| parse @message "model=* position=* role=* reachable=* error_class=* latency_ms=* reason=*" as model, position, role, reachable, error_class, latency_ms, reason
| sort @timestamp desc
| limit 20
```

Each line names the model, its place in the chain, and an `error_class`. The
class tells you who acts:

| `error_class` | What it means | Who acts | What they do |
| --- | --- | --- | --- |
| `model_not_found` | 404: the provider no longer has this model id. It will not come back. | Any GenAI developer | Check the provider's deprecation page, pick a replacement, change `config/model_routing.json`, run `python -m pytest -q`, open a PR. Re-run the probe after deploy. |
| `auth_or_entitlement` | 401/403: the key was revoked, or the account is unpaid. **The model is fine. Do not change code.** | Whoever holds the Groq or Gemini account | Check billing and the key in the provider console. If the key was rotated, update it in Parameter Store (`/dev/saayam/GenAI/groq/key` or `/dev/saayam/GenAI/gemini/key`). |
| `rate_limited` | 429: rate limit or daily quota used up. On Groq's free tier this is roughly 58 help requests a day. | GenAI leads | Wait for the reset, reorder the chain, or upgrade the plan. If it repeats daily, it is a capacity problem, not an incident (see #277). |
| `timeout_or_unavailable` | Slow, 5xx or unreachable. Usually the provider's problem. | Any GenAI developer | Check the provider's status page. If it still fails at the next day's probe, treat it as an outage and tell the leads. |
| `empty_response` | The model answered with nothing. | Any GenAI developer | Re-run the probe. If it repeats, investigate that model before relying on it as a fallback. |
| `other` | Not one of the above. Read `reason=`. | Any GenAI developer | `code=model_decommissioned` (Groq answers a retired model with 400, not 404) means the same as `model_not_found`. `ValueError` with every model failing usually means a key never loaded: check the probe role can read both parameters. |

**If no `MODEL_PROBE` lines exist for today**, the probe did not run. The alarm
treats a missing datapoint as a failure on purpose. Check that the schedule
`saayam-genai-model-health-probe-daily` is enabled, and check the function's
last invocation in the Lambda console.

**Is anyone affected right now?** Only if the failing model is the primary
(`position=0 role=primary`) **and** every fallback is failing too. Search the
service logs for `MODEL_FAILOVER`: every failed attempt by a real request is
logged there with the same `error_class`. If only a fallback is failing, nobody
is affected yet. Fix it before the day you need it.

## 2. Run the probe by hand

From the repository root, with `GROQ_API_KEY` and `GEMINI_API_KEY` in your
`.env`. This calls the real providers once per model and spends a few tokens.

```bash
python -m utils.model_health_probe
```

```
model                         role      status                  latency
openai/gpt-oss-20b            primary   ok                      412 ms
openai/gpt-oss-120b           fallback  ok                      655 ms
openai/gpt-oss-safeguard-20b  fallback  ok                      398 ms
gemini-2.5-flash              fallback  model_not_found         120 ms

3 of 4 models answering.
```

The exit code is 1 if any model failed. In the Lambda console, a test
invocation returns the same results as JSON.

## 3. What the probe writes

Namespace `Saayam/GenAI`:

| Metric | Dimensions | Value |
| --- | --- | --- |
| `ModelProbeFailures` | `service=model_health_probe` | Number of models that did not answer. Written every run, even when 0. **The alarm watches this.** |
| `ModelReachable` | `provider`, `model` | 1 or 0, per model. For the per-model history and the wiki graph. |
| `ModelLatencyMs` | `provider`, `model` | Time to answer (or to fail), per model. |

The error class is in the log line, not a metric dimension. As a dimension it
would split each model into a new series per class, and one alarm could no
longer watch them.

## 4. One-time setup (needs AWS access)

Run these once, in order. Replace the values in the first block. The region is
the one the other GenAI functions use.

```bash
REGION=us-east-1
ACCOUNT=<12-digit account id>
FUNCTION=<probe function name, for example ai-model-health-probe>
ALERT_EMAIL=<a team list address, not one person's inbox>
```

**4.1 The function.** Create it from the same deployment package as the other
GenAI functions, with the same execution role (it needs `ssm:GetParameters` on
the two key parameters, and CloudWatch Logs):

- handler: `lambda_function.model_health_probe_handler`
- runtime: Python 3.11, memory 256 MB, timeout 120 s (four models, up to 20 s each)

Then add it to the deploy matrix in `.github/workflows/deploy_aws_lambda.yml`
with its ARN as a repository secret, like the other functions, so it ships
with every change.

**4.2 The daily schedule.** 14:00 UTC is 06:00 Pacific (07:00 in summer), so a
failure is waiting when the team starts its day.

```bash
aws events put-rule --region $REGION \
  --name saayam-genai-model-health-probe-daily \
  --schedule-expression "cron(0 14 * * ? *)" \
  --description "Daily model health and entitlement probe (#195)"

aws lambda add-permission --region $REGION \
  --function-name $FUNCTION \
  --statement-id model-health-probe-daily \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:$REGION:$ACCOUNT:rule/saayam-genai-model-health-probe-daily

aws events put-targets --region $REGION \
  --rule saayam-genai-model-health-probe-daily \
  --targets "Id"="model-health-probe","Arn"="arn:aws:lambda:$REGION:$ACCOUNT:function:$FUNCTION"
```

**4.3 The email topic.**

```bash
TOPIC_ARN=$(aws sns create-topic --region $REGION \
  --name saayam-genai-model-health --query TopicArn --output text)

aws sns subscribe --region $REGION \
  --topic-arn $TOPIC_ARN --protocol email --notification-endpoint $ALERT_EMAIL
```

Open the confirmation email that arrives and click the link. Until someone
does, nothing is delivered.

**4.4 The alarm.** It fires when any model fails, and also when the probe
did not run at all (`--treat-missing-data breaching`).

```bash
aws cloudwatch put-metric-alarm --region $REGION \
  --alarm-name saayam-genai-model-probe-failure \
  --alarm-description "A model in the GenAI chain did not answer the daily probe, or the probe did not run. Runbook: https://github.com/saayam-for-all/ai/blob/dev/docs/runbooks/model-provider-health.md" \
  --namespace Saayam/GenAI --metric-name ModelProbeFailures \
  --dimensions Name=service,Value=model_health_probe \
  --statistic Maximum --period 86400 --evaluation-periods 1 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data breaching \
  --alarm-actions $TOPIC_ARN --ok-actions $TOPIC_ARN
```

**4.5 Prove it reaches a person.** An alarm nobody has seen fire is an
assumption, not an alert.

```bash
aws lambda invoke --region $REGION --function-name $FUNCTION /dev/stdout
```

If every model is healthy, force the alarm once to check the email path:

```bash
aws cloudwatch set-alarm-state --region $REGION \
  --alarm-name saayam-genai-model-probe-failure \
  --state-value ALARM --state-reason "Testing the email path (#195)"
```

Confirm the email arrived, and note the date in #195.

## 5. Wiki section (draft)

To be added to the wiki's GenAI page once the probe is deployed:

> ### Model chain health
>
> Every model the GenAI services can fall back to is checked once a day at
> 14:00 UTC, including fallbacks that no request is using.
>
> - **Today's status and the last 30 days:** CloudWatch dashboard
>   `<link once created>`, graphing `ModelReachable` and `ModelLatencyMs` per
>   model.
> - **If a model is failing:** the GenAI leads get an email. What to do is in
>   the [model provider health runbook](https://github.com/saayam-for-all/ai/blob/dev/docs/runbooks/model-provider-health.md).
> - **Why this exists:** issue #195. In 2026 a retired model went unnoticed
>   for weeks.

## 6. What the probe does not do

It does not judge answer quality, which is evaluation, not reachability. It
does not change the chain or fail over anything; it only reports. It does not
watch the request database or the emergency dataset (future scope on #195), or
the endpoints themselves (#260).
