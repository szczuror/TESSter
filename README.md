# TESSter

AI agent designed to help verify the existence of exoplanets using data from TESS.

## Authors

- Igor Kowalik
- Wiktor Szymonek
- Aleksander Sergiej

## What it does

Given a candidate's TOI number, the agent looks the candidate up in the catalogs, lists papers that mention it, checks for nearby stars bright enough to cause the dip, and runs tests for false positives (centroid, odd-even depth, secondary eclipse, companion size). The report gives one verdict (*likely planet*, *false positive* or *inconclusive*) with its main reason, why each test was run or skipped, and a link for every outside fact. See [vision](docs/vision.md), [requirements](docs/requirements.md) and [use cases](docs/use-cases.md).

An LLM runs the check through tool calls, but code computes the verdict from the test results (FR-11), so the same results always give the same verdict.

> **Real archives are being connected.** The candidate comes from the TOI table of the [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/). Papers, the star catalog and light curves are not connected yet: the report lists them under *Problems and missing data*, and until they are, most verdicts are *inconclusive*. The made-up candidates `TOI-90001.01` to `TOI-90005.01` are used only by the tests.

## Setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Install the dependencies:

   ```bash
   uv sync
   ```

3. Copy `.env.example` to `.env` and put your key of the [PSNC LLM service](https://llm.hpc.psnc.pl/) in `VLLM_API_KEY`. The default model is `vllm:gpt-oss_120b`, which PSNC serves through an OpenAI-compatible API; `.env.example` already sets its address:

   ```bash
   TESSTER_MODEL=vllm:gpt-oss_120b
   VLLM_BASE_URL=https://llm.hpc.psnc.pl/v1
   VLLM_API_KEY=<your key>
   ```

   To use another model, change `TESSTER_MODEL` and put in the key of its provider, e.g. `anthropic:claude-haiku-5-5` with `ANTHROPIC_API_KEY`, `openai:<model>` with `OPENAI_API_KEY` or `google:<model>` with `GOOGLE_API_KEY`. Other PSNC models keep the `vllm:` prefix, with the name exactly as PSNC lists it.

`.env` is ignored by git. Never commit API keys.

## Usage

```bash
uv run tesster samples                               # list real candidates to try
uv run tesster check TOI-270.01                      # check one candidate with the LLM agent
uv run tesster check TOI-270.01 --verbose            # also show every tool call and the token usage
uv run tesster check TOI-270.01 --chat               # ask follow-up questions about the report
uv run tesster check TOI-270.01 TOI-236.01 TOI-1285.01   # several candidates, likely planets first
uv run tesster check TOI-236.01 --offline            # standard procedure without an LLM (no key needed)
uv run tesster check TOI-270.01 --blind              # hide catalog status, names and papers (evaluation)
uv run tesster check TOI-270.01 --out reports        # also save the report as Markdown
```

Every check reads the online archives, so it needs a network connection. `--offline` only turns the LLM off.

## Development

```bash
uv run pytest            # tests run without network or API keys
uv run ruff check        # lint
uv run ruff format       # format
```

CI runs the same checks on every pull request.

### Adding a verification test

1. Add a member and its label to `Check` in `src/tesster/models.py`.
2. Write the test in a new module in `src/tesster/vetting/checks/`, with a `SPEC` that says what it looks for, its likely cause, what would settle it and how to run it. A new test is *supporting* by default: its result never changes the verdict.
3. List the `SPEC` in `src/tesster/vetting/registry.py`. The order there is the order tests run in and failures are reported in.
4. Add unit tests in `tests/test_checks.py`.

## Project structure

```
src/tesster/
  cli.py            command line (Typer)
  config.py         settings from environment variables / .env
  models.py         domain model: TOI numbers, sources, checks, verdicts, reports
  pipeline.py       one check from TOI number to report, several checks at once
  investigation.py  state of a check and the steps shared by the agent and the standard procedure
  report.py         Markdown reports
  agent/            LLM agents (Pydantic AI): instructions, the verifier with its tools, follow-up questions
  vetting/          verification tests (one module each), their registry and the verdict rule, no LLM
  sources/          outside archives, read with astroquery: the NASA Exoplanet Archive catalog, stand-ins for the sources not connected yet, fixtures for the tests
tests/              unit tests, end-to-end tests offline, agent tests with a scripted fake model
```

Planned next: the remaining archives in `sources/` (the TIC star catalog and TESS light curves at MAST, NASA ADS and arXiv) with light-curve analysis, an MCP server exposing the data sources, RAG over papers and vetting knowledge, and an evaluation suite (`evals/`) for NFR-01 to NFR-04.

