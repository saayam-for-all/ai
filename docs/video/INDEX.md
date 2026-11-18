# GenAI Walkthrough Series

This page is the index for Issue #196's GenAI walkthrough series. Each episode explains stable system behaviour and design reasoning, while changing values are maintained on the relevant wiki or repository documentation pages.

## Episodes

| # | Episode | Owner | Script / wiki page | Recording | Target |
| ---: | --- | --- | --- | --- | ---: |
| 1 | What this service is, and where it sits | @koduri24 | Episode 1 wiki page after approval | TBD | 5 min |
| 2 | One request, end to end (`predict_category`) | @Yilmaas | Episode 2 wiki page after approval | TBD | 7 min |
| 3 | Two integration types, and the 502 that taught us | @Drishtee0406 | Episode 3 wiki page after approval | TBD | 5 min |
| 4 | How a change ships | @abuzarshaikh25 | [[Episode 4: How a Change Ships]] | TBD | 6 min |

## Staleness table

A recording should be re-verified when one of its named source files changes. The commit column records the commit the final recording was made against.

| Episode | Source files | Maintained detail owner | Recorded against | Last verified |
| --- | --- | --- | --- | --- |
| 1 — Service overview | `lambda_function.py` (`lambda_handler`) | Wiki **Home**; **GenAI Services Specification** | TBD | TBD |
| 2 — Request end to end | `lambda_function.py`; `services/classification_service.py` | **Help Request Classification Design** | TBD | TBD |
| 3 — Integration types | `lambda_function.py`; `tests/test_response_contract.py` | **GenAI Services Specification** | TBD | TBD |
| 4 — How a change ships | `tests/conftest.py`; `docs/testing/QA_RUNBOOK.md`; `docs/testing/TEST_CATALOGUE.md`; `.github/workflows/python-ci-cd.yml`; `.github/workflows/deploy_aws_lambda.yml` | **GenAI Services Specification**; `docs/testing/` | TBD | 2026-11-18 (script verified against `b0f99c1`) |

## Review and publishing process

1. Draft or update the episode script on the owner's branch.
2. Share the branch in Issue #196 and tag the requested reviewers.
3. Review the script before recording.
4. After approval, move the episode content to its wiki page.
5. Verify that the narration contains no volatile values maintained on the **GenAI Services Specification** page or other maintained documentation.
6. Record against a known `dev` commit and add that commit to the episode details and staleness table.
7. Publish the recording on the organisation's channel and add the recording link here.
8. If a named source file changes later, compare the change with the episode and re-record only if the behaviour shown in the video actually changed.

## Series-level completion items

These remain tracked by Issue #196:

- Link the series from the repository wiki **Home** page.
- Link the series from onboarding Mission 2.5.
- Validate the onboarding check with the next joiners as described in the issue.
- Link the finished series from the older architecture/documentation issues.
