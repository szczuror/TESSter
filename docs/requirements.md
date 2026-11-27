# Requirements

Requirements say what TESSter must do and within what limits. Each one comes from the [vision](vision.md) and describes one behavior that can be checked, without saying how the system is built.

## Notation

- **FR** (functional requirement) - what the system does.
- **NFR** (non-functional requirement) - a quality the system must have or a limit it must stay within.
- **Priority** - **Must**: without it the problem stays unsolved. **Should**: important, but the system is useful without it. **Could**: only if time allows.

## Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | When the user gives a candidate's TOI (TESS Object of Interest) number, e.g. `TOI-1234.01`, the system checks it and produces a report. | Must |
| FR-02 | If the system cannot find the candidate or some of its data, it tells the user what is missing. | Must |
| FR-03 | The system shows the candidate's current catalog status (e.g. planet candidate, confirmed planet, false positive) with its source and date. | Must |
| FR-04 | The system lists scientific papers that mention the candidate, each with title and year. | Must |
| FR-05 | For each listed paper, the system states whether it confirms the candidate, rules it out, or only mentions it. | Should |
| FR-06 | The system checks whether the dip could be caused by two stars eclipsing each other. | Must |
| FR-07 | If another star within 2.5 arcminutes of the candidate is bright enough that eclipsing it completely would produce the dip, the system first checks which star the dip comes from. | Must |
| FR-08 | The report says why each test was run or skipped. | Must |
| FR-09 | Each test that was run ends as *passed* (fits a planet), *failed* (points to a false positive) or *unclear*, and the report shows which. | Must |
| FR-10 | The report gives exactly one verdict (*likely planet*, *false positive* or *inconclusive*) with its main reason in one sentence. | Must |
| FR-11 | The agent gives the verdict from the test results, within the limits of FR-17. A fixed rule also gives a reference verdict: *false positive* if any test failed, *likely planet* if every needed test passed, and *inconclusive* otherwise. The report shows the reference verdict when the two differ, and uses it when the agent gives no valid verdict. | Must |
| FR-12 | For a *false positive* verdict, the report names the likely cause, e.g. two eclipsing stars or a nearby star. | Should |
| FR-13 | For an *inconclusive* verdict, the report names the observation or data that would settle it. | Should |
| FR-14 | Every fact in the report that comes from an outside source links to it. | Must |
| FR-15 | The system answers follow-up questions about a report, e.g. what a test means or why it was skipped. | Should |
| FR-16 | When several candidates are checked at once, the system lists each one's verdict and main reason, *likely planet* candidates first. | Could |
| FR-17 | The agent gives its verdict only after every needed test has a result. The verdict rests only on test results in the report, never on the catalog status or papers. It may overrule a weak failure of a test, with the reason in the report, but not a strong one, and a *false positive* names at least one failed test. | Must |
| FR-18 | When test results are unclear or contradict each other, the agent may run further tests that could settle them, and says why (FR-08). | Should |

## Non-functional requirements

| ID | Requirement | Priority |
|---|---|---|
| NFR-01 | On a test set of at least 50 resolved candidates (half confirmed planets, half false positives), with their catalog status, names and papers hidden, at least 70% of the planets get *likely planet* and at least 70% of the false positives get *false positive*. The score is also given separately for candidates the model cannot remember: synthetic ones, or ones resolved after its training data. | Must |
| NFR-02 | Across at least 20 sample reports, every cited paper exists and mentions the candidate. | Must |
| NFR-03 | Checking any test-set candidate 10 times on unchanged data gives the same verdict at least 9 times. | Should |
| NFR-04 | A check of one candidate finishes within 10 minutes for at least 90% of the test set. | Should |
| NFR-05 | After reading a report, at least 4 of 5 non-expert students can state its verdict and main reason. | Should |

## Assumptions

- Users know what a transiting planet is, but not how false positives are ruled out.
- Every candidate already has a TOI number, with the timing and depth of its dips in the catalog. The system does not look for new candidates.
- All data the system needs are public and free online: catalogs, TESS light curves and star catalogs. For papers, an arXiv version or at least the abstract is available.
- The system only works with existing data. It does not plan or request new observations.
- A verdict is advice. It does not change the candidate's official status, and the system never *confirms* a planet. A *likely planet* verdict can support a request for follow-up observations.

## Open questions

- Should the user also be able to enter a star's TIC number, or a TOI without its suffix (e.g. `TOI-1234`) to check all candidates of that star?
- If catalogs or papers already confirm or rule out a candidate, should the system still run its own tests?
- Which papers count: only peer-reviewed ones, or arXiv preprints too? Should "recent" mean a time limit?
- Which mistake is worse for our users: calling a real planet a false positive, or the reverse?
- Should the test set include false positives found only by later observations, which TESS data alone cannot reveal?
- Beyond the verdict, should the system say whether a small telescope can catch the dip (its depth, the star's brightness, when the next dip is due)?
- Can the user come back to a report from an earlier session and ask follow-up questions about it?
- Where does a weak failure end and a strong one begin, for each test (FR-17)?
- Should the verdict come from one run of the agent, or from the majority of several runs (NFR-03, NFR-04)?
