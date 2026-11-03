# Provenance for `services/organizations.json`

Organizations are shown to people looking for help, and the Organizations tab
sorts them by rating. A listing that looks authoritative but is wrong sends
someone to the wrong place. So every record in the dataset has to be traceable
to a source and verified by a person before it is committed. This file sets the
rules, in the same spirit as
[`emergency_numbers_provenance.md`](emergency_numbers_provenance.md), for the
dataset served by `utils/grounded_orgs.py` (issue #197, stack 3).

## Rules

1. **A claim is added only from a source a person can open.** The organization's
   own website, a government registry (for US nonprofits, the IRS Tax Exempt
   Organization Search), or the page of a recognised charity evaluator for a
   rating. Not a blog, not a scraped directory, and never a language model's
   unaided recall.
2. **A language model may research, but never decide.** Using a model to find a
   candidate organization and its citation is fine. The citation is then opened
   and read by a person, and that person's verification is what justifies the
   commit. The person's name and the date go in `verified_by` and `verified_on`.
3. **Never at request time.** `grounded_orgs.py` calls no model. Results are
   deterministic and instant, and there is no provider to have an outage.
4. **A blank is better than a guess.** If a rating or size cannot be sourced,
   leave `rating` at `0.0` and `size` empty. A blank makes no claim and needs no
   source. The code never fills a blank `location` or `causes` from the request.
5. **Every claim has a source.** Each non-empty value in `organization_name`,
   `org_type`, `size`, `rating`, `location`, `contact`, `email`, `web_url`,
   `mission` and `description` needs an `https://` URL under `sources` with the
   same field name. A record that breaks this is dropped when the dataset is
   loaded and fails `tests/test_grounded_orgs.py`.
6. **Nothing is invented to fill a gap.** An empty dataset returns no results.

## Record format

| Field | Meaning |
| --- | --- |
| `source_id` | Stable ID for the record, for example `org-0001`. |
| `organization_name`, `org_type`, `size`, `rating`, `location`, `contact`, `email`, `web_url`, `mission`, `description` | The contract fields. Rating is on the 0.0-5.0 scale. |
| `causes` | List of cause areas, for example `["Food Security"]`. |
| `categories` | Taxonomy IDs this organization serves (the dotted IDs in `utils/predict_category_list.py`, such as `"1.2"`). |
| `service_area` | Where it serves: `"San Jose, CA"` (city), `"CA"` (state) or `"US"` (national). |
| `keywords` | Optional words that should match a request when no category does. |
| `sources` | Object mapping each claimed field to its `https://` source URL. |
| `verified_by`, `verified_on` | Who verified the record, and when (`YYYY-MM-DD`). |

## Adding a record

1. Find the organization from an official source (rule 1).
2. Open every source and read the value it supports. Copy only what it says.
3. Fill `sources` for every field you filled in; leave the rest blank.
4. Put your name and today's date in `verified_by` and `verified_on`.
5. Run `pytest tests/test_grounded_orgs.py`. The dataset test fails if any rule
   above is broken.

## Proxy data (current state of the file)

For the issue #197 experiment the maintainers agreed that proxy data is fine
while the real Saayam data is not available. So `services/organizations.json`
currently holds **made-up** records for three cities (Chicago, Houston, Seattle)
plus one national helpline, covering food assistance (`1.1`), donating clothes
(`2.1`) and housing/shelter (`3`). The classifier has no separate shelter
category, so shelter is filed under Housing (`3`).

Proxy records are kept honest by these rules:

- The name ends with `(proxy data)`.
- `verified_by` is `proxy-data`, never a person's name, because no one checked
  these against a real source.
- Sources, web addresses and emails use the reserved `example.org` domain, and
  phone numbers use the fictional `555-01xx` range.
- `rating` and `size` are blank. No number is invented.

`tests/test_grounded_orgs.py` checks the labels. Before any real use, replace
the proxy records with records a person has verified (see "Adding a record").

## Records

`proxy-001` to `proxy-010`: proxy data, as described above. No verified records yet.
