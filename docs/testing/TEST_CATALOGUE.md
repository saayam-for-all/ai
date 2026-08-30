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
| [`tests/test_emergency_dataset.py`](../../tests/test_emergency_dataset.py) | - | #146 | `services/emergency_numbers.json` | 15 |
| [`tests/test_emergency_locale.py`](../../tests/test_emergency_locale.py) | Unit | #146 | `services/emergency.py` | 59 |
| [`tests/test_response_contract.py`](../../tests/test_response_contract.py) | Contract | #146, #169, #170 | `response envelopes` | 10 |
| [`tests/test_router.py`](../../tests/test_router.py) | Integration | #171 | `lambda_function.lambda_handler` | 31 |
| [`tests/test_subject_generator.py`](../../tests/test_subject_generator.py) | Unit | - | `utils/subject_generator.py` | 13 |
| | | | **Total** | **135** |

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

### `test_emergency_dataset.py`

*- · issue #146 · 15 tests*

Integrity checks on services/emergency_numbers.json.

| Test | Behaviour it protects |
| --- | --- |
| `test_the_file_is_not_empty` | The file is not empty. |
| `test_country_keys_are_iso_alpha2` | Country keys are iso alpha2. |
| `test_every_number_is_dialable` | No blanks, no prose, no truncated values. |
| `test_no_us_only_number_appears_outside_the_us` | The core safety invariant of issue #146, asserted against the data. |
| `test_every_country_can_answer_a_general_emergency` | Every country must have something for the fallback to reach for. |
| `test_service_names_are_from_the_known_vocabulary` | An unmodelled service name is silently invisible to the client. |
| `test_specific_corrected_values` | Specific corrected values. |

> 7 test functions expand to 15 cases through parametrisation.

### `test_emergency_locale.py`

*Unit · issue #146 · 59 tests*

Behaviour tests for issue #146 - Emergency Contacts must never show a user a number from another country, and must never leave a field empty for the web client to fill with a hardcoded US default (911 / 988).

| Test | Behaviour it protects |
| --- | --- |
| `test_india_fire_is_indian_not_911` | Reported symptom 1: the India Fire row showed US 911. |
| `test_india_mental_health_is_indian_not_988` | Reported symptom 2: the India Mental Health row showed US 988. |
| `test_india_returns_the_routes_the_ticket_asks_for` | India returns the routes the ticket asks for. |
| `test_india_full_directory_has_no_us_numbers` | India full directory has no us numbers. |
| `test_no_response_ever_contains_a_foreign_number` | Every number returned for a country appears in that country's own record. |
| `test_every_country_answers_every_modelled_service` | No modelled service comes back empty for a country we know. |
| `test_no_non_us_country_ever_shows_988` | 988 is the one number in the dataset that is unambiguously US-only. |
| `test_missing_service_falls_back_to_the_countrys_own_general_line` | Missing service falls back to the countrys own general line. |
| `test_a_fallback_is_labelled_as_one` | A general emergency line must not be passed off as the real service. |
| `test_a_real_entry_is_never_overwritten_by_the_fallback` | A real entry is never overwritten by the fallback. |
| `test_unmodelled_service_is_unavailable_not_the_general_line` | Asking for something we do not model must not be answered with 112. |
| `test_no_service_filter_returns_the_whole_directory` | An absent or blank service parameter means "give me everything". |
| `test_city_entry_inherits_the_services_it_does_not_list` | Bengaluru lists only police and ambulance. |
| `test_single_service_reports_the_level_it_actually_came_from` | Bengaluru matches at city level but does not list a fire number. |
| `test_more_specific_levels_override_broader_ones` | More specific levels override broader ones. |
| `test_country_with_no_dialable_number_at_all_is_unavailable` | We report nothing rather than invent a fallback out of nothing. |
| `test_country_name_normalizes_to_iso` | Country name normalizes to iso. |
| `test_truly_unknown_country_is_unavailable_not_us` | A country we do not have is answered "unavailable", never with US numbers. |
| `test_us_still_works` | Us still works. |
| `test_a_foreign_state_name_does_not_leak_into_another_country` | "Karnataka" under "US" must not match anything US-side. |
| `test_explicit_country_discards_a_contradicting_geocode` | Explicit country discards a contradicting geocode. |
| `test_agreeing_country_override_keeps_the_finer_detail` | Agreeing country override keeps the finer detail. |
| `test_ambiguous_bare_city_is_not_guessed` | A city name in two countries must not pick one of them. |
| `test_is_dialable` | Is dialable. |
| `test_a_non_ip_is_never_put_into_the_lookup_url` | The IP comes from a request header, so it is validated before use. |
| `test_out_of_range_coordinates_are_rejected_before_any_request` | Out of range coordinates are rejected before any request. |
| `test_display_number_is_localized_but_dial_number_stays_ascii` | Display number is localized but dial number stays ascii. |
| `test_unknown_language_falls_back_to_the_ascii_digits` | Unknown language falls back to the ascii digits. |
| `test_end_to_end_india_response` | End to end india response. |
| `test_end_to_end_unknown_country_is_404_not_us_numbers` | End to end unknown country is 404 not us numbers. |
| `test_end_to_end_with_nothing_to_go_on_is_404` | No parameters and no client IP: we say we do not know. |
| `test_missing_language_defaults_to_english` | Missing language defaults to english. |

> 32 test functions expand to 59 cases through parametrisation.

### `test_response_contract.py`

*Contract · issue #146, #169, #170 · 10 tests*

Pin the response contract the deployed web client depends on.

| Test | Behaviour it protects |
| --- | --- |
| `test_response_body_stays_an_object` | Response body stays an object. |
| `test_predict_returns_ranked_objects_under_categories` | Predict returns ranked objects under categories. |
| `test_subject_is_readable_at_body_subject` | Subject is readable at body subject. |
| `test_emergency_uses_the_proxy_contract_instead` | Emergency Contacts is the one endpoint on PROXY integration. |
| `test_emergency_returns_indian_numbers_not_us_ones` | Emergency returns indian numbers not us ones. |
| `test_emergency_error_bodies_use_the_proxy_shape_too` | A proxy method rejects an object body, and the caller sees a bare 502. |
| `test_emergency_errors_through_the_router_use_the_proxy_shape` | Emergency errors through the router use the proxy shape. |
| `test_a_malformed_body_does_not_break_an_emergency_lookup` | The query string alone is enough; a stray body must not cause a 500. |
| `test_error_bodies_are_objects_too` | Error bodies are objects too. |
| `test_router_error_path_keeps_the_proxy_envelope` | The router can fail before the handler is ever reached. |

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
