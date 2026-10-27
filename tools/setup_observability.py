#!/usr/bin/env python
"""Create the CloudWatch alarms and saved queries for category prediction (#197, stack 5).

The function itself only prints CLASSIFICATION_OUTCOME lines (see
utils/classification_telemetry.py); CloudWatch turns those into metrics on its
own. Alarms and saved Logs Insights queries are account configuration, not
code that ships in the Lambda, so they are created by this script, from the
definitions in tools/observability/classification.json.

    python tools/setup_observability.py                     # dry run: print what would be created
    python tools/setup_observability.py --apply \\
        --log-group /aws/lambda/<predict-category-function> \\
        [--sns-topic arn:aws:sns:...] [--region us-east-1]

The default is a dry run, and --apply needs AWS credentials allowed to call
cloudwatch:PutMetricAlarm and logs:PutQueryDefinition. Both calls are
upserts keyed by name, so running it twice changes nothing the second time.
"""

from __future__ import annotations

import argparse
import json
import pathlib

DEFINITIONS_PATH = pathlib.Path(__file__).resolve().parent / "observability" / "classification.json"


def load_definitions(path: pathlib.Path = DEFINITIONS_PATH) -> dict:
    """Read the alarm and query definitions."""
    return json.loads(path.read_text(encoding="utf-8"))


def _metric(query_id: str, name: str, definitions: dict, period: int) -> dict:
    """One raw metric for a metric-math alarm, summed over the period."""
    return {
        "Id": query_id,
        "ReturnData": False,
        "MetricStat": {
            "Metric": {
                "Namespace": definitions["namespace"],
                "MetricName": name,
                "Dimensions": [{"Name": k, "Value": v} for k, v in definitions["dimensions"].items()],
            },
            "Period": period,
            "Stat": "Sum",
        },
    }


def alarm_request(alarm: dict, definitions: dict, sns_topic: str | None = None) -> dict:
    """The `put_metric_alarm` arguments for one alarm definition.

    The alarm is on a *rate*: the summed numerator metrics divided by
    Requests. Below `min_requests` in a period the rate is reported as 0, so
    one General answer at 3am on a quiet day does not page anyone. Periods
    with no data at all are not breaching, for the same reason.
    """
    period = alarm["period_seconds"]
    queries = [_metric("requests", "Requests", definitions, period)]
    numerator_ids = []
    for index, name in enumerate(alarm["numerator"]):
        query_id = f"n{index}"
        numerator_ids.append(query_id)
        queries.append(_metric(query_id, name, definitions, period))
    numerator = " + ".join(numerator_ids)
    queries.append(
        {
            "Id": "rate",
            "ReturnData": True,
            "Label": f"({' + '.join(alarm['numerator'])}) / Requests",
            "Expression": f"IF(requests >= {alarm['min_requests']}, ({numerator}) / requests, 0)",
        }
    )
    request = {
        "AlarmName": alarm["name"],
        "AlarmDescription": alarm["description"],
        "Metrics": queries,
        "ComparisonOperator": "GreaterThanThreshold",
        "Threshold": alarm["threshold"],
        "EvaluationPeriods": alarm["evaluation_periods"],
        "DatapointsToAlarm": alarm["evaluation_periods"],
        "TreatMissingData": "notBreaching",
    }
    if sns_topic:
        request["AlarmActions"] = [sns_topic]
        request["OKActions"] = [sns_topic]
    return request


def query_request(query: dict, log_group: str) -> dict:
    """The `put_query_definition` arguments for one saved Logs Insights query."""
    return {"name": query["name"], "queryString": query["query"], "logGroupNames": [log_group]}


def plan(definitions: dict, log_group: str, sns_topic: str | None = None) -> dict:
    """Every request this script would send, without sending any."""
    return {
        "alarms": [alarm_request(a, definitions, sns_topic) for a in definitions["alarms"]],
        "queries": [query_request(q, log_group) for q in definitions["queries"]],
    }


def apply(requests: dict, cloudwatch, logs) -> None:
    """Send the planned requests. Clients are passed in so tests can fake them.

    A saved query is matched to an existing one by name and updated in place,
    because put_query_definition creates a duplicate when given no id.
    """
    for request in requests["alarms"]:
        cloudwatch.put_metric_alarm(**request)
        print(f"alarm  {request['AlarmName']}")

    existing = {}
    for page in logs.get_paginator("describe_query_definitions").paginate():
        for definition in page.get("queryDefinitions", []):
            existing[definition["name"]] = definition["queryDefinitionId"]
    for request in requests["queries"]:
        if request["name"] in existing:
            request = {**request, "queryDefinitionId": existing[request["name"]]}
        logs.put_query_definition(**request)
        print(f"query  {request['name']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="create or update them in AWS")
    parser.add_argument("--log-group", default="/aws/lambda/<predict-category-function>",
                        help="the Predict Category function's log group")
    parser.add_argument("--sns-topic", help="SNS topic ARN to notify on alarm and recovery")
    parser.add_argument("--region", help="AWS region; defaults to the configured one")
    args = parser.parse_args(argv)

    requests = plan(load_definitions(), args.log_group, args.sns_topic)
    if not args.apply:
        print(json.dumps(requests, indent=2))
        print("\nDry run: nothing was sent. Add --apply --log-group <name> to create these.")
        return 0
    if args.log_group.startswith("/aws/lambda/<"):
        parser.error("--apply needs the real --log-group of the Predict Category function")

    import boto3

    session = boto3.session.Session(region_name=args.region)
    apply(requests, session.client("cloudwatch"), session.client("logs"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
