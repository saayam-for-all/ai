"""Smoke test for the test function, run after every deploy to `test` (#252).

Sends each sample request in tests/smoke/ to the function and fails the run on a
server error or on a response missing the fields the sample expects. Every
response is printed in short, so a contributor who added a sample can read
what their change returned.

A sample is one JSON file:

    {
      "name": "Predict Category: a help request",
      "service": "predict_category",
      "body": {"description": "I need help with gardening"},
      "expect": {"status": 200, "body_keys": ["categories"]}
    }

"service" picks the router's service. "body" is the request body. A service
that reads the query string, as Emergency Contacts does, takes "query" instead.
"expect.status" defaults to "anything below 500", and "expect.body_keys" lists
fields the response body must have.

Usage:
    python tools/smoke_check.py --function ai-app-test --fixtures tests/smoke
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

CALLER_IP = "203.0.113.10"   # a documentation address, never a real caller
BODY_PREVIEW = 300
SAMPLE_FIELDS = {"name", "service", "body", "query", "expect"}


def validate_sample(sample):
    """Reasons a sample file is malformed; empty when it is usable."""
    if not isinstance(sample, dict):
        return ["must be a JSON object"]
    problems = []
    for field in ("name", "service"):
        if not isinstance(sample.get(field), str) or not sample[field].strip():
            problems.append(f'"{field}" must be a non-empty string')
    for field in ("body", "query"):
        if field in sample and not isinstance(sample[field], dict):
            problems.append(f'"{field}" must be an object')
    expect = sample.get("expect", {})
    if not isinstance(expect, dict):
        problems.append('"expect" must be an object')
    else:
        status = expect.get("status")
        if status is not None and (isinstance(status, bool) or not isinstance(status, int)):
            problems.append('"expect.status" must be a number')
        keys = expect.get("body_keys", [])
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            problems.append('"expect.body_keys" must be a list of field names')
    unknown = sorted(set(sample) - SAMPLE_FIELDS)
    if unknown:
        problems.append(f"unknown fields {unknown}")
    return problems


def load_samples(folder):
    """Every sample in `folder`, in file-name order. A malformed file stops the run."""
    samples = []
    for path in sorted(Path(folder).glob("*.json")):
        sample = json.loads(path.read_text(encoding="utf-8"))
        problems = validate_sample(sample)
        if problems:
            raise ValueError(f"{path.name}: " + "; ".join(problems))
        samples.append(dict(sample, file=path.name))
    return samples


def build_event(sample):
    """The event API Gateway would send for this sample, with the router's service set."""
    event = {"requestContext": {"identity": {"sourceIp": CALLER_IP}}}
    if "query" in sample:
        event["queryStringParameters"] = dict(sample["query"], service=sample["service"])
        if sample.get("body"):
            event["body"] = json.dumps(sample["body"])
    else:
        event["body"] = json.dumps(dict(sample.get("body") or {}, service=sample["service"]))
    return event


def parse_response(payload):
    """(status, body) from a handler's return value, proxy shape or not."""
    if not isinstance(payload, dict):
        return None, payload
    status = payload.get("statusCode")
    body = payload.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            pass
    return status, body


def check(sample, status, body, function_error=None):
    """Reasons the response fails the sample; empty when it passes."""
    if function_error:
        return [f"the function raised an error ({function_error})"]
    expect = sample.get("expect", {})
    reasons = []
    wanted = expect.get("status")
    if not isinstance(status, int):
        reasons.append("no statusCode in the response")
    elif wanted is not None and status != wanted:
        reasons.append(f"status {status}, expected {wanted}")
    elif wanted is None and status >= 500:
        reasons.append(f"status {status}")
    keys = expect.get("body_keys", [])
    if keys:
        if not isinstance(body, dict):
            reasons.append("the body is not a JSON object")
        else:
            missing = [k for k in keys if k not in body]
            if missing:
                reasons.append(f"the body is missing {missing}")
    return reasons


def preview(body):
    if body is None:
        return ""
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return text if len(text) <= BODY_PREVIEW else text[:BODY_PREVIEW] + "..."


def run(function_name, samples, invoke):
    """Send every sample through `invoke(function_name, event)`; one result per sample."""
    results = []
    for sample in samples:
        started = time.monotonic()
        try:
            payload, function_error = invoke(function_name, build_event(sample))
            status, body = parse_response(payload)
            reasons = check(sample, status, body, function_error)
        except Exception as e:   # the call itself failed: record it and carry on
            status, body, reasons = None, None, [f"the call failed: {type(e).__name__}: {e}"]
        results.append({
            "file": sample.get("file", ""),
            "name": sample["name"],
            "status": status,
            "seconds": round(time.monotonic() - started, 1),
            "reasons": reasons,
            "preview": preview(body),
        })
    return results


def report(results, out=None, summary_path=None):
    """Print every result, add a table to the job summary, and say whether all passed."""
    out = out or sys.stdout
    failed = [r for r in results if r["reasons"]]
    for r in results:
        mark = "FAIL" if r["reasons"] else "ok"
        print(f"{mark:4} {r['name']}  status={r['status']}  {r['seconds']}s  ({r['file']})", file=out)
        for reason in r["reasons"]:
            print(f"      - {reason}", file=out)
        if r["preview"]:
            print(f"      body: {r['preview']}", file=out)
    print(f"\n{len(results) - len(failed)} of {len(results)} sample requests passed.", file=out)
    if summary_path:
        lines = ["## Smoke test", "", "| Sample | Status | Time | Result |", "| --- | --- | --- | --- |"]
        for r in results:
            result = "; ".join(r["reasons"]) if r["reasons"] else "pass"
            lines.append(f"| {r['name']} | {r['status']} | {r['seconds']} s | {result.replace('|', '/')} |")
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return not failed


def lambda_invoker(region):
    """An `invoke` that calls the real function; its return value and any FunctionError."""
    import boto3
    from botocore.config import Config

    lam = boto3.client("lambda", region_name=region,
                       config=Config(read_timeout=150, retries={"max_attempts": 0}))

    def invoke(function_name, event):
        r = lam.invoke(FunctionName=function_name, InvocationType="RequestResponse",
                       Payload=json.dumps(event).encode("utf-8"))
        raw = r["Payload"].read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return payload, r.get("FunctionError")

    return invoke


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send the sample requests to a deployed function.")
    parser.add_argument("--function", required=True, help="function name, for example ai-app-test")
    parser.add_argument("--fixtures", default="tests/smoke", help="folder of sample request files")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args(argv)

    samples = load_samples(args.fixtures)
    if not samples:
        print(f"No sample requests in {args.fixtures}.")
        return 1
    results = run(args.function, samples, lambda_invoker(args.region))
    passed = report(results, summary_path=os.environ.get("GITHUB_STEP_SUMMARY"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
