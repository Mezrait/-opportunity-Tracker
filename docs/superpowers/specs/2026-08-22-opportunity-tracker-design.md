# Opportunity Tracker — Design Spec

**Date:** 2026-08-22 (revision of a 2026-08-17 draft, `2026-08-17-opportunity-tracker-design.md`)
**Status:** Approved for implementation planning
**Scope:** Sub-project 1 — Core + Eligibility + Filter-Driven Discovery. Supersedes the
original draft's non-goal on automated discovery — see §2 and §12 for what changed and why.

---

## 1. Purpose

A single-user command-line tool that, given an operator-editable filter (country, degree
level, field of study, and optional preferences), discovers every matching institution's
scholarship/research-degree opportunities, extracts their requirements as structured data
with provenance, evaluates them against the operator's profile, and produces a ranked
report.

The problem it solves is twofold:

1. **Discovery at scale.** Checking one known institution takes one web search. Checking
   *every* institution in a country against a filter does not — that's the gap between
   "I heard about UWA's RTP scholarship" and "show me everything in Canada offering a
   funded CS PhD." A human cannot do this exhaustively by hand.
2. **Data integrity, still primary.** The failure this tool exists to prevent is acting on
   plausible-looking but wrong requirement data, and missing binding requirements that live
   on secondary pages. Discovery only finds candidates; it does not relax how rigorously
   each one is verified.

Motivating case: UWA's international RTP scholarship looked like a strong match on every
page a keyword search surfaces. The disqualifying rule — a research project worth at least
25% of an annual full-time enrolment — lives on the PhD course rules page, not the
scholarship page. A separate AI summary of the same opportunity produced a fabricated
stipend figure, an invented acceptance rate, and email addresses on a non-existent domain.

## 2. Non-goals

Explicitly out of scope. Each is a deliberate decision, not an oversight.

- **General open-web crawling.** Discovery is bounded to institutions in the vendored
  directory (§4.1 `institution`) plus domain-scoped search (§6.0) — it does not explore
  arbitrary unknown institutions or follow the open web outside a known institution's
  domain. *(Revises the original draft's blanket non-goal on "automated discovery," which
  assumed 20–40 hand-picked targets; the operator instead wants exhaustive country-wide
  coverage against a filter — see §12.)*
- **Multi-user support, auth, hosting, web UI.** Single operator, local execution.
- **Weighted composite scoring.** Rejected: with limited records and no outcome data,
  weights cannot be calibrated and produce false precision. Revisit only after two
  completed application cycles produce real outcomes.
- **Monitoring, change alerts, cycle recurrence.** Sub-project 2. The data model here must
  not preclude it (see §4.4).
- **Application drafting, supervisor outreach, document generation.**

## 3. Governing principles

These are load-bearing. Implementation choices that conflict with them are wrong even if
they pass tests.

1. **Rank, never silently eliminate.** No record is ever hidden or deleted. Every award
   appears in the report with its bucket and reasons. The operator may choose not to read
   the bottom of the list; the tool never makes that choice for them.
2. **Only Tier 1 sources write to fields.** A field with no Tier 1 source remains `NULL`.
   Never averaged, never inferred, never filled from a lower-tier source.
3. **Three-valued logic throughout.** Pass / fail / unknown. `unknown` never collapses to
   either, at any layer.
4. **Every error degrades toward UNKNOWN-GATED.** Never toward ELIGIBLE, never toward
   deletion. Failures must not manufacture optimism or shrink options.
5. **Absence of a requirement is not evidence it does not exist.**
6. **Trust is measured, not chosen.** A requirement kind earns the authority to produce a
   blocking verdict by clearing a recall threshold on the gold set.
7. **Discovery misses are logged, not silent.** *(New.)* An institution considered by a
   discovery run for which no candidate page was found is recorded as `NO_CANDIDATE_FOUND`,
   not simply absent — the same "rank, never silently eliminate" spirit applied to
   institutions, not just awards.

## 4. Data model

SQLite, single file. Relational because provenance queries require joins; flat files make
append-only history painful.

### 4.1 Entities

