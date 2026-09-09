# Worked examples

Three implementations that satisfy every check in `onboarding_check.py` for
Missions 4, 5 and 6.

**Read these after you have written your own, not before.** Nothing stops you
reading them early and nobody is checking. But they are worth very little in
advance, because what makes them useful is comparing them against the decisions
you already made, and the defect hunt below is unreadable until you have tried
it yourself.

There is no answer key here to leak. The self check verifies behaviour, not
answers: a tool that refuses `poison_control`, a harness that outscores its own
control, a search whose citations resolve. Copy one of these and you have a
working implementation, which was the point of the mission.

| File | Mission |
| --- | --- |
| `agent_tools.py` | 4, tool calling |
| `evals_run.py` | 5, evaluation harness |
| `grounded_orgs.py` | 6, grounded search, elective |

---

## The defect hunt

`agent_tools.py` **passes every check and is wrong in at least three ways.**
This is deliberate and it is the last exercise in the onboarding.

Find them before reading the answers below. The hint is the same one that runs
through the whole flow: **what can a user ask for that this cannot answer?**

<details>
<summary>The three defects</summary>

**1. Three of the seven services are unreachable.** The schema's `service`
enum lists `police`, `ambulance`, `fire` and `general_emergency`.
`KNOWN_SERVICES` in `services/emergency.py` also has `disaster_management`,
`women_helpline` and `suicide_helpline`. A model constrained by this schema can
never ask for any of them, so a woman asking for a women's helpline gets told
the request is not supported. Those three are precisely the services issue
#146 was raised about.

**2. It never reads state-level data.** `lookup_emergency_number` reads only
`_DATA[country]["default"]`. India carries entries for Karnataka, Maharashtra
and Tamil Nadu, and the United States carries state entries too. Someone in
Karnataka gets India's national number rather than their state's.

**3. It refuses `"Japan"`.** The mission text warns that the model will pass a
country name where the data expects an ISO code, and this implementation
returns `None` for exactly that case. Refusing is far better than guessing, so
this is the mildest of the three, but the code declines to solve the problem
its own docstring anticipates. `services/emergency.py` has an alias map for
this; the worked example does not use it.

**Which would you fix first?** Defect 1, on the argument that a missing
women's helpline is a safety failure while a wrong-but-national number still
connects someone to help. That is a judgement, not a fact, and disagreeing with
it in your observations is a perfectly good answer.

</details>

---

## Maintainer note

**The three defects in `agent_tools.py` are intentional. Do not fix them.**
They are the material for the exercise above, and a well-meaning cleanup would
silently remove the last mission from the onboarding.

If you change the checks in `onboarding_check.py`, re-run the adversarial suite
against these files. It writes deliberately broken variants, confirms each is
rejected, then confirms these still pass. A check that stops biting is worse
than no check, because it reports success.

`evals_run.py` uses a deterministic stand-in classifier so the harness can be
exercised without a live model or an API key. A joiner's version would call the
real classifier. The contract the check enforces is `GOLDEN`, `PROMPT`,
`CONTROL_PROMPT` and `run(prompt) -> {"score": float}`.

`grounded_orgs.py` carries three hardcoded records rather than a real dataset,
for the same reason. It demonstrates the shape, not the retrieval.
