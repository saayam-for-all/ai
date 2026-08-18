# Volunteer Matching: Current State Baseline

What the matcher does today, before any clustering, fuzzy matching, or match-%
work. Every number here came from running the code on the checked-in sample data.

Base branch: `feature/volunteer_matching_algorithm` (commit `658fe8e`)
Related: issues #37, #42, #43

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # pulls torch + sentence-transformers, ~2GB
cd volunteer_matching_algorithm      # data paths are relative, this matters
PYTHONPATH=. python scripts/baseline_run.py
```

First run downloads the `all-MiniLM-L6-v2` weights (~90MB) from Hugging Face, so it
needs network access. To serve the API instead, run `uvicorn main:app --reload` from
the same directory.

`scripts/baseline_run.py` regenerates every number below.

## Pipeline

`data_loader.py` reads both CSVs, fills NaN on string columns with `""`, and coerces
`Rating` and `Duration` to numeric.

`matcher.match_volunteers(request_id, top_k)` then does the work:

1. Filters to `Status == "Active"` volunteers (169 of 507).
2. Builds two text blobs:
   - volunteer: `Skills + " " + PreferredServiceAreas`
   - request: `RequestCategory + " " + Subject + " " + Description`
3. Scores those against each other two ways:
   - `TFIDF_Sim` from `preprocessing.prepare_tfidf` (sklearn, `stop_words="english"`,
     fit per request over volunteer texts plus the request text)
   - `BERT_Sim` from `embeddings.get_embedding` (all-MiniLM-L6-v2, 384-dim, cosine)
   - combined as `TextSim = 0.30 * TFIDF_Sim + 0.70 * BERT_Sim`
4. Computes `SkillMatch` separately: cosine between `BERT(Skills)` and
   `BERT(RequestCategory)`.
5. Computes two attribute scores:
   - `LanguageMatch`: `1 if req_lang in LanguagesSpoken else 0` (substring test)
   - `LocationScore`: `1.0` if `RequestType == "Remote"`, otherwise
     `TransportationAvailability` (Yes 1.0 / No 0.3) multiplied by
     `WillingnessToTravel` (High 1.2 / Moderate 1.0 / Low 0.8), capped at 1.0
6. Hands all of it to `scoring.calculate_score`:

```
FinalScore = 0.50 * TextSim
           + 0.20 * SkillMatch
           + 0.15 * LanguageMatch
           + 0.10 * LocationScore
           + 0.05 * (Rating / 5)
