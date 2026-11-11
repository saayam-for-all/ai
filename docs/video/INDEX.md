# GenAI walkthrough series

This directory contains the reviewable scripts for Issue #196's short GenAI
walkthrough series.

The recordings explain **stable system behaviour and design reasons**. Changing
facts such as model names, Lambda configuration values, category/test counts,
line numbers, and endpoint lists belong to the wiki or maintained repository
documentation and must not be narrated as fixed facts.

## Episodes

| # | Episode | Owner | Script | Recording | Target |
| ---: | --- | --- | --- | --- | ---: |
| 1 | What this service is, and where it sits | @koduri24 | `01-service-overview.md` (pending) | TBD | 5 min |
| 2 | One request, end to end (`predict_category`) | @Yilmaas | `02-predict-category.md` (pending) | TBD | 7 min |
| 3 | Two integration types, and the 502 that taught us | @Drishtee0406 | `03-integration-types.md` (pending) | TBD | 5 min |
| 4 | How a change ships | @abuzarshaikh25 | [`04-how-a-change-ships.md`](04-how-a-change-ships.md) | TBD | 6 min |

## Staleness table

A recording should be re-verified when one of its named source files changes.
The commit column is the commit the final recording was made against, not
necessarily the commit that first introduced the script.

| Episode | Source files | Wiki / maintained detail owner | Recorded against | Last verified |
| --- | --- | --- | --- | --- |
| 1 — Service overview | `lambda_function.py` (`lambda_handler`) | Wiki **Home**; **GenAI Services Specification** | TBD | TBD |
| 2 — Request end to end | `lambda_function.py`; `services/classification_service.py` | Wiki **Help Request Classification Design** | TBD | TBD |
| 3 — Integration types | `lambda_function.py`; `tests/test_response_contract.py` | Wiki **GenAI Services Specification** | TBD | TBD |
| 4 — How a change ships | `tests/conftest.py`; `docs/testing/QA_RUNBOOK.md`; `docs/testing/TEST_CATALOGUE.md`; `.github/workflows/python-ci-cd.yml`; `.github/workflows/deploy_aws_lambda.yml` | Wiki **GenAI Services Specification**; `docs/testing/` | TBD | 2026-11-02 (script verified against `271a402`) |

## Update process

1. Write or update the Markdown script first.
2. Review the script before recording.
3. Verify that the narration contains no volatile values owned by the wiki.
4. Record against a known `dev` commit and add that commit to the script and
   staleness table.
5. Add the published recording link here.
6. If a named source file changes later, compare the change with the script and
   re-record only when the behaviour shown by the episode has actually changed.

## Series-level completion items

These are tracked by Issue #196 and should be completed once the recordings are
available:

- Add the series link to the repository wiki **Home** page.
- Add the series link to onboarding Mission 2.5.
- Validate the onboarding check with the next joiners as described in the issue.
- Link the finished series from the older architecture/documentation issues.
