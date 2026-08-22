# Opportunity Tracker

Single-user CLI that discovers scholarship/research-degree opportunities matching a
filter (country, degree level, field), verifies their requirements against primary
sources, and ranks them against your profile.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) if you don't have it.
2. `uv sync` — provisions Python 3.12 and installs all dependencies.
3. `cp .env.example .env` and fill in `ANTHROPIC_API_KEY`.
4. `cp profile.example.yaml profile.yaml` and fill in your details.
5. `cp filter.example.yaml filter.yaml` and set your target country/degree/field.
6. `uv run optrack init-db` — creates `opportunity_tracker.db`.
7. `uv run optrack run` — runs the full pipeline: discover, fetch, extract, evaluate, report.

See `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` for the full design.
