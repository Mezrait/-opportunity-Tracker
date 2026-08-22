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
6. *(optional)* `cp seeds.example.yaml seeds.yaml` and pin any opportunities you already
   know about. A pin may carry `declared_tier: 1` to override automatic domain
   classification for a legitimate site that matches no academic suffix.
7. `uv run optrack init-db` — creates `opportunity_tracker.db`.
8. **`uv run optrack load-directory --version 2026.1`** — loads the vendored institution
   directory into the `institution` table. **Required**: discovery searches institution by
   institution, so with an empty `institution` table `discover` finds nothing at all, and
   tiering cannot recognise an institution's own domain.
9. `uv run optrack run` — runs the full pipeline: sync profile, discover, fetch, extract,
   evaluate, report.

## Measuring extraction trust

Per spec principle 6 ("trust is measured, not chosen"), a requirement kind is untrusted
until its extraction recall has actually been measured, and every FAIL on an unmeasured
kind is downgraded to UNKNOWN-GATED. Run the gold-set harness to produce those numbers:

```
uv run python scripts/eval_gold_set.py
```

It writes per-kind recall to `data/gold_set_recall.json`, which `optrack evaluate-all`
reads on every run. Until it has been run at least once, expect everything to land in
Unknown-Gated — that is the designed behaviour, not a bug.

## Other commands

- `uv run optrack review-unclassified` — triage rules that were logged but not written to a
  field: unrecognised kinds, and findings from non-Tier-1 sources (spec principle 2).
- `uv run optrack dig --award-id N --kind deadline` — bounded gap-filler for one missing
  required field on one award.
- `uv run optrack report --format csv --output report.csv` — re-render the last evaluation.

See `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` for the full design.
