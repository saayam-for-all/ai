#!/usr/bin/env bash
#
# Fail unless every deploy target is running the package this run just built.
#
# The deploy matrix pushes one deployment.zip to several Lambda functions and,
# until this check, never read anything back. Targets could disagree with each
# other, or with the build, while every run reported success (issue #246).
#
# This runs once, after the whole matrix, because the failure it catches is
# disagreement between targets, which no single deploy leg can see.
#
# Lambda reports CodeSha256 as the base64 SHA-256 of the zip it was given, for
# direct and S3 uploads alike, so it compares byte for byte with the artefact.
#
# Usage:
#   verify_lambda_hashes.sh <deployment.zip> "<label>=<function name or ARN>" ...
#
# Writes a table to $GITHUB_STEP_SUMMARY when that is set.

set -uo pipefail

if [ "$#" -lt 2 ]; then
  echo "::error::usage: $0 <deployment.zip> \"<label>=<function>\" ..."
  exit 2
fi

zip_path="$1"
shift

if [ ! -f "$zip_path" ]; then
  echo "::error::${zip_path} not found. Cannot verify against a build that is not here."
  exit 1
fi

expected=$(python3 -c '
import base64, hashlib, sys
with open(sys.argv[1], "rb") as fh:
    print(base64.b64encode(hashlib.sha256(fh.read()).digest()).decode())
' "$zip_path") || { echo "::error::could not hash ${zip_path}"; exit 1; }

echo "Expected CodeSha256 (from ${zip_path}): ${expected}"
echo

failures=0
rows=()

for target in "$@"; do
  label="${target%%=*}"
  function_name="${target#*=}"

  if [ "$label" = "$target" ] || [ -z "$label" ]; then
    echo "::error::Malformed target '${target}'. Expected <label>=<function>."
    failures=$((failures + 1))
    continue
  fi

  if [ -z "$function_name" ]; then
    echo "::error::${label}: function name is empty. Its Lambda ARN secret is missing."
    rows+=("| ${label} | missing secret | - |")
    failures=$((failures + 1))
    continue
  fi

  # $LATEST is what update-function-code writes and what the deploy matrix
  # targets, so that is the version compared here.
  if ! read -r actual status < <(aws lambda get-function-configuration \
        --function-name "$function_name" \
        --query '[CodeSha256, LastUpdateStatus]' \
        --output text --no-cli-pager 2>/dev/null) || [ -z "${actual:-}" ]; then
    echo "::error::${label}: could not read the function configuration."
    rows+=("| ${label} | unreadable | - |")
    failures=$((failures + 1))
    continue
  fi

  if [ "$status" != "Successful" ]; then
    # A failed or still-running update leaves the function's code in doubt,
    # whatever the hash says right now.
    echo "::error::${label}: last update status is ${status}, not Successful."
    rows+=("| ${label} | update ${status} | \`${actual}\` |")
    failures=$((failures + 1))
  elif [ "$actual" != "$expected" ]; then
    echo "::error::${label}: running ${actual}, expected ${expected}."
    rows+=("| ${label} | **different build** | \`${actual}\` |")
    failures=$((failures + 1))
  else
    echo "${label}: matches"
    rows+=("| ${label} | matches | \`${actual}\` |")
  fi
done

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## Deployed build check"
    echo
    echo "Expected \`${expected}\`"
    echo
    echo "| Target | Result | CodeSha256 |"
    echo "| --- | --- | --- |"
    # The +-expansion keeps bash 3.2 (macOS) from treating an empty array as unset.
    printf '%s\n' ${rows[@]+"${rows[@]}"}
  } >> "$GITHUB_STEP_SUMMARY"
fi

echo
if [ "$failures" -gt 0 ]; then
  echo "::error::${failures} of $# targets are not on this build."
  exit 1
fi

echo "All $# targets are running this build."
