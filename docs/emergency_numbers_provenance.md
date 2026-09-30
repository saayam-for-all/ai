# Provenance for `services/emergency_numbers.json`

Emergency numbers are dialled by people in crisis, so every value in the
directory has to be traceable to an official source and verified by a person
before it is committed. This file records where the values changed for
[issue #146](https://github.com/saayam-for-all/ai/issues/146) came from, and
the rules that govern future changes.

## Rules

1. **A number is added only from an official source** — a government or
   national emergency-service page, or an ITU/EENA published list. Not a blog,
   not a travel site, and never a language model's unaided recall.
2. **A language model may research, but never decide.** Using a web-grounded
   model to *find* a candidate number and its citation is fine and is the
   intended way to close the remaining gaps. The citation is then opened and
   read by a person, and it is that person's verification that justifies the
   commit. No number reaches a user because a model produced it.
3. **Never at request time.** The resolver does not call a model. A generated
   number looks authoritative and would be dialled; a wrong one is a larger
   liability than showing "unavailable". Resolution must also be deterministic
   and instant, and model calls in this codebase are neither — category
   prediction takes seven to thirteen seconds and returns different results for
   identical inputs.
4. **Nothing crosses a border.** A number may only appear under the country it
   belongs to. `test_emergency_dataset.py` and `test_emergency_locale.py`
   enforce this on every build.

## Changes made for issue #146

### Corrections to existing values

| Country | Field | Was | Now | Why |
| --- | --- | --- | --- | --- |
| AU | `police`, `ambulance`, `fire` | `"0"` | `"000"` | Australia's emergency number is Triple Zero, `000`. The stored value had lost its leading zeros, which is what happens when a number is round-tripped through a spreadsheet as an integer. `"0"` is not dialable and no country uses it. Source: Australian Government, Triple Zero (000) service. |
| PK | `ambulance` | `"115 and 1122"` | `"1122"` | The stored value was prose, not a number: a click-to-call link built from it cannot connect. `1122` is Rescue 1122, Pakistan's government emergency ambulance and rescue service. `115` is the Edhi Foundation ambulance, a charity line; the government service is the correct primary. Source: Punjab Emergency Service (Rescue 1122). |

### Services added for India

Issue #146 names these routes explicitly. India already had `police` (112),
`ambulance` (108) and `fire` (101) on record.

| Field | Value | Notes |
| --- | --- | --- |
| `general_emergency` | `112` | The pan-India single emergency number (ERSS 112), Ministry of Home Affairs. |
| `disaster_management` | `108` | Emergency Response Service, used for medical, police and fire/disaster response across most states. |
| `women_helpline` | `1091` | National Women Helpline, Ministry of Women and Child Development. |

`ambulance` was left at `108` rather than changed to the `102` named in the
issue. Both are real. `108` is the pan-India emergency ambulance and is the
number to dial in an emergency; `102` is the free maternal and child health
ambulance and is not the general emergency route. `108` was already in the
directory and verified, so it stays.

`suicide_helpline` was left at the existing `9152987821`. It is not a US
number and satisfies the issue. It is worth a separate review: Tele-MANAS
(`14416`), the Government of India's national mental-health helpline, is
toll-free, twenty-four hour and multilingual, and is likely the better primary.
That change is deliberately **not** bundled here — replacing a working verified
number is its own reviewed change, not a side effect of a safety fix.

### `general_emergency` added

The field names a country's own pan-emergency line and is what the resolver
falls back to when a specific service is missing for that country. It was added
only where the number is well established, and only where stating it explicitly
changes or clarifies the outcome. Countries not listed here fall back to their
own `police` number, which for most of the directory *is* the national single
number.

| Country | `general_emergency` | Note |
| --- | --- | --- |
| AU | `000` | Triple Zero. |
| BE | `112` | Police is `101`; `112` is the single European emergency number. |
| CA | `911` | Same as police; stated explicitly. |
| CH | `112` | Police is `117`. |
| DE | `112` | Police is `110`. |
| GB | `999` | `112` also connects. |
| GR | `112` | Police is `100`. |
| IN | `112` | ERSS, the pan-India number. |
| NZ | `111` | Same as police; stated explicitly. |
| PL | `112` | Police is `997`. |
| RS | `112` | Police is `192`. |
| RU | `112` | Police is `102`. |
| SK | `112` | Police is `158`. |
| UA | `112` | Police is `102`. |
| US | `911` | Same as police; stated explicitly. |

`112` is the single emergency number across the EU and EEA by law
(Directive 2002/22/EC, Article 26), which is the basis for every `112` above.

## Directory replaced by the S3 dataset (issue #334, September 29, 2026)

The data team designated `s3://saayam-virginia-public/emergency_contact.json`
as the ground truth, and `services/emergency_numbers.json` is now a
byte-identical copy of it: MD5 `7dd6a88260658b3594f5abdd134e3426` (the S3
ETag), SHA-256
`e5122abde45fd5a5a471503cfbf9d9f08cf57122dd16defd4feb5db66c66dab3`. The
bundled file is only the fallback for when S3 cannot be read, and keeping the
two identical means a fallback never changes what a person is told.

Coverage grows from 73 countries to 249. Compared with the directory the
sections above describe, the S3 dataset changes the following. Rule 1
applies: these values came from the data team's dataset, not from a
per-number official source recorded here, so each is a candidate for review.

**Reverses a correction from #146**

| Country | Field | #146 value | S3 value |
| --- | --- | --- | --- |
| PK | `ambulance` | `1122` (Rescue 1122, government) | `115` (Edhi Foundation, charity) |

**Changes a documented `general_emergency`**

| Country | Was | Now | Effect |
| --- | --- | --- | --- |
| CH | `112` | absent | The general line and every fallback resolve to police, `117`. |
| UA | `112` | absent | The general line and every fallback resolve to police, `102`. |
| GB | `999` | `112` | `999` moves to `general_emergency_alternate`. |

**Replaces other stored numbers**

| Country | Changed fields |
| --- | --- |
| BG | police `112`→`166`, ambulance `112`→`150`, fire `112`→`160` |
| CO | police `123`→`112`, ambulance `123`→`125`, fire `123`→`119` |
| CZ | police `112`→`158`, ambulance `112`→`155`, fire `112`→`150` |
| EG | police `112`→`122` |
| FR | police `112`→`17`, ambulance `112`→`15`, fire `112`→`18` |
| HR | police `112`→`192`, ambulance `112`→`194`, fire `112`→`193` |
| HU | police `112`→`107`, ambulance `112`→`104`, fire `112`→`105` |
| TR | police `112`→`153` |
| UZ | ambulance `101`→`103`, fire `103`→`101` |
| VE | police, ambulance, fire `911`→`171` (`911` kept as `general_emergency`) |
| ZA | spaces removed: `10 111`→`10111`, `10 177`→`10177` |

Where a specific line replaced `112`, the country gained `general_emergency`
`112`, so the general route is unchanged for BG, CZ, EG, FR, HR, HU and TR.

**Removes regional overrides.** The previous directory had all 50 US states
and three Indian states. The S3 dataset has regional entries only for
Karnataka (Bengaluru, Mysuru, ZIP 560001). Every removed entry repeated its
country's numbers, so lookups return the same numbers, reported at
`match_level` `country` instead of `state` or `city`.

## Known gaps

These are real and are **not** closed by this change. The general-emergency
fallback means users are given a working in-country number rather than nothing,
and never a foreign one, but a dedicated line is better than a general one.

- **`suicide_helpline` is absent for 244 of 249 countries.** Only Austria,
  Australia, Canada, India and the United States have one (as of the S3
  dataset, September 29, 2026). Everywhere else the mental-health row now resolves to
  that country's general emergency line, flagged `is_fallback: true`. Closing
  this properly means researching each country's national line with a citation
  and having a person verify it, per the rules above.
- **`disaster_management` exists for 9 countries and `women_helpline` for 4.**
  Same treatment and same remedy.
- **No drift detection.** Emergency numbers change rarely but they do change,
  and nothing here re-verifies the directory against its sources. A scheduled
  job that re-checks and opens an issue on a discrepancy is the durable fix.