```
scheme      id, name, funder, jurisdiction

award       id, scheme_id, institution, country, degree_levels,
            intake_year, canonical_url

document    id, url, source_tier, fetch_method, content_hash,
            text_path, retrieved_at, fetch_status, degraded

requirement id, award_id, document_id, kind, operator, value, unit,
            raw_text, evidence, confidence, extracted_at, human_verified

profile     id, version, created_at, attributes (json)

evaluation  id, award_id, profile_version, evaluated_at, bucket,
            sort_keys (json), per_requirement_outcomes (json)

unclassified_rule
            id, document_id, raw_text, logged_at, reviewed

institution id, name, country, country_code, domain, source
            ('hipo_directory' | 'manual'), directory_version, added_at

filter      id, name, country, degree_levels (json), fields (json),
            funding_type, deadline_after, min_grade, institution_cap,
            created_at

discovery_run
            id, filter_id, filter_content_hash, started_at, completed_at,
            institutions_considered, institutions_with_candidates,
            searches_used, status

candidate   id, discovery_run_id (nullable — null for manual pins),
            institution_id, url, query_used, found_at,
            promoted_to_award_id (nullable)
```

`requirement.kind` is a **closed enum**:

```
min_grade | research_project_fraction | thesis_required | english_test
nationality | deadline | degree_level | supervisor_required
prior_scholarship_exclusion | return_obligation | funding_component
intake_year
```

`document.fetch_method`: `http | headless | pdf`

### 4.1.1 Required vs informational kinds

A kind is **required** if an unknown or failing value must gate the bucket. Referenced
throughout as "required requirements":

**Required:** `deadline`, `degree_level`, `intake_year`, `thesis_required`,
`research_project_fraction`, `min_grade`, `english_test`, `nationality`

**Informational** (recorded, shown in the report, never gates a bucket):
`supervisor_required`, `prior_scholarship_exclusion`, `return_obligation`,
`funding_component`

`supervisor_required` is informational rather than gating because it is a task to complete,
not a property the operator either has or lacks — it feeds `feasibility` (§6.5) instead.
`return_obligation` and `funding_component` are preference inputs the operator judges; the
tool must not decide them. `prior_scholarship_exclusion` is informational only while the
operator holds no prior research scholarship; promote it to required if that changes.

### 4.2 Why `scheme` is separate from `award`

Universities rebrand the same funding under their own names — Melbourne's Graduate Research
Scholarship and UWA's RTP draw from the same federal block grant but carry different local
rules. One scheme, many awards. A flat table would either duplicate or wrongly merge them.

### 4.3 Institution, filter, discovery_run, candidate — why these exist

- `institution` rows load once from the vendored Hipo directory (§6.0), keyed by domain;
  reloading the directory inserts new institutions and never deletes — same append-only
  philosophy as everything else. Institutions added by hand (missing from Hipo) get
  `source = 'manual'`.
- `filter` is the operator-editable discovery config, persisted (not a transient CLI flag
  bag) so a run is reproducible and diffable against past runs. `filter.yaml` is the file the
  operator actually edits; the CLI syncs it into a `filter` row keyed by content hash before
  each discovery run — the same sync pattern `profile.yaml` uses for `profile` (§4.5).
- `discovery_run` records one execution of a filter: institutions considered, candidates
  found, searches spent. This is the audit trail for what a run cost and covered — it's
  what makes coverage gaps (principle 7) queryable instead of anecdotal.
- `candidate` is raw discovery output before promotion to an `award`. A candidate that
  yields no extractable requirements stays a candidate and is never promoted — visible in
  its `discovery_run`'s counts, never silently dropped. Manual pins from `seeds.yaml` insert
  directly as `candidate` rows with `discovery_run_id = NULL` and
  `query_used = 'manual_pin'`, so pinned and discovered opportunities flow through one
  promotion path, not two.

### 4.4 Append-only requirements

Re-extraction **inserts**, never updates. Resolution order for the effective value of a
field: latest `human_verified`, else latest highest-`source_tier`, else latest.

This gives change history at no cost and is the foundation sub-project 2 (Monitoring)
builds on.

### 4.5 Versioned profile, immutable evaluations

The operator's profile is in flux (English test pending, publication pending, grades
finalising). Without `profile_version` on each evaluation, a verdict recorded in August is
uninterpretable in November.

`evaluation` is an immutable log, not a computed view. This is the only way to answer the
tool's most valuable question: *did this verdict change because the institution changed its
rules, or because I changed?*

