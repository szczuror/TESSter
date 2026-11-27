# The Agent's Role

TESSter is meant to be an AI agent ([vision](vision.md)), but in v0.1 the LLM plays a small part. It classifies papers, writes the sentences of the report and answers follow-up questions. Code picks the tests and computes the verdict with a fixed rule, so `--offline` gives almost the same report. This document proposes a larger role: the agent **investigates**, **judges** and **explains**, and code keeps the limits that make the result trustworthy. The [requirements](requirements.md) (FR-11, FR-17, FR-18), the [domain model](domain-model.md) (D1), the [state diagram](state-diagram.md) and the [activity diagram](activity-diagram.md) follow it.

## Why

The fixed rule cannot weigh evidence: any failed test means *false positive*. The real planet WASP-121 b (TOI-495.01) fails the companion-size test with 22.7 Earth radii, just above the limit of 22.4 and well within the measurement errors. Very hot planets glow, so their own secondary eclipse can fail the secondary-eclipse test. Every test we add rejects more real planets.

## 1. Investigator

- Code enforces only the minimum: the required tests (FR-06), the centroid test first when needed (FR-07), and the safety net for required steps the agent left out.
- Beyond that, the agent chooses what to look at next from what it has found so far. When results are unclear or contradict each other, it runs further tests that could settle them (FR-18).
- Tests to add, each one *supporting* at first:

| Test | What it shows |
|---|---|
| Stellar density | The star's density from the transit shape disagrees with the catalog: the dip may come from another star. |
| Transit shape | A V-shaped dip, rather than a flat-bottomed U, points to two stars grazing each other. |
| Other candidates of the star | A candidate whose star has other candidates is rarely a false positive. |
| Gaia RUWE | A high value means the star is probably an unresolved pair. |
| Depth per sector | A depth that changes between sectors points to light from another star. |
| Follow-up notes (ExoFOP) | What follow-up observations of the candidate found. Not in a blind test. |

## 2. Judge

- The agent gives the verdict with a new tool, `give_verdict`, which replaces `get_verdict`. It sends the verdict, its confidence (*low*, *medium* or *high*), the test results it rests on, the failed tests it overrules with the reason, and the main reason.
- It weighs every result, supporting tests included. The fixed rule ignores supporting tests; the agent does not.
- It may overrule a **weak** failure, such as WASP-121 b above, and the report says why. It may not overrule a **strong** one, such as odd and even dips that differ by 10 sigma. Each test says where a weak failure ends and a strong one begins.
- Code checks the verdict when it is given (FR-17). A verdict that breaks a limit gets a correction, so the model can fix it.

## 3. Narrator

- The agent writes the main reason (FR-10), why each test was run or skipped (FR-08) and why it overruled a failure, from its own reasoning instead of templates.
- It answers follow-up questions about the report (FR-15), as today.

## What code keeps

- **Limits** on the agent's verdict (FR-17):
  - it comes only after every required test has a result;
  - it rests only on test results in the report, never on the catalog status or papers, which are shown as disagreements (UC-01 2b);
  - it does not contradict a strong failure;
  - a *false positive* names at least one failed test.
- **The reference verdict:** the fixed rule still gives its verdict (FR-11). The report shows it when it differs from the agent's.
- **The fallback:** without a valid verdict from the agent (offline, after a model error, or when a test was added after the verdict), the report uses the reference verdict.

## Changes to the requirements

| ID | Change |
|---|---|
| FR-11 | The agent gives the verdict within the limits of FR-17. The fixed rule gives a reference verdict, shown when the two differ. |
| FR-17 | New: the limits on the agent's verdict. |
| FR-18 | New: the agent may run further tests when results are unclear or contradict each other. |
| NFR-01 | The score is also given for candidates the model cannot remember. |
| NFR-03 | Unchanged, but harder to meet (see below). |

## Risks and open questions

- **Memory.** A blind test hides names, but the period, depth and brightness of a famous object (WASP-121 b: 1.27 days, about 1.5%) may still let the model recognize it. We would then measure the model's memory, not the method. So NFR-01 is also scored on synthetic candidates and on candidates resolved after the model's training data.
- **Repeatability (NFR-03).** Temperature 0 helps. If it is not enough, the verdict can be the majority of three runs, at three times the cost.
- **Time and cost (NFR-04).** More tests and more model requests per candidate.
- **Text only.** `gpt-oss-120b` reads only text. To look at plots (TESS Data Validation reports) the way a person vetting a candidate does, the agent needs a model that takes images.
- **Weak or strong.** Where the line lies for each test is decided per test and checked on the reference candidates.
