"""Evaluation for the GenAI services (issue #197, stack 5).

Tests check that our code does what it was written to do. Evaluation checks
that the *model*, driven by our prompts, still gives the right answers. The two
fail independently: a one-word edit to a prompt can pass every test and still
move real requests into the wrong category.

  * `golden_set`           - load and validate the hand-labelled cases.
  * `classification_eval`  - run the classifier over them, score, gate, and
                             fingerprint everything that decides the answer.

The live run lives in `tools/run_golden_set.py`. Its committed result in
`docs/metrics/` is what the offline test suite checks against.
"""
