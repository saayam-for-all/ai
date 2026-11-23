# Emergency Contacts: tool contract for plain-language questions

Decision record and requirement for
[#243](https://github.com/saayam-for-all/ai/issues/243). Nothing here is
implemented, and nothing here changes the dataset or the resolver.

## Decision: not yet

Free text earns its place only when something sends us a sentence. The two
candidate entry points, as of 22 Nov 2026:

| Entry point | Status |
| --- | --- |
| LLM-assisted search bar, [#83](https://github.com/saayam-for-all/ai/issues/83) | On hold until after the MVP. The MVP search is deterministic and uses no AI on the main path, so it sends no sentences. |
| Voice input, [#22](https://github.com/saayam-for-all/ai/issues/22) | Open, with no assignee, no milestone and no recent activity. |

Neither has a timeline, so nothing is built now.

**Reopen when** the LLM phase of #83 or #22 has an owner and a date. This
contract is then the starting point, and it is re-checked against the dataset as
it stands at that time.

## How it works

```
"my neighbour has collapsed, I'm in Bangalore"
  -> model extracts country=IN, state=Karnataka, city=Bengaluru, service=ambulance
  -> the resolver looks it up in services/emergency_numbers.json
  -> 108
```

The model interprets the sentence. The dataset supplies the number. The model
never emits a number, and no prompt instruction is relied on for that: a number
is not part of the model's output contract. This is consistent with
[`emergency_numbers_provenance.md`](emergency_numbers_provenance.md), where no
number reaches a user because a model produced it.

## Tool contract

### What the model supplies

Two tools. Both are closed with `additionalProperties: false`.

**`lookup_emergency_number`**: four optional fields.

| Field | Type | Meaning |
| --- | --- | --- |
| `country` | string | The country as the person said it ("India", "IN"). |
| `state` | string | The state or region as said. |
| `city` | string | The city as said ("Bangalore"). |
| `service` | enum | One of the 13 values below. Omitted when no service was asked for. |

**`unsupported_request`**: no arguments. The model calls it when the person asks
for something outside the 13 services, for example poison control. An omitted
`service` therefore always means "no service asked for", never "a service we
could not map".

`service` is exactly `KNOWN_SERVICES` in `services/emergency.py`:
`general_emergency`, `police`, `ambulance`, `fire`, `disaster_management`,
`women_helpline`, `suicide_helpline`, `child_helpline`, `coastguard`,
`traffic_police`, `gendarmerie`, `gas_leak`, `general_emergency_alternate`.
Each value carries a fixed description in the schema, reviewed against the
dataset.

The contract is derived from the dataset and the resolver, not from the earlier
prototypes (`mcp_poc/` and the onboarding example on the `NewJoineeTask`
branch). The prototypes read only the `default` block and expose four services,
so they reach neither state or city records nor the women, suicide and child
helplines.

### What the model never supplies

- A dial number, in any field.
- A service or organisation name, or an address.
- A zip code. Zip is not in the schema.
- Any argument not listed above. An unknown argument such as `number` is
  rejected by the schema.
- Any argument containing a digit (proposed). None of the four fields needs one,
  and a digit string is the easiest way for a number to reach the lookup.

### From fields to an answer

The extracted fields go to the resolver's `find_services(location,
requested_service)`, where `location` is a dict with `country`, `state`, `city`
and `zip`. It returns `({service: {number, source, level}}, match_level)`, or `(None, None)`
when nothing resolves. The tool does not use
`get_emergency_services` for this: with an explicit country and a city or state
it first runs a Nominatim place search and a reverse lookup, each with a 4 s
timeout, and the finer fields survive only when Nominatim or the directory's own
city-to-state inference supplies them under the same country.

The reply is rendered from the resolver output by a template, after the
resolver's localisation step (`LocalizationService.localize_services`) has added
`dial_number`, `display_number` and `is_fallback`. The template shows those
fields, the `match_level`, and the fallback label. The model does not word a
reply around them, so it cannot attach a number to the wrong service or present
a country-level number as city-specific.

### Location precedence

A country the model inferred from a sentence is used only when the caller
supplied no structured location. The caller's own location always wins, because
an explicit country overrides GPS and IP in the resolver and drops the finer
fields.

### Aliases

State and city are matched by exact title case, and the country aliases cover
only a few names (US, IN, GB, AE). The tool therefore needs a fixed alias table
for state and city, built from the dataset's own keys, mapping what people say
("Bangalore") to the canonical key ("Bengaluru"). A city is looked up only
inside a matched state, so the table maps a city to its state as well.

Today the dataset has one state, Karnataka, with the cities Bengaluru and
Mysuru, and India is the only country with a `states` block. The table is small
now and is reviewed whenever sub-national records are added.

## Refusal path

There are three distinct outcomes, and the tool path keeps each exactly as the
resolver defines it (#146):

| Situation | Outcome |
| --- | --- |
| No country can be determined; the country is not in the dataset or has no dialable number; the request is outside the 13 services (`unsupported_request`); the model fails, times out, or sends arguments the schema rejects | **Unavailable.** |
| A state or city that does not resolve, in a country we hold | The broader level of the **same country**: the state, or the country default. The response reports `match_level`. |
| A known service that has no entry for the country | That country's own general emergency line, flagged `general_emergency_fallback`. |

Never another country's number, and never a number that did not come from the
dataset.

Making this structural means:

1. The model's output type has no field that can carry a number.
2. The reply is built only from the resolver's result. "Unavailable" is the
   default when the resolver returns nothing.
3. There is no model-supplied fallback and no nearest-match logic anywhere in
   the tool path.

### Tests required before this is built

- **No number from the model.** A mocked model returns a number-shaped value in
  each argument, plus free text containing a number. Every number in the
  response is a value from `emergency_numbers.json` for the resolved location.
- **Extra argument rejected.** A call with an extra argument such as `number`
  is rejected by the schema.
- **Unsupported request.** "Poison control" leads the model to call
  `unsupported_request`, and the response is "unavailable".
- **Unresolved city or state.** An unknown city in India resolves to the broader
  level of India, reports that `match_level`, and never returns another
  country's number.
- **No country.** When neither the caller nor the model gives a country, the
  response is "unavailable".
- **Missing service.** A known service with no entry for the country returns the
  country's general line with the fallback label.
- **Model failure.** A model error or timeout returns "unavailable".
- **All 13 services.** Every value in `KNOWN_SERVICES` can be requested.

## Placement and latency

### Where the model call sits

Extraction runs in front of the existing path, and the structured path stays
model-free. That follows provenance rule 3: a model that only extracts
arguments never produces a number, and keeping it out of the resolver preserves
the rule's requirement that resolution be deterministic and instant.

### Live figures (22 Nov 2026: configuration and the last 7 days)

| Service | Timeout | Median | p95 | Max |
| --- | --- | --- | --- | --- |
| Emergency Contacts | 10 s | 1 ms | 0.7 s | 1.6 s |
| Predict Category | 10 s | 0.5 s | 1.3 s | 2.0 s |
| Generate Subject | 30 s | 0.4 s | 1.6 s | 1.8 s |
| Generate Answer | 120 s | 21 s | 112 s | 120 s |
| More Organizations | 30 s | 1.6 s | 2.0 s | 2.5 s |

These are whole-service figures. They show the order of magnitude, roughly
0.4-2 s for a model-backed service against about a millisecond at the median for
the structured lookup on a warm container. A cold start first loads the
directory from S3 (1 s connect and read timeouts). The figures are not a
measurement of one extraction call.

### Recommendation: its own function

Timeout and IAM role are set per function, so a new handler inside the existing
function could isolate neither. An own function gets its own timeout, its own
limit on model calls, and is the only function that holds the model keys. The
five services share one deployment package, so this is a deployment
configuration addition, not a new package.

This depends on:

- [#253](https://github.com/saayam-for-all/ai/pull/253) (#237 Part A) and
  [#223](https://github.com/saayam-for-all/ai/pull/223) landing. They defer the
  SSM key fetch and the provider SDK imports (Groq, Gemini and their LangChain
  wrappers) out of the Emergency Contacts cold start, which keeps the structured
  path free of model calls in practice.
- A model timeout that keeps the request under API Gateway's 29 s
  ([#263](https://github.com/saayam-for-all/ai/issues/263)).

Once the extraction function exists and Emergency Contacts no longer reads model
keys, narrowing the Emergency Contacts IAM role becomes possible. That is a
follow-up and is not part of this change.

## Out of scope

- Building an MCP server. Whether the contract is later exposed over a protocol
  is a separate question that the MCP evaluation spike answered conditionally.
- Any change to the dataset or the resolver.
- Generating a number under any circumstance, including as a fallback when the
  lookup misses.
- Reusing either existing prototype as-is.