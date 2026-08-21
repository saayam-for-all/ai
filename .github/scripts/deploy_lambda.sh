#!/usr/bin/env bash
#
# Deploy deployment.zip to one Lambda function.
#
# Uses S3 when DEPLOY_S3_BUCKET is set, which raises the ceiling from the 50 MB
# direct upload limit to 250 MB unzipped. Falls back to a direct upload when the
# bucket is not configured, so the workflow still works without new infrastructure.
#
# Required env:
#   FUNCTION_NAME    Lambda function name or ARN
# Optional env:
#   DEPLOY_S3_BUCKET S3 bucket for large packages
#   LAMBDA_TIMEOUT   seconds; when set, updates the function timeout after deploy

set -euo pipefail

if [ -z "${FUNCTION_NAME:-}" ]; then
  echo "::error::FUNCTION_NAME is empty. The Lambda ARN secret for this function is missing."
  exit 1
fi

if [ ! -f deployment.zip ]; then
  echo "::error::deployment.zip not found."
  exit 1
fi

zip_bytes=$(wc -c < deployment.zip)
echo "Package size: $((zip_bytes / 1024 / 1024)) MB (${zip_bytes} bytes)"

if [ -n "${DEPLOY_S3_BUCKET:-}" ]; then
  s3_key="lambda-deploys/${GITHUB_SHA:-manual}/deployment.zip"
  echo "Uploading to s3://${DEPLOY_S3_BUCKET}/${s3_key}"
  aws s3 cp deployment.zip "s3://${DEPLOY_S3_BUCKET}/${s3_key}"

  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --s3-bucket "$DEPLOY_S3_BUCKET" \
    --s3-key "$s3_key" \
    --no-cli-pager
else
  # 70167211 bytes is the hard request limit for UpdateFunctionCode.
  if [ "$zip_bytes" -ge 70167211 ]; then
    echo "::error::Package is ${zip_bytes} bytes, over the 70167211 byte direct upload limit."
    echo "::error::Set the DEPLOY_S3_BUCKET secret to deploy via S3."
    exit 1
  fi
  echo "DEPLOY_S3_BUCKET not set, using direct upload."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://deployment.zip \
    --no-cli-pager
fi

aws lambda wait function-updated --function-name "$FUNCTION_NAME"

if [ -n "${LAMBDA_TIMEOUT:-}" ]; then
  echo "Setting function timeout to ${LAMBDA_TIMEOUT}s"
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout "$LAMBDA_TIMEOUT" \
    --no-cli-pager
  aws lambda wait function-updated --function-name "$FUNCTION_NAME"
fi

echo "Deployed $FUNCTION_NAME"
