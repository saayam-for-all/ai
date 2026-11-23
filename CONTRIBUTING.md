# Contributing to the GenAI services

## How a change reaches users

1. **Branch from `dev`.**
2. **Open a pull request into `test`.** It merges without review. Merging deploys to the test function, `ai-app-test`, which runs every service through one router. Nothing users call is touched.
3. **Read the smoke test.** After that deploy, the run sends one sample request per service to `ai-app-test` and fails on any server error or missing field. Every response is printed in the run's log and summary.
4. **Open a second pull request, from the same branch, into `dev`.** It needs two approvals. Merging into `dev` deploys to the functions real users call.

- Docs-only changes go straight to `dev`.
- Experiments that use `test` as a sandbox, such as #231 and #234, stay on `test` and are never opened against `dev`.

## Trying your own change on `test`

Add a sample request to `tests/smoke/` in your pull request, one JSON file per request:

```json
{
  "name": "Predict Category: a help request",
  "service": "predict_category",
  "body": {"description": "I need help with gardening"},
  "expect": {"status": 200, "body_keys": ["categories"]}
}
```

- `service` picks the router's service: `predict_category`, `generate_subject`, `generate_answer`, `emergency_contacts` or `search_orgs`.
- `body` is the request body. Emergency Contacts reads the query string, so its samples use `query` instead.
- `expect.status` defaults to "anything below 500", and `expect.body_keys` lists fields the response must have.

After your pull request merges into `test`, the deploy run sends your sample and prints the response. `tests/test_smoke_tool.py` checks that every sample is well formed, so a broken file fails the pull request's own tests first.

Keep samples free of real names, phone numbers, addresses and request IDs.

## When `test` and `dev` drift apart

- After every merge into `dev`, a workflow opens a "Sync dev into test" pull request. Merge it promptly, so changes on `test` are checked against current code.
- If your pull request into `test` conflicts, merge it through a separate branch cut from `test`, for example `merge/<topic>-into-test`. Your feature branch then stays on `dev`'s line for its second pull request.
- Conflicts in generated or append-only files are routine:
  - `docs/testing/TEST_CATALOGUE.md`: regenerate it with `python tools/gen_test_catalogue.py` rather than merging by hand.
  - `CHANGELOG.md`: keep both entries.

## What `test` does not check

- **API Gateway.** The smoke test calls `ai-app-test` directly, not through the API. A fault in how a route hands requests to its function, such as the proxy or non-proxy shape, the request mapping or the authorizer, passes on `test` and fails on `dev`. Check those through the API after the `dev` merge. The larger fix, stages and aliases, is proposed in #207.
- **Gemini.** `test` runs Groq-only, so the last step of the model fallback chain is never exercised there.
- **The request database.** The test function cannot read the database credentials, so Generate Answer's lookup by request ID does not run on `test`. Its sample sends the request text directly.

## Keys on `test`

`ai-app-test` reads its own test-only Groq key, named by `GROQ_PARAM_NAME`, and runs Groq-only because `GEMINI_PARAM_NAME` is empty. Its role can read that key and nothing else. Anyone can push to `test`, so never point the test function at a role that can read the live keys.
