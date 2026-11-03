# TESS VERIFIER 

AI agent designed to help verify the existence of exoplanets using data from TESS.

## Authors

- Igor Kowalik
- Wiktor Szymonek
- Aleksander Sergiej

## What it does

Given a candidate's TOI number, the agent looks the candidate up in the catalogs, lists papers that mention it, checks for nearby stars bright enough to cause the dip, and runs tests for false positives (centroid, odd-even depth, secondary eclipse, companion size). The report gives one verdict (*likely planet*, *false positive* or *inconclusive*) with its main reason, why each test was run or skipped, and a link for every outside fact. See [vision](docs/vision.md), [requirements](docs/requirements.md) and [use cases](docs/use-cases.md).

An LLM runs the check through tool calls, but code computes the verdict from the test results (FR-11), so the same results always give the same verdict.

> **Version 0.1 uses placeholder data.** The catalogs, papers, star catalog and light-curve measurements come from made-up fixtures (`TOI-90001.01` to `TOI-90005.01`). Real archives come next.

## Setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Install the dependencies:

   ```bash
   uv sync
   ```

3. Copy `.env.example` to `.env` and put your key of the [PSNC LLM service](https://llm.hpc.psnc.pl/) in `VLLM_API_KEY`. The default model is `vllm:gpt-oss_120b`, which PSNC serves through an OpenAI-compatible API; `.env.example` already sets its address:

   ```bash
   TESS_VERIFIER_MODEL=vllm:gpt-oss_120b
   VLLM_BASE_URL=https://llm.hpc.psnc.pl/v1
   VLLM_API_KEY=<your key>
   ```

   To use another model, change `TESS_VERIFIER_MODEL` and put in the key of its provider, e.g. `anthropic:claude-haiku-5-5` with `ANTHROPIC_API_KEY`, `openai:<model>` with `OPENAI_API_KEY` or `google:<model>` with `GOOGLE_API_KEY`. Other PSNC models keep the `vllm:` prefix, with the name exactly as PSNC lists it.

`.env` is ignored by git. Never commit API keys.

## Usage

```bash
uv run tess-verifier samples                               # list the placeholder candidates
uv run tess-verifier check TOI-90003.01                    # check one candidate with the LLM agent
uv run tess-verifier check TOI-90003.01 --verbose          # also show every tool call and the token usage
uv run tess-verifier check TOI-90003.01 --chat             # ask follow-up questions about the report
uv run tess-verifier check TOI-90001.01 TOI-90002.01 TOI-90004.01   # several candidates, likely planets first
uv run tess-verifier check TOI-90004.01 --offline          # standard procedure without an LLM (no key needed)
uv run tess-verifier check TOI-90005.01 --blind            # hide catalog status, names and papers (evaluation)
uv run tess-verifier check TOI-90001.01 --out reports      # also save the report as Markdown
```

## Development

```bash
uv run pytest            # tests run without network or API keys
uv run ruff check        # lint
uv run ruff format       # format
```

CI runs the same checks on every pull request.

## Project structure

```
src/tess_verifier/
  cli.py            command line (Typer)
  config.py         settings from environment variables / .env
  models.py         domain model: TOI numbers, sources, checks, verdicts, reports
  pipeline.py       one check from TOI number to report, several checks at once
  investigation.py  state of a check and the steps shared by the agent and the standard procedure
  report.py         Markdown reports
  agent/            LLM agents (Pydantic AI): instructions, the verifier with its tools, follow-up questions
  vetting/          verification tests and the verdict rule, plain code without an LLM
  sources/          interfaces to outside archives; placeholder implementation with fixtures
tests/              unit tests, end-to-end tests offline, agent tests with a scripted fake model
```

Planned next: real archives in `sources/` (NASA Exoplanet Archive, ExoFOP, NASA ADS, arXiv, MAST) with light-curve analysis, an MCP server exposing the data sources, RAG over papers and vetting knowledge, and an evaluation suite (`evals/`) for NFR-01 to NFR-04.
