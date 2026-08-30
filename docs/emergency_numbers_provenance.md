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

## Known gaps

These are real and are **not** closed by this change. The general-emergency
fallback means users are given a working in-country number rather than nothing,
and never a foreign one, but a dedicated line is better than a general one.

- **`suicide_helpline` is absent for 71 of 73 countries.** Only India and the
  United States have one. Everywhere else the mental-health row now resolves to
  that country's general emergency line, flagged `is_fallback: true`. Closing
  this properly means researching each country's national line with a citation
  and having a person verify it, per the rules above.
- **`disaster_management` and `women_helpline` exist only for India.** Same
  treatment and same remedy.
- **No drift detection.** Emergency numbers change rarely but they do change,
  and nothing here re-verifies the directory against its sources. A scheduled
  job that re-checks and opens an issue on a discrepancy is the durable fix.
