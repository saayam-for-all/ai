# Test catalogue

**Generated from the suite by `tools/gen_test_catalogue.py`. Do not edit by
hand.** A catalogue maintained separately from the tests goes stale, and a
stale catalogue is worse than none, because it is believed.

This is the document to read when deciding whether a behaviour is adequately
covered. Each row names the behaviour a test protects, not merely what it
calls.

## Test kinds

| Kind | Meaning | Trust it for |
| --- | --- | --- |
| **Unit** | One function, collaborators mocked, no I/O. | Internal logic: fallback selection, field normalisation. |
| **Contract** | The shape of what crosses a boundary - the Lambda event in, the JSON envelope out. | Whether the web client will break. **These mirror what the browser actually sees, so trust these most.** |
| **Dataset** | Assertions over shipped data files. | Data quality, independent of code. |
| **Integration** | Several modules together, still hermetic. | Wiring, and blast radius between services. |

No test in the default run touches the network: `tests/conftest.py` fails any
unmarked test that opens a URL. Anything that genuinely needs the network must
be marked `needs_network`, which is excluded from the default run and from CI.

## Files

| File | Kind | Issue | Covers | Tests |
| --- | --- | --- | --- | ---: |
| [`tests/test_classification_resilience.py`](../../tests/test_classification_resilience.py) | Unit | - | `services/classification_service.py` | 5 |
| [`tests/test_client_imports.py`](../../tests/test_client_imports.py) | Integration | #154 | `utils/client.py` | 2 |
| [`tests/test_emergency_locale.py`](../../tests/test_emergency_locale.py) | Unit | #146 | `services/emergency.py` | 6 |
| [`tests/test_response_contract.py`](../../tests/test_response_contract.py) | Contract | #146, #169, #170 | `response envelopes` | 6 |
| [`tests/test_router.py`](../../tests/test_router.py) | Integration | #171 | `lambda_function.lambda_handler` | 31 |
| [`tests/test_subject_generator.py`](../../tests/test_subject_generator.py) | Unit | - | `utils/subject_generator.py` | 13 |
| | | | **Total** | **63** |

## Every test

### `test_classification_resilience.py`

*Unit · issue - · 5 tests*

Guards the two failure modes behind "every request lands in General".

| Test | Behaviour it protects |
| --- | --- |
| `test_service_model_defaults_to_client_source_of_truth` | Service model defaults to client source of truth. |
| `test_gpt_oss_uses_low_reasoning_effort` | Gpt oss uses low reasoning effort. |
| `test_retired_model_error_does_not_crash_request` | Retired model error does not crash request. |
| `test_json_validate_failed_does_not_crash_request` | Json validate failed does not crash request. |
| `test_parsing_errors_still_handled` | Parsing errors still handled. |

### `test_client_imports.py`

*Integration · issue #154 · 2 tests*

Guard against the utils/client.py import regression that broke dev.

| Test | Behaviour it protects |
| --- | --- |
| `test_client_exports_all_required_names` | Client exports all required names. |
| `test_core_modules_import` | Core modules import. |

### `test_emergency_locale.py`

*Unit · issue #146 · 6 tests*

Tests for #146 - Emergency Contacts must never fall back to US numbers (911/988) for non-US or unknown locales. Runs against the real emergency_numbers.json. No network: exercises EmergencyServiceResolver._find_services directly.

| Test | Behaviour it protects |
| --- | --- |
| `test_india_missing_service_uses_india_default_not_us` | India missing service uses india default not us. |
| `test_india_fire_is_indian_not_911` | India fire is indian not 911. |
| `test_country_name_normalizes_to_iso` | Country name normalizes to iso. |
| `test_truly_unknown_country_is_unavailable_not_us` | Truly unknown country is unavailable not us. |
| `test_india_full_set_has_no_us_numbers` | India full set has no us numbers. |
| `test_us_still_works` | Us still works. |

### `test_response_contract.py`

*Contract · issue #146, #169, #170 · 6 tests*

Pin the response contract the deployed web client depends on.

| Test | Behaviour it protects |
| --- | --- |
| `test_response_body_stays_an_object` | Response body stays an object. |
| `test_predict_returns_ranked_objects_under_categories` | Predict returns ranked objects under categories. |
| `test_subject_is_readable_at_body_subject` | Subject is readable at body subject. |
| `test_emergency_uses_the_proxy_contract_instead` | Emergency Contacts is the one endpoint on PROXY integration. |
| `test_emergency_returns_indian_numbers_not_us_ones` | Emergency returns indian numbers not us ones. |
| `test_error_bodies_are_objects_too` | Error bodies are objects too. |

### `test_router.py`

*Integration · issue #171 · 31 tests*

Router-level regression tests - issue #171.

| Test | Behaviour it protects |
| --- | --- |
| `test_service_in_body_reaches_its_handler` | Service in body reaches its handler. |
| `test_service_in_query_string_reaches_its_handler` | Service in query string reaches its handler. |
| `test_service_name_is_case_and_whitespace_insensitive` | Service name is case and whitespace insensitive. |
| `test_query_string_wins_over_body` | An explicit query parameter is the more specific instruction. |
| `test_absent_service_defaults_to_predict_category` | Back-compat: the original single-service deployment had no `service`. |
| `test_unknown_service_returns_the_documented_shape` | Unknown service returns the documented shape. |
| `test_a_body_that_is_not_an_object_never_500s` | A malformed body is a client error, not a server error. |
| `test_malformed_body_is_reported_as_400` | Malformed body is reported as 400. |
| `test_malformed_body_still_routes_when_the_query_string_named_the_service` | The body is not the router's problem once the service is known. |
| `test_an_empty_event_does_not_crash` | An empty event does not crash. |
| `test_non_proxy_services_keep_an_object_body` | The mirror image: these clients read response.body.<field>. |
| `test_a_handler_raising_does_not_leak_internals` | An unexpected error must not put a stack trace or a key in the body. |
| `test_every_advertised_service_has_a_handler` | The router's error message lists the services it supports. |

> 13 test functions expand to 31 cases through parametrisation.

### `test_subject_generator.py`

*Unit · issue - · 13 tests*

Unit tests for the Generate Subject service.

| Test | Behaviour it protects |
| --- | --- |
| `test_clean_subject_strips_leading_label` | Clean subject strips leading label. |
| `test_clean_subject_strips_surrounding_quotes` | Clean subject strips surrounding quotes. |
| `test_clean_subject_strips_label_and_quotes_together` | Clean subject strips label and quotes together. |
| `test_clean_subject_empty_falls_back` | Clean subject empty falls back. |
| `test_truncate_enforces_max_length` | Truncate enforces max length. |
| `test_generate_cleans_label_and_quotes` | Generate cleans label and quotes. |
| `test_generate_enforces_max_length` | Generate enforces max length. |
| `test_generate_empty_description_returns_fallback` | Generate empty description returns fallback. |
| `test_generate_falls_back_to_description_when_no_llm` | Generate falls back to description when no llm. |
| `test_prompt_keeps_concern_framing_rule` | Prompt keeps concern framing rule. |
| `test_prompt_keeps_no_status_word_rule` | Prompt keeps no status word rule. |
| `test_prompt_forbids_subject_label_in_output` | Prompt forbids subject label in output. |
| `test_prompt_includes_the_description` | Prompt includes the description. |
