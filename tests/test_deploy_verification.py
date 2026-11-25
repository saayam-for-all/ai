"""Post-deploy build check - issue #246.

The deploy matrix pushes one deployment.zip to five Lambda functions. Until
this check it read nothing back, so the five could end up on different builds,
or keep a hand-edited version, while every run reported success.

``.github/scripts/verify_lambda_hashes.sh`` runs once after the matrix and fails
unless every target's CodeSha256 equals the hash of the zip that run built.
These tests drive the real script against a fake ``aws`` on PATH, and pin the
workflow wiring so a sixth function cannot be added to the matrix without also
being verified.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".github" / "scripts" / "verify_lambda_hashes.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy_aws_lambda.yml"

TARGETS = {
    "Predict Category": "pred-cat",
    "Generate Subject": "gen-sub",
    "Generate Answer": "gen-ans",
    "Emergency Contacts": "emr-con",
    "More Organizations": "more-org",
}

# Stands in for `aws lambda get-function-configuration --query
# '[CodeSha256, LastUpdateStatus]' --output text`. Functions missing from the
# state behave like an AWS error.
FAKE_AWS = """\
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LAMBDA_CALLS"], "a") as log:
    log.write(" ".join(args) + "\\n")
name = args[args.index("--function-name") + 1]
state = json.loads(os.environ["FAKE_LAMBDA_STATE"])
if name not in state:
    sys.stderr.write("ResourceNotFoundException\\n")
    sys.exit(254)
sha, status = state[name]
print(sha + "\\t" + status)
"""

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _sha(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


@pytest.fixture
def deploy_env(tmp_path):
    """A built zip, a fake aws CLI on PATH, and a runner for the script."""
    zip_bytes = b"PK\x03\x04 pretend deployment package"
    (tmp_path / "deployment.zip").write_bytes(zip_bytes)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_AWS)
    fake.chmod(0o755)

    calls = tmp_path / "calls.log"
    calls.touch()
    summary = tmp_path / "summary.md"

    def run(state, targets=None):
        if targets is None:
            targets = [f"{label}={fn}" for label, fn in TARGETS.items()]
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LAMBDA_STATE": json.dumps(state),
            "FAKE_LAMBDA_CALLS": str(calls),
            "GITHUB_STEP_SUMMARY": str(summary),
        }
        return subprocess.run(
            ["bash", str(SCRIPT), "deployment.zip", *targets],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )

    run.expected = _sha(zip_bytes)
    run.calls = calls
    run.summary = summary
    return run


def _all_on(sha, status="Successful"):
    return {fn: [sha, status] for fn in TARGETS.values()}


@needs_bash
def test_passes_when_every_target_runs_the_built_zip(deploy_env):
    """Five targets on the artefact's hash is the only state that passes."""
    result = deploy_env(_all_on(deploy_env.expected))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All 5 targets are running this build." in result.stdout


@needs_bash
def test_fails_and_names_the_one_target_on_a_different_build(deploy_env):
    """One diverged target fails the run, and the error says which one."""
    state = _all_on(deploy_env.expected)
    state["gen-ans"] = [_sha(b"an older build"), "Successful"]

    result = deploy_env(state)

    assert result.returncode == 1
    assert "::error::Generate Answer: running" in result.stdout
    assert "1 of 5 targets are not on this build" in result.stdout
    for label in TARGETS:
        if label != "Generate Answer":
            assert f"{label}: matches" in result.stdout


@needs_bash
def test_fails_when_all_targets_agree_with_each_other_but_not_the_build(deploy_env):
    """Five identical stale targets is still a failure: agreement is not enough."""
    result = deploy_env(_all_on(_sha(b"last week's build")))

    assert result.returncode == 1
    assert "5 of 5 targets are not on this build" in result.stdout


@needs_bash
@pytest.mark.parametrize("status", ["Failed", "InProgress"])
def test_fails_when_a_target_update_did_not_finish_successfully(deploy_env, status):
    """A failed or in-flight update leaves the code in doubt, even on the right hash."""
    state = _all_on(deploy_env.expected)
    state["emr-con"] = [deploy_env.expected, status]

    result = deploy_env(state)

    assert result.returncode == 1
    assert f"Emergency Contacts: last update status is {status}" in result.stdout


@needs_bash
def test_fails_when_a_target_cannot_be_read(deploy_env):
    """An AWS error on read-back is a failure, never a silent skip."""
    state = _all_on(deploy_env.expected)
    del state["more-org"]

    result = deploy_env(state)

    assert result.returncode == 1
    assert "More Organizations: could not read the function configuration" in result.stdout


@needs_bash
def test_fails_on_a_missing_arn_secret_without_calling_aws_for_it(deploy_env):
    """An empty secret is reported as missing rather than sent to AWS as a blank name."""
    targets = [f"{label}={fn}" for label, fn in TARGETS.items()]
    targets[0] = "Predict Category="

    result = deploy_env(_all_on(deploy_env.expected), targets)

    assert result.returncode == 1
    assert "Predict Category: function name is empty" in result.stdout
    assert len(deploy_env.calls.read_text().splitlines()) == 4


@needs_bash
def test_reads_back_the_hash_and_update_status_of_latest(deploy_env):
    """The query asks Lambda for exactly the two fields the comparison uses."""
    deploy_env(_all_on(deploy_env.expected))

    call = deploy_env.calls.read_text().splitlines()[0]
    assert call.startswith("lambda get-function-configuration --function-name pred-cat")
    assert "--query [CodeSha256, LastUpdateStatus]" in call
    assert "--qualifier" not in call


@needs_bash
def test_writes_a_per_target_table_to_the_step_summary(deploy_env):
    """The run summary shows every target's result, so a red run says where to look."""
    state = _all_on(deploy_env.expected)
    state["gen-sub"] = [_sha(b"other"), "Successful"]

    deploy_env(state)

    summary = deploy_env.summary.read_text()
    assert f"Expected `{deploy_env.expected}`" in summary
    assert "| Generate Subject | **different build** |" in summary
    assert summary.count("| matches |") == 4


@needs_bash
def test_fails_when_the_built_zip_is_absent(deploy_env, tmp_path):
    """Without the artefact there is nothing to compare against, so it cannot pass."""
    (tmp_path / "deployment.zip").unlink()

    result = deploy_env(_all_on("anything"))

    assert result.returncode == 1
    assert "deployment.zip not found" in result.stdout


def test_every_deployed_function_is_also_verified():
    """Each ARN secret in the deploy matrix is passed to the verify step."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    deployed = {row["arn_secret"] for row in jobs["deploy"]["strategy"]["matrix"]["include"]}

    step = next(s for s in jobs["verify"]["steps"] if "verify_lambda_hashes.sh" in s.get("run", ""))
    assert set(step["env"]) == deployed
    for secret in deployed:
        assert step["env"][secret] == f"${{{{ secrets.{secret} }}}}"
        assert f"=${secret}\"" in step["run"]


def test_verify_runs_after_the_whole_matrix_even_when_a_leg_fails():
    """The check waits for every deploy leg and still runs if one of them failed."""
    verify = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["verify"]

    assert "deploy" in verify["needs"] and "build" in verify["needs"]
    assert "!cancelled()" in verify["if"]
    assert "needs.build.result == 'success'" in verify["if"]