```

7. Sorts descending, returns `head(top_k)`.

`match_volunteer_group` sits on top of that. It pulls a pool of `2 * group_size` from
`match_volunteers`, takes the top scorer as "Lead", then greedily adds members using a
second, separate scoring function, `calculate_diversity_score` (0.30 relevance + 0.25
skill diversity + 0.20 language diversity + 0.15 rating balance + 0.10 location spread).

API surface in `main.py`: `POST /volunteers`, `POST /requests`,
`GET /match/{request_id}`, `GET /volunteers`, `GET /requests`.

## Sample data

| | count |
|---|---|
| requests.csv rows | 504 |
| with `REQ_ID` populated | 4 (`REQ_1`-`REQ_4`) |
| volunteers.csv rows | 507 |
| with `VOL_ID` populated | 6 (`VOL_1`-`VOL_6`) |
| volunteers with `Status == "Active"` | 169 |

Volunteer `Status` values: `Unavailable` 178, `Active` 169, `OnBreak` 157, `open` 2,
`Available` 1.

Request `RequestType` values: `Remote` 271, `InPerson` 230, `In-Person` 2, `Urgent` 1.

This constrains the whole baseline. `match_volunteers` looks requests up by `REQ_ID`,
so only 4 of the 504 requests can be addressed at all. The ticket asked for roughly 5
sample requests; 4 is the complete reachable set, so that is what is recorded below.

The 6 rows with IDs are hand-seeded fixtures appended to the end of the generated data
(`Sita Rao`, `John Doe`, `John Daniel`, `Lara` x2, `Danny`), and `REQ_1`-`REQ_4` were
written to match them.

## Baseline results

`match_volunteers(req_id, top_k=5)` against 169 active volunteers. Roughly 2.6-2.9s
per request.

### REQ_1: Medical, "Need First Aid", Telugu, Urgent

Description: "Person injured and bleeding."

| # | Volunteer | Skills | TFIDF | BERT | SkillMatch | Lang | Loc | TextSim | Rating | FinalScore |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Sita Rao | Medical Aid, First Aid | 0.1437 | 0.6386 | 0.5363 | 1 | 0.8 | 0.4902 | 4.8 | 0.6303 |
| 2 | John Ryan | First Aid, Medical Aid | 0.1437 | 0.5993 | 0.5341 | 1 | 1.0 | 0.4626 | 4.1 | 0.6291 |
| 3 | William Morgan | Medical Aid | 0.1161 | 0.4259 | 0.7444 | 1 | 1.0 | 0.3330 | 3.6 | 0.6014 |
| 4 | Dustin Chang | Medical Aid | 0.1161 | 0.4352 | 0.7444 | 1 | 0.8 | 0.3394 | 4.8 | 0.5966 |
| 5 | Leroy Campbell | Medical Aid | 0.1161 | 0.4385 | 0.7444 | 1 | 0.3 | 0.3417 | 4.2 | 0.5417 |

### REQ_2: Education and Career Support, tutoring, English, Remote

Description: "Looking for someone to help with math and science tutoring for a 10th
grade student preparing for exams."

| # | Volunteer | Skills | TFIDF | BERT | SkillMatch | Lang | Loc | TextSim | Rating | FinalScore |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | John Daniel | Teaching, Counseling | 0.1456 | 0.3561 | 0.4846 | 1 | 1 | 0.2930 | 4.5 | 0.5384 |
| 2 | Craig Nicholson | Counseling, Medical Aid, Logistics, Teaching | 0.0000 | 0.3733 | 0.4935 | 1 | 1 | 0.2613 | 4.6 | 0.5254 |
| 3 | Jennifer Carr | Teaching, Counseling | 0.0000 | 0.3763 | 0.4846 | 1 | 1 | 0.2634 | 4.4 | 0.5226 |
| 4 | Mrs. Paige Farley | Logistics, Teaching | 0.0000 | 0.3805 | 0.4313 | 1 | 1 | 0.2664 | 4.9 | 0.5184 |
| 5 | Angela Russo | Medical Aid, Counseling, Teaching, Child Care | 0.0000 | 0.3950 | 0.4562 | 1 | 1 | 0.2765 | 3.4 | 0.5135 |

### REQ_3: Education, "Math Tutoring Program", English, In-Person

Description: "Need volunteers to tutor middle school students in mathematics"

| # | Volunteer | Skills | TFIDF | BERT | SkillMatch | Lang | Loc | TextSim | Rating | FinalScore |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | John Daniel | Teaching, Counseling | 0.2208 | 0.3769 | 0.5160 | 1 | 1.0 | 0.3301 | 4.5 | 0.5632 |
| 2 | Mrs. Paige Farley | Logistics, Teaching | 0.0000 | 0.3832 | 0.4975 | 1 | 1.0 | 0.2683 | 4.9 | 0.5326 |
| 3 | Jon Huang | Teaching, Cooking | 0.0000 | 0.3393 | 0.5518 | 1 | 1.0 | 0.2375 | 3.4 | 0.5131 |
| 4 | John Doe | Teaching, Counseling, Cooking | 0.1547 | 0.2791 | 0.4579 | 1 | 1.0 | 0.2418 | 4.5 | 0.5075 |
| 5 | Craig Nicholson | Counseling, Medical Aid, Logistics, Teaching | 0.0000 | 0.3733 | 0.3864 | 1 | 1.0 | 0.2613 | 4.6 | 0.5039 |

### REQ_4: Clothing Assistance, donations for shelter, English, In-Person

Description: "We are collecting gently used clothing items including shirts, pants,
jackets, and shoes. Looking for volunteers to help sort and distribute donated clothes
to families in need."

| # | Volunteer | Skills | TFIDF | BERT | SkillMatch | Lang | Loc | TextSim | Rating | FinalScore |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Danny | Clothing donation, thrift store organization, sorting donated clothes | 0.3292 | 0.8049 | 0.6684 | 1 | 1.0 | 0.6622 | 4.5 | 0.7598 |
| 2 | Deborah Barker | Elderly Care, Medical Aid | 0.0000 | 0.2807 | 0.3151 | 1 | 1.0 | 0.1965 | 4.7 | 0.4583 |
| 3 | Trevor Stuart | Elderly Care, Medical Aid, Child Care, First Aid | 0.0000 | 0.2787 | 0.3020 | 1 | 1.0 | 0.1951 | 4.9 | 0.4570 |
| 4 | Clinton Massey | Elderly Care, Child Care, First Aid | 0.0000 | 0.3317 | 0.3358 | 1 | 0.8 | 0.2322 | 4.1 | 0.4543 |
| 5 | Sita Rao | Medical Aid, First Aid | 0.0000 | 0.3118 | 0.3232 | 1 | 0.8 | 0.2183 | 4.8 | 0.4518 |

### Group mode

`match_volunteer_group("REQ_1", group_size=3)` returns 2 members, not 3. See item 2
under Broken below.

| Volunteer | Role | FinalScore |
|---|---|---|
| Sita Rao | Lead | 0.6303 |
| Leroy Campbell | Member | 0.5417 |

### Score distribution, REQ_1, all 169 active volunteers

| min | p25 | median | p75 | max |
|---|---|---|---|---|
| 0.1504 | 0.2328 | 0.3301 | 0.4087 | 0.6303 |

### Edge case

`match_volunteers("REQ_999")` returns an empty DataFrame. `main.py` turns that into a
200 with "No suitable volunteers found." That is reasonable, but a missing request and
a request with zero eligible volunteers look identical to the caller.

## What works

- CSV loading and NaN cleaning (`data_loader.py`). Real, handles per-column defaults
  and numeric coercion.
- TF-IDF (`preprocessing.py`). Real sklearn `TfidfVectorizer`.
- BERT embeddings (`embeddings.py`). Real all-MiniLM-L6-v2, with zero-vector and
  zero-norm guards.
- Weighted scoring (`scoring.py`). All five components are populated and contribute.
  Nothing is hardcoded or short-circuited.
- Single-volunteer matching end to end. Rankings are sensible. REQ_4 is the clearest
  case: the volunteer whose skills literally describe the request scores 0.76, next
  best is 0.46.
- `POST /volunteers` and `POST /requests` do append to the CSVs.

## What is broken or incomplete

1. **`REQ_ID` and `VOL_ID` are almost entirely empty.** 4 of 504 requests, 6 of 507
   volunteers. `/match/{request_id}` can only ever address 4 requests. This blocks
   any evaluation work.

2. **`match_volunteer_group` silently returns fewer members than asked.** The dedup
   line is `remaining = remaining[remaining["VOL_ID"] != best_addition["VOL_ID"]]`,
   which drops every row sharing that `VOL_ID`. 501 of 507 volunteers have a blank
   `VOL_ID`, so selecting one blank-ID member wipes the rest of the pool. Asking for
   3 returns 2, and larger group sizes still return 2.

3. **`match_volunteer_group` only accepts `REQ_ID`.** It hardcodes
   `requests["REQ_ID"] == request_id`, while `match_volunteers` handles both `REQ_ID`
   and `RequestId`. Commit `658fe8e` ("fixed inconsistency of REQ-ID and RequestId
   formats") only patched one of the two.

4. **The `Status` filter is case and vocabulary sensitive.** `== "Active"` excludes
   the 2 `open` and 1 `Available` rows. There is no canonical status enum anywhere.

5. **TF-IDF contributes nothing for most candidates.** 90 of 169 active volunteers
   score exactly 0.0 on `TFIDF_Sim` for REQ_1, because volunteer text is a short skill
   list that shares no literal tokens with the request prose. The 30%-of-50% TF-IDF
   weight is effectively inactive for most of the pool. Worth knowing before anyone
   tunes the weights.

6. **Language matching is substring containment, not set membership.**
   `1 if req_lang in x else 0` over the raw `LanguagesSpoken` string. It works on this
   data, but any language name that is a substring of another will false-positive.

7. **`RequestType` mixes modality and urgency.** Values are `Remote` (271),
   `InPerson` (230), `In-Person` (2), `Urgent` (1). `LocationScore` branches on
   `== "Remote"`, so `Urgent` (REQ_1) lands in the in-person branch by accident, and
   `In-Person` vs `InPerson` is an unnormalized duplicate.

8. **Scores are not calibrated and cannot be shown as a match percentage.** For REQ_1
   the range across all active volunteers is 0.15 to 0.63. A near-perfect match tops
   out around 0.63-0.76, never near 1.0, and an unrelated volunteer still floors at
   ~0.15 because rating (5%) and location (10%) pay out regardless of relevance.
   Showing `FinalScore` directly as a percentage would mislead users.

9. **Two independent scoring paths.** `scoring.calculate_score` and
   `matcher.calculate_diversity_score` both encode weighting logic, with different
   weights, in different files. Any change to relevance has to be made twice.

10. **Embeddings are recomputed per request, one at a time.**
    `[get_embedding(v) for v in volunteer_texts]` plus a second pass for `SkillMatch`
    is about 338 individual `model.encode()` calls per request at 169 volunteers. No
    batching, no caching, no persistence. ~2.7s per request at this size, scaling
    linearly.

11. **No tests.** No `tests/` directory, no `test_*.py` under
    `volunteer_matching_algorithm/`.

12. **`id_generator.generate_id` is fragile.** It takes the last non-empty ID and
    increments. Given the sparse ID column it works by luck, has no uniqueness
    guarantee, and will collide if rows are deleted or reordered.

13. **`.idea/` is committed.** Should be gitignored.

14. **No fuzzy, synonym, or clustering logic exists yet.** Expected, since that is the
    follow-up work. The BERT layer is the only thing bridging vocabulary gaps today.

## Schema: current vs. Issue #42

Current schema, from `models.py` and the CSV headers:

| VolunteerModel | HelpRequestModel |
|---|---|
| `VolunteerName`, `ContactInformation`, `Location` | `RequestCategory`, `Location`, `RequestType` |
| `Skills` (flat comma string) | `PriorityLevel`, `LeadVolunteerNeeded` |
| `LanguagesSpoken`, `PreferredServiceAreas` | `ForSelfOrOthers`, `IsCalamity` |
| `Rating`, `Status` | `Subject`, `Description`, `LanguagePreferred` |
| `TransportationAvailability`, `WillingnessToTravel` | `RequestorId`, `Status`, `Duration` |

Gaps against `Issue42/volunteer_match.py`:

| Issue #42 field | Status today | Impact on matching |
|---|---|---|
| `availability_days` (e.g. `Saturday,Sunday`) | dropped | #42 used day overlap as a hard filter. Nothing now prevents matching a volunteer who is never free when the request needs them. |
| `availability_frequency` (weekly/biweekly) | dropped | #42 required an exact frequency match against `time_commitment_frequency`. |
| `skills` with proficiency (`logistics:3`) | degraded | #42 could require a minimum skill level. `Skills` is now an unweighted comma string, so "knows a little cooking" and "professional chef" are identical to the matcher. |
| `certifications` (e.g. `First Aid`) | dropped | No way to require a credential. REQ_1 ("person injured and bleeding") is exactly where this matters. |
| `past_hours` | dropped | Experience signal. Only the 0-5 `Rating` proxies for it, at 5% weight. |
| `age` | dropped | #42 loaded it but never used it. Low priority. |
| `preferred_task_type` | kept as `PreferredServiceAreas` | Now free text feeding the embedding rather than a category. |
| request `time_commitment` | reduced to `Duration` (int) | #42 had structured days plus frequency. Now a bare integer with no stated unit, and the matcher never reads it. |
| `priority` | kept as `PriorityLevel` | In the data, but the matcher never reads it. A High priority request scores identically to a Low one. |

Fields present but never read by the matcher: `Duration`, `PriorityLevel`,
`LeadVolunteerNeeded`, `ForSelfOrOthers`, `IsCalamity`, `RequestorId`,
`AssignedVolunteer`, `ContactInformation`, and volunteer `Location` (only
`TransportationAvailability` and `WillingnessToTravel` feed `LocationScore`; the
`Location` string itself is ignored outside group mode).

`IsCalamity` and `PriorityLevel` in particular look like they were collected for
matching and then never wired in. Also note that request `Location` and volunteer
`Location` are never compared, so in-person matching currently means "does this person
own a car", not "are they anywhere near the requester".

## Sub-tasks this unblocks

Ordered by dependency.

Foundational, blocks the rest:

1. Pick a canonical ID scheme and backfill `REQ_ID` / `VOL_ID` across all 504 and 507
   rows, or drop them and key off the existing UUID `RequestId` / `VolunteerId`.
   Nothing can be evaluated at scale until this is done.
2. Normalize the enum-like columns: `Status` (`Active` / `open` / `Available`) and
   `RequestType` (`InPerson` / `In-Person` / `Urgent`). Split modality from urgency.
3. Add a test harness. Even a few assertions like "REQ_4 ranks Danny first" gives the
   follow-up work a regression net.

Schema:

4. Decide which Issue #42 fields come back. Availability and certifications are the
   two worth prioritizing, since they are hard constraints that semantic similarity
   cannot substitute for. Skill proficiency is the natural third.
5. Wire up the fields already collected but ignored, starting with `PriorityLevel` and
   `IsCalamity`.
6. Add real geographic matching between request `Location` and volunteer `Location`.

Algorithm, the actual ticket work:

7. Fuzzy and synonym matching. Language and skill tokens are the two places exact
   string comparison is currently doing the work.
8. Clustering.
9. Match-% calibration. Needs a defined target scale, since raw `FinalScore` maxes out
   near 0.63-0.76 and floors near 0.15.
10. Consolidate `calculate_score` and `calculate_diversity_score` into one scoring
    module before adding weights to either.

Performance:

11. Batch and cache the embeddings. One `model.encode(list_of_texts)` call instead of
    338, and precompute volunteer embeddings rather than recomputing per request.