## 5. Source tiering

| Tier | Definition | May write fields? |
|---|---|---|
| 1 | The institution's own domain, or a government/agency domain (`education.gov.au`, `eacea.ec.europa.eu`) | Yes |
| 2 | Official aggregators (Study Australia search, DAAD, EACEA catalogue) | No — discovery only |
| 3 | Everything else | No — may be stored as `unverified_note` |

**The curated seed file's declared tier overrides automatic domain classification.** Suffix
matching cannot recognise legitimate consortium domains: `cybersure-master.eu` is an
official Erasmus Mundus programme site and matches no academic suffix. Automatic tiering
still guards anything not hand-added.

A Tier 3 deny-list is maintained for domains observed publishing fabricated figures. These
are excluded from fetch entirely.

**Discovery composes with tiering, not around it.** Because discovery only ever searches
within an institution's own domain (`allowed_domains` scoped to `institution.domain`, §6.0),
every document it surfaces is automatically Tier 1 under the same domain-classification
logic above — no special-casing needed.

## 6. Components and data flow

```
filter.yaml ─┬─→ discovery ──→ candidate ──→ fetcher → documents → extractor → requirements
seeds.yaml ──┘        │                                                 ↓
      institution      │                                    digger (milestone 2, fills NULLs)
      directory ───────┘                                                ↓
                                            profile ──→ evaluator → evaluations → reporter
```

### 6.0 discovery *(new)*

`filter` → `candidate` rows. Owns:

- Loading the vendored institution directory (Hipo's `world_universities_and_domains.json`,
  MIT-licensed, downloaded once and cached locally — not queried live) filtered by
  `filter.country`.
- Per institution, up to `filter.institution_cap` (default 50): one or more
  domain-scoped Claude `web_search` calls (`allowed_domains: [institution.domain]`) built
  from `filter.degree_levels` + `filter.fields`, e.g. *"PhD Computer Science scholarship
  international students"*.
- Recording every institution considered — with a candidate found, or
  `NO_CANDIDATE_FOUND` — in `discovery_run`. An institution is never silently absent from
  the count (principle 7).
- **Caching:** a `discovery_run` for an unchanged `filter` (matched by
  `filter_content_hash`) within the staleness window is reused; `--rediscover` forces a
  fresh pass. Mirrors the fetcher's own "unchanged hash ⇒ no downstream work" rule (§6.1),
  applied to discovery cost.
- Manual pins from `seeds.yaml` are inserted as `candidate` rows alongside discovered ones,
  flowing through the same fetch/extract/evaluate path.
- **Discovery never fetches full page content itself** — Claude's `web_search` returns
  URLs/snippets only (confirmed against current API docs), not full text. Candidate URLs
  are handed to the existing fetcher, unchanged.
- Cost, at the default cap: ≈2–3 searches/institution × 50 institutions ≈ 100–150 searches
  ≈ **$1–1.50** at $10/1,000 searches, plus extraction token cost.

### 6.1 fetcher

URL → `document` row. Owns:

- robots.txt compliance, per-host rate limiting with backoff. Applies identically whether
  the URL came from a hand-curated seed or from discovery — the fetcher does not know or
  care which.
- `http` → `headless` fallback, triggered by heuristic: extracted text below a length
  threshold, or presence of loading-placeholder markers. UWA's HDR page renders `Loading
  component...` to a plain GET — a naive pipeline accepts that as content.
- PDF text extraction. **Not optional:** UWA's binding scholarship conditions are PDFs
  linked from the HTML page.
- Content hashing. Unchanged hash ⇒ no downstream work, no tokens spent.
- Degraded-fetch detection: minimum content length plus expected-keyword presence.

### 6.2 extractor

One document → candidate requirements. Single LLM call, strict JSON schema, closed `kind`
enum, `NULL` preserved, evidence span mandatory.

**The extractor never sees the operator's profile.** Given both the rules and the
applicant, a model will reason about fit and rationalise. The separation is structural.

Enum violations reject the requirement and log to `unclassified_rule`. These are reviewed
after every run — they are how unmodelled requirement types get discovered.

### 6.3 digger (milestone 2)

Per award with a NULL on a required field: a bounded sub-agent with a hard budget. Strategy,
in order: (1) one domain-scoped `web_search` (`allowed_domains` = the award's registrable
domain) targeting the missing field — usually a higher hit rate than blind link-walking; (2)
if that fails, fall back to the original bounded fetch-and-follow — 5 fetches, depth 2, same
registrable domain. Returns value + source URL + evidence, or explicit not-found. Routes
through the fetcher, so every dig is cached, logged and replayable. The external contract
(budget, one target field, explicit not-found) is unchanged from the original draft; only
the internal strategy gained a search-first step.

**Build/evaluate sequencing:** digger is built now, alongside Milestone 1, per the
operator's explicit choice (§12). Its kill criterion (§10) — measuring recall before/after —
still requires a Milestone 1 gold-set baseline to exist first. Digger ships code-complete
but its keep/delete decision is deferred until that baseline is measured; it does not run
against real data before then.

### 6.4 feasibility

Pure function. Given the profile's missing prerequisites, estimates minimum lead time and
compares against days remaining. Initial estimates (operator-tunable in config, not
empirical):

| Missing prerequisite | Lead time added |
|---|---|
| English test result | ~21 days |
| Supervisor agreement required | ~28–42 days |
| Official transcripts + grading key | ~7 days |

This component is what correctly demotes an award that is a perfect profile match but
unreachable in the time remaining.

### 6.5 evaluator

Pure function: requirements + profile version → three-valued outcomes → bucket + sort keys.
**No network, no LLM.** This is what makes it unit-testable and makes "why is this blocked"
answerable in one line.

Grade comparison is deliberately **not** automated. GPA → WAM conversion is
institution-specific and unknowable externally; a stated grade threshold with no verified
conversion yields `unknown`, not a computed pass or fail.

### 6.6 reporter

Markdown report plus CSV. Every row shows its bucket, its reasons, days remaining, and the
source URL and retrieval date for each field used. Adds a **discovery coverage summary**
(institutions considered vs. candidates found vs. `NO_CANDIDATE_FOUND`) per run, so gaps
from principle 7 are visible in the artifact the operator actually reads, not only queryable
in the database.

## 7. Ranking

Lexicographic (tiered) sort, not a weighted score.

**Bucket order:**

1. **ACT NOW** — all required requirements pass; feasible before deadline
2. **ELIGIBLE, LATER** — all pass; deadline beyond the current cycle
3. **UNKNOWN-GATED** — one or more unknowns on required fields
4. **LIKELY BLOCKED** — a verified fail, with the failing requirement named

Named "LIKELY BLOCKED" deliberately: a fail derived from unverified extraction is not
certain.

**Within bucket:** fewest unknowns → fewest days remaining → funding completeness. The key
order lives in config; reordering is the tunable surface.

A record whose `retrieved_at` is older than the staleness threshold cannot enter ACT NOW.

**Safety valve:** UNKNOWN-GATED is sub-sorted fewest-unknowns-first. Records blocked on a
single unverified field surface at the top — that is where the expensive error hides.

This ranking applies identically regardless of whether an award originated from discovery
or a manual pin — `award` carries no field distinguishing its origin once promoted from
`candidate`.

## 8. Failure modes and defences

| Failure | Defence |
|---|---|
| Hallucinated value with plausible evidence | Evidence span must fuzzy-match text in the stored document. Non-matching ⇒ requirement rejected. Mechanical, no model involved. |
| Stale data read as current | `retrieved_at` on every requirement; staleness threshold bars ACT NOW. |
| Wrong intake year | `intake_year` extracted explicitly; mismatch against target cycle ⇒ UNKNOWN-GATED. |
| Partial page (headless returned nav only) | Minimum content length + expected keywords ⇒ `degraded` flag. |
| Unparseable LLM output | One retry with stricter instruction, then `extraction_failed`. Award ⇒ UNKNOWN-GATED. |
| Fetch failure | `fetch_status` recorded; award flagged unfetched and surfaced in report. Never silently skipped. |
| **Requirement on a page never fetched** | **Unfixable in principle.** Partial mitigation: per-scheme checklist of normally-present requirement kinds. A kind entirely absent (no pass, no fail, no unknown) ⇒ **COVERAGE GAP** flag. |
| **Institution in directory, web-search finds nothing relevant** *(new)* | Recorded `NO_CANDIDATE_FOUND` in `discovery_run`, surfaced in the reporter's coverage summary — never silently absent. |
| **Web-search returns a stale/moved page within the right domain** *(new)* | No special handling needed — it's just a fetched document at that point, subject to the same degraded-fetch detection and evidence-span validation as any other. |
| **Institution missing from the Hipo directory entirely** *(new)* | Unfixable via discovery alone. Mitigated by the manual pin list (§4.3); a known limitation, tracked in §11. |

Per-run token cap; breach fails loudly rather than truncating silently. Extends to
per-run **search-call cap** (`filter.institution_cap`) for the same reason.

## 9. Testing and evaluation

### 9.1 Deterministic components — unit tests, TDD applies

`evaluator` table-driven tests, mandatory cases:

- `research_project_fraction` 0.25 required vs 0.10 held → **fail** (UWA case)
- `english_test` required, profile holds none → **unknown, not fail**
- `intake_year` mismatch → UNKNOWN-GATED
- **empty requirement set → COVERAGE GAP, never ELIGIBLE**

Also unit-tested: `feasibility`; evidence-span validator (a fabricated span must be
rejected); reporter sort ordering as a property test; source tiering — **including a
regression test that `cybersure-master.eu` resolves to Tier 1 via seed override**, an
observed bug in an earlier throwaway prototype.

**Discovery's deterministic surface** *(new)*: filter-matching and cache hit/miss logic are
pure functions, unit-tested without network or LLM access — given a filter and prior
`discovery_run` history, does it reuse or refresh; given `institution_cap`, does it stop at
the boundary; does a manual pin always produce a `candidate` regardless of cache state. The
`web_search` call itself is mocked via recorded fixtures in this suite — never live-called
in tests that must run offline and reproducibly, matching the evaluator's "no network, no
LLM" spirit.

### 9.2 Extractor — evaluation, not tests

Gold set: 15 documents hand-annotated by the operator, committed as fixtures so evaluation
runs offline and reproducibly. Sourced by running discovery for real, once built, against
the operator's actual first filter — candidate annotations drafted by the assistant from
what discovery finds, corrected by the operator. Must deliberately include:

- A binding requirement stated as prose fraction on a secondary page (the UWA-course-rules
  shape), not the primary scholarship page
- A JS-rendered page, near-empty to a plain GET
- A scholarship conditions PDF — rules in an attachment
- A page with dates in an awkward/non-ISO format
- One page with **no** relevant requirements — measures false positives
- A scheme-level rules page (e.g. a national funder page) — tests that scheme-level
  requirements are not wrongly attached to a single award

**Metrics per requirement kind, never aggregated.** Aggregate accuracy hides the single
field that ruins a cycle.

**Recall is the primary metric.** A missed requirement produces a false ELIGIBLE and costs
an application cycle; a precision miss costs one wasted page read. The asymmetry is roughly
a year against ten minutes.

Hallucination rate (requirements whose evidence fails span validation) target: zero. Should
be mechanically impossible post-validator.

### 9.3 Trust gate

A requirement kind may produce a LIKELY BLOCKED verdict only once its gold-set recall clears
the operator-set threshold. Below threshold, a fail downgrades to UNKNOWN-GATED. This is
principle 6 made mechanical.

**Starting threshold: 85%.** Chosen as a conservative default in the absence of real
recall data (see §12) — the first thing to revisit once Milestone 1's gold-set run produces
actual per-kind numbers.

## 10. Milestones and kill criteria

**Milestone 1 — deterministic pipeline + discovery.** filter → discovery → fetcher →
extractor → evaluator → reporter, plus gold set and the full deterministic test suite.
*Kill criterion:* if per-kind recall on the gold set does not clear the trust threshold for
`deadline`, `thesis_required` and `research_project_fraction`, stop and reconsider the
extraction approach. Everything downstream is worthless without these three.

**Milestone 2 — bounded digger.** Built alongside Milestone 1 (operator's explicit choice —
see §12). *Kill criterion, pre-committed:* measure per-kind recall and COVERAGE GAP count
before and after enabling digger against real data. This measurement — and therefore the
keep/delete decision — cannot happen until Milestone 1's gold-set baseline exists; digger
ships code-complete and gated until then. If the digger does not improve recall, delete it.

Both milestones are built in this implementation pass; Milestone 2's *evaluation* is
sequenced after Milestone 1's baseline is measured, not after Milestone 2's code is written.

## 11. Open questions

- **Grade conversion.** Deliberately unresolved in code. The operator must obtain the
  official grading-scale key and populate `wam_equivalent` manually; until then it stays
  `NULL` and produces `unknown`.
- **Operator profile values.** `profile.yaml` is scaffolded with placeholder/`NULL` fields
  (nationality, current grade, English-test status, target intake, etc.) for the operator to
  fill in after setup. Several schemes cannot produce a meaningful ELIGIBLE verdict until
  this is populated.
- **Staleness threshold value.** Start at 30 days; revisit once change frequency is observed
  in sub-project 2.
- **Institution directory staleness.** *(New.)* Hipo's dataset updates are crowdsourced and
  irregular — no automatic refresh mechanism in Milestone 1. If missed-institution reports
  become frequent, revisit; the manual pin list is the interim mitigation.

## 12. Decision log

| Decision | Rationale |
|---|---|
| Single-user, local CLI | No auth, hosting, or UI cost. Correctness over polish. |
| Core + Eligibility as one spec | The engine is meaningless without the requirement store. |
| Rank fully, never eliminate | A false block silently deletes an opportunity and is never discovered; a false eligible costs one page read. |
| Tiered sort over weighted score | Limited records, no outcome data ⇒ weights unfalsifiable and tuning is theatre. |
| Approach C (deterministic spine + bounded digger), phased | Adaptive exactly where the observed failure was; deterministic and replayable everywhere else. |
| Extractor blind to profile | Prevents fit-reasoning and rationalisation. |
| **Filter-driven automated discovery, replacing hand-curated-only seeds** | Operator wants exhaustive coverage of every institution in a country matching a filter, not a pre-picked list of 20–40 targets. Verified feasible and cheap (~$1–1.50/run at the default cap) before committing — see research below. |
| **Hipo `university-domains-list` as the base institution directory** | Only open, MIT-licensed, globally-covering dataset with both country and domain fields in one machine-readable file; official registries (Canada DLI, Australia TEQSA, UK OfS) are authoritative for accreditation status but ship no bulk domain-mapped export, so they're not viable as a bootstrap layer. |
| **Claude `web_search` tool, domain-scoped per institution, for discovery** | Confirmed against current API docs: returns URLs/snippets only, not full page text, so it composes with the existing fetcher rather than replacing it. `allowed_domains` keeps each search bounded to the institution actually being checked. |
| **Discovery cached per filter, `--rediscover` to force refresh** | Mirrors the existing "unchanged hash ⇒ no downstream work, no tokens spent" principle, applied to discovery cost, not just fetch cost. |
| **Manual pin list (`seeds.yaml`) retained alongside discovery** | Cheap safety net against directory gaps or search misses on an opportunity the operator already knows about. |
| **Default institution cap: 50/run, configurable** | Cost containment (~$1–1.50/run in search cost); extends the existing "breach fails loudly, never silently truncates" principle to institution count. |
| **Trust threshold defaults to 85%, explicit revisit after real gold-set data** | Cannot be meaningfully chosen before real recall numbers exist; avoids the same false-precision trap already rejected for weighted composite scoring. |
| **Milestone 1 + 2 built together; Milestone 2's evaluation still sequenced after Milestone 1's baseline** | Operator's explicit choice to build both now; kill-criterion logic preserved by gating the *decision*, not the *code*, on the baseline measurement. |
| Python + `uv` | `uv` provisions its own Python — no separate interpreter install needed on this machine, which currently only has the Microsoft Store stub alias. |
| Claude (Anthropic API) for both extraction and discovery search | One provider, one API key, one billing surface; `web_search` tool composes with the extractor's own LLM calls. |
| Local git repo, `.env` (git-ignored) for `ANTHROPIC_API_KEY` | Standard hygiene for a single-user local tool; no key ever committed. |
| Discovery deferred *(original draft's framing — revised above)* | Original rationale was "20–40 targets needed, not thousands, hand-curation beats a crawler." Superseded once the operator clarified the actual want was exhaustive per-country coverage, and research confirmed a bounded, domain-scoped search approach is neither a general crawler nor prohibitively expensive. |
