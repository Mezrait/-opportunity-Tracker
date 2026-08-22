# Opportunity Tracker Implementation Plan — Part B: Config & Sync Layer (Tasks 5–8)

> Companion to `docs/superpowers/plans/2026-08-22-opportunity-tracker.md`. Builds directly
> on that file's Tasks 1–4 (`models.py`, `config.py`, `db.py`) — every import below refers to
> those modules exactly as implemented there. Do not redefine any dataclass, enum, or table
> from those tasks here.

---

### Task 5: Source tiering (`tiering.py`)

**Files:**
- Create: `src/opportunity_tracker/tiering.py`
- Test: `tests/unit/test_tiering.py`

**Interfaces:**
- Consumes: `models.SourceTier` (`TIER_1 = 1`, `TIER_2 = 2`, `TIER_3 = 3`) from Task 2's
  `models.py`.
- Produces: `classify_tier(domain: str, seed_override: int | None = None) -> SourceTier` and
  `is_denied(domain: str, deny_list: set[str]) -> bool` — called later by the fetcher's
  `pipeline.py` (Task 13, to set `document.source_tier`) and by discovery's `websearch.py`
  and `run.py` (Tasks 14–15, to confirm every domain-scoped search result is Tier 1, and to
  skip denied domains before fetching).

This is a deterministic, pure-logic component — no network, no LLM, no I/O. Strict TDD
applies: the spec's own mandatory regression test (§9.1) is written first, verbatim.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tiering.py
from opportunity_tracker.models import SourceTier
from opportunity_tracker.tiering import classify_tier, is_denied


def test_seed_override_wins_even_when_domain_matches_no_known_pattern():
    # Regression test (spec §5, §9.1): cybersure-master.eu is a real Erasmus
    # Mundus consortium domain that matches no academic/government suffix, but
    # the curated seed file marks it Tier 1. Suffix matching alone would wrongly
    # classify it Tier 3 — an observed bug in an earlier throwaway prototype.
    assert classify_tier("cybersure-master.eu", seed_override=1) == SourceTier.TIER_1


def test_seed_override_can_downgrade_an_academic_domain():
    assert classify_tier("mit.edu", seed_override=3) == SourceTier.TIER_3


def test_academic_edu_domain_is_tier_1_without_override():
    assert classify_tier("mit.edu") == SourceTier.TIER_1


def test_edu_au_domain_is_tier_1():
    assert classify_tier("unimelb.edu.au") == SourceTier.TIER_1


def test_ac_uk_domain_is_tier_1():
    assert classify_tier("ox.ac.uk") == SourceTier.TIER_1


def test_gov_domain_is_tier_1():
    assert classify_tier("education.gov.au") == SourceTier.TIER_1


def test_known_aggregator_domains_are_tier_2():
    assert classify_tier("daad.de") == SourceTier.TIER_2
    assert classify_tier("eacea.ec.europa.eu") == SourceTier.TIER_2


def test_unknown_domain_is_tier_3():
    assert classify_tier("some-random-blog.com") == SourceTier.TIER_3


def test_is_denied_true_for_listed_domain():
    deny_list = {"scam-scholarships.example", "fake-uni-list.example"}
    assert is_denied("scam-scholarships.example", deny_list) is True


def test_is_denied_false_for_unlisted_domain():
    deny_list = {"scam-scholarships.example"}
    assert is_denied("legit-university.edu", deny_list) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tiering.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.tiering'`

- [ ] **Step 3: Write `src/opportunity_tracker/tiering.py`**

```python
"""Domain -> SourceTier classification. Pure function, no I/O. See spec §5, §9.1.

The curated seed file's declared tier (`seed_override`) always wins over automatic
domain classification — suffix matching cannot recognise legitimate consortium
domains like cybersure-master.eu, an official Erasmus Mundus programme site that
matches no academic suffix. Automatic tiering still guards anything not hand-added.
"""
from __future__ import annotations

from opportunity_tracker.models import SourceTier

# Academic and government suffixes. A domain ending in any of these, with no seed
# override, is Tier 1 (the institution's own domain, or a government/agency domain).
TIER_1_SUFFIXES: tuple[str, ...] = (
    ".edu",
    ".edu.au",
    ".ac.uk",
    ".ac.nz",
    ".ac.at",
    ".ac.jp",
    ".ac.za",
    ".gov",
    ".gov.au",
    ".gov.uk",
)

# Known official aggregators: Tier 2 (discovery only, never writes fields). Small
# hardcoded list — these are catalogue/search domains, not any single institution's
# own domain, and not the primary regulatory/agency domain itself.
TIER_2_AGGREGATOR_DOMAINS: frozenset[str] = frozenset({
    "daad.de",
    "eacea.ec.europa.eu",
})


def classify_tier(domain: str, seed_override: int | None = None) -> SourceTier:
    if seed_override is not None:
        return SourceTier(seed_override)

    normalized = domain.strip().lower()

    if any(normalized.endswith(suffix) for suffix in TIER_1_SUFFIXES):
        return SourceTier.TIER_1

    if normalized in TIER_2_AGGREGATOR_DOMAINS:
        return SourceTier.TIER_2

    return SourceTier.TIER_3


def is_denied(domain: str, deny_list: set[str]) -> bool:
    normalized = domain.strip().lower()
    normalized_deny_list = {d.strip().lower() for d in deny_list}
    return normalized in normalized_deny_list
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tiering.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/tiering.py tests/unit/test_tiering.py
git commit -m "feat: source tiering classification (tiering.py)"
```

---

### Task 6: Profile sync (`profile.py`)

**Files:**
- Create: `src/opportunity_tracker/profile.py`
- Test: `tests/unit/test_profile.py`

**Interfaces:**
- Consumes: `db.get_connection(db_path: str) -> sqlite3.Connection`,
  `db.init_db(conn: sqlite3.Connection) -> None` from Task 4's `db.py`; `models.Profile`
  (`id`, `version`, `created_at`, `attributes`) from Task 2's `models.py`.
- Produces: `sync_profile(yaml_path: str, conn: sqlite3.Connection) -> Profile` — called
  later by the evaluator's `run.py` (Task 23, to resolve the current profile version before
  evaluating an award) and by `cli.py` (Task 26, on every pipeline run).

Deterministic file+DB sync logic, no network or LLM call — tested directly, no mocking
required.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_profile.py
from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import Profile
from opportunity_tracker.profile import sync_profile

PROFILE_V1 = """
nationality: null
current_grade: null
english_test_status: null
target_intake_year: 2027
degree_level: phd
field: computer science
"""

PROFILE_V2 = """
nationality: null
current_grade: null
english_test_status: ielts_pending
target_intake_year: 2027
degree_level: phd
field: computer science
"""


def _write_yaml(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_sync_profile_creates_version_1_when_no_profile_exists(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)
    yaml_path = _write_yaml(tmp_path, "profile.yaml", PROFILE_V1)

    profile = sync_profile(yaml_path, conn)

    assert isinstance(profile, Profile)
    assert profile.version == 1
    assert profile.attributes["target_intake_year"] == 2027
    assert profile.attributes["english_test_status"] is None
    rows = conn.execute("SELECT COUNT(*) AS n FROM profile").fetchone()
    assert rows["n"] == 1


def test_sync_profile_unchanged_yaml_produces_no_new_row(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)
    yaml_path = _write_yaml(tmp_path, "profile.yaml", PROFILE_V1)

    first = sync_profile(yaml_path, conn)
    second = sync_profile(yaml_path, conn)

    assert first.version == second.version == 1
    assert first.id == second.id
    rows = conn.execute("SELECT COUNT(*) AS n FROM profile").fetchone()
    assert rows["n"] == 1


def test_sync_profile_changed_yaml_produces_version_2(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)
    yaml_path = _write_yaml(tmp_path, "profile.yaml", PROFILE_V1)
    sync_profile(yaml_path, conn)

    changed_path = _write_yaml(tmp_path, "profile_v2.yaml", PROFILE_V2)
    second = sync_profile(changed_path, conn)

    assert second.version == 2
    assert second.attributes["english_test_status"] == "ielts_pending"
    rows = conn.execute("SELECT COUNT(*) AS n FROM profile").fetchone()
    assert rows["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.profile'`

- [ ] **Step 3: Write `src/opportunity_tracker/profile.py`**

```python
"""profile.yaml <-> `profile` table sync. See spec §4.5, §11.

The operator's profile is in flux (English test pending, grades finalising).
Comparing the new YAML against the latest stored version means an unchanged file
never creates a spurious new profile_version, while any real change is captured
as a new, immutable version so past evaluations stay interpretable.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import yaml

from opportunity_tracker.models import Profile


def _load_yaml_attributes(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _latest_profile_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, version, created_at, attributes FROM profile "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()


def sync_profile(yaml_path: str, conn: sqlite3.Connection) -> Profile:
    attributes = _load_yaml_attributes(yaml_path)
    existing = _latest_profile_row(conn)

    if existing is not None and json.loads(existing["attributes"]) == attributes:
        return Profile(
            id=existing["id"],
            version=existing["version"],
            created_at=existing["created_at"],
            attributes=json.loads(existing["attributes"]),
        )

    next_version = (existing["version"] + 1) if existing is not None else 1
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES (?, ?, ?)",
        (next_version, created_at, json.dumps(attributes, sort_keys=True)),
    )
    conn.commit()
    return Profile(
        id=cursor.lastrowid,
        version=next_version,
        created_at=created_at,
        attributes=attributes,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_profile.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/profile.py tests/unit/test_profile.py
git commit -m "feat: profile.yaml sync (profile.py)"
```

---

### Task 7: Filter sync (`filters.py`)

**Files:**
- Create: `src/opportunity_tracker/filters.py`
- Test: `tests/unit/test_filters.py`
- Test fixture: `tests/fixtures/filter_canada_cs_phd.yaml`

**Interfaces:**
- Consumes: `db.get_connection(db_path: str) -> sqlite3.Connection`,
  `db.init_db(conn: sqlite3.Connection) -> None` from Task 4's `db.py`; `models.Filter`
  (`id`, `name`, `country`, `degree_levels`, `fields`, `funding_type`, `deadline_after`,
  `min_grade`, `institution_cap`, `content_hash`, `created_at`) from Task 2's `models.py`;
  `config.INSTITUTION_CAP_DEFAULT` (50) from Task 3's `config.py`.
- Produces: `sync_filter(yaml_path: str, conn: sqlite3.Connection) -> Filter` — called later
  by discovery's `run.py` (Task 15, to resolve the current filter and its `content_hash`
  before starting or reusing a `discovery_run`) and by `cli.py` (Task 26).

Same sync pattern as `profile.py`, but keyed by a content hash instead of a monotonic
version: a filter has no "supersedes" semantics, just identity — syncing byte-identical
content always resolves to the same row. Deterministic file+DB logic, no network/LLM call —
tested directly, no mocking required.

- [ ] **Step 1: Create the fixture and write the failing test**

```yaml
# tests/fixtures/filter_canada_cs_phd.yaml
name: canada-cs-phd
country: Canada
degree_levels: [phd]
fields: [computer science]
funding_type: null
deadline_after: null
min_grade: null
institution_cap: 50
```

```python
# tests/unit/test_filters.py
from pathlib import Path

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.filters import sync_filter
from opportunity_tracker.models import Filter

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "filter_canada_cs_phd.yaml"


def test_sync_filter_creates_row_from_fixture():
    conn = get_connection(":memory:")
    init_db(conn)

    filt = sync_filter(str(FIXTURE_PATH), conn)

    assert isinstance(filt, Filter)
    assert filt.name == "canada-cs-phd"
    assert filt.country == "Canada"
    assert filt.degree_levels == ["phd"]
    assert filt.fields == ["computer science"]
    assert filt.funding_type is None
    assert filt.institution_cap == 50
    rows = conn.execute("SELECT COUNT(*) AS n FROM filter").fetchone()
    assert rows["n"] == 1


def test_sync_filter_same_file_twice_reuses_row():
    conn = get_connection(":memory:")
    init_db(conn)

    first = sync_filter(str(FIXTURE_PATH), conn)
    second = sync_filter(str(FIXTURE_PATH), conn)

    assert first.id == second.id
    assert first.content_hash == second.content_hash
    rows = conn.execute("SELECT COUNT(*) AS n FROM filter").fetchone()
    assert rows["n"] == 1


def test_sync_filter_changed_fields_produces_new_row(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)
    first = sync_filter(str(FIXTURE_PATH), conn)

    changed_path = tmp_path / "filter_changed.yaml"
    changed_path.write_text(
        "name: canada-cs-phd\n"
        "country: Canada\n"
        "degree_levels: [phd]\n"
        "fields: [robotics]\n"
        "funding_type: null\n"
        "deadline_after: null\n"
        "min_grade: null\n"
        "institution_cap: 50\n",
        encoding="utf-8",
    )
    second = sync_filter(str(changed_path), conn)

    assert second.id != first.id
    assert second.fields == ["robotics"]
    assert second.content_hash != first.content_hash
    rows = conn.execute("SELECT COUNT(*) AS n FROM filter").fetchone()
    assert rows["n"] == 2


def test_sync_filter_missing_institution_cap_defaults_to_50(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)

    path = tmp_path / "filter_no_cap.yaml"
    path.write_text(
        "name: no-cap-filter\n"
        "country: Canada\n"
        "degree_levels: [phd]\n"
        "fields: [computer science]\n",
        encoding="utf-8",
    )
    filt = sync_filter(str(path), conn)

    assert filt.institution_cap == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.filters'`

- [ ] **Step 3: Write `src/opportunity_tracker/filters.py`**

```python
"""filter.yaml <-> `filter` table sync. See spec §4.3.

Same sync pattern as profile.py, but keyed by content hash instead of a monotonic
version — a filter has no "supersedes" semantics, just identity. Reusing a row for
byte-identical content is what makes discovery_run caching (§6.0) possible: an
unchanged filter, matched by content_hash, reuses a prior discovery_run within the
staleness window instead of spending searches again.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import yaml

from opportunity_tracker import config
from opportunity_tracker.models import Filter


def _load_yaml(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _normalize(data: dict) -> dict:
    return {
        "name": data.get("name"),
        "country": data.get("country"),
        "degree_levels": data.get("degree_levels") or [],
        "fields": data.get("fields") or [],
        "funding_type": data.get("funding_type"),
        "deadline_after": data.get("deadline_after"),
        "min_grade": data.get("min_grade"),
        "institution_cap": data.get("institution_cap", config.INSTITUTION_CAP_DEFAULT),
    }


def _content_hash(normalized: dict) -> str:
    serialized = json.dumps(normalized, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _row_to_filter(row: sqlite3.Row) -> Filter:
    return Filter(
        id=row["id"],
        name=row["name"],
        country=row["country"],
        degree_levels=json.loads(row["degree_levels"]),
        fields=json.loads(row["fields"]),
        funding_type=row["funding_type"],
        deadline_after=row["deadline_after"],
        min_grade=row["min_grade"],
        institution_cap=row["institution_cap"],
        content_hash=row["content_hash"],
        created_at=row["created_at"],
    )


def sync_filter(yaml_path: str, conn: sqlite3.Connection) -> Filter:
    normalized = _normalize(_load_yaml(yaml_path))
    content_hash = _content_hash(normalized)

    existing = conn.execute(
        "SELECT * FROM filter WHERE content_hash = ? ORDER BY id LIMIT 1",
        (content_hash,),
    ).fetchone()
    if existing is not None:
        return _row_to_filter(existing)

    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO filter (name, country, degree_levels, fields, funding_type, "
        "deadline_after, min_grade, institution_cap, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            normalized["name"],
            normalized["country"],
            json.dumps(normalized["degree_levels"]),
            json.dumps(normalized["fields"]),
            normalized["funding_type"],
            normalized["deadline_after"],
            normalized["min_grade"],
            normalized["institution_cap"],
            content_hash,
            created_at,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM filter WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_filter(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/filters.py tests/unit/test_filters.py tests/fixtures/filter_canada_cs_phd.yaml
git commit -m "feat: filter.yaml sync (filters.py)"
```

---

### Task 8: Institution directory loader (`directory.py`)

**Files:**
- Create: `src/opportunity_tracker/directory.py`
- Test: `tests/unit/test_directory.py`
- Test fixture: `tests/fixtures/institution_directory_sample.json`

**Interfaces:**
- Consumes: `db.get_connection(db_path: str) -> sqlite3.Connection`,
  `db.init_db(conn: sqlite3.Connection) -> None` from Task 4's `db.py`; `models.Institution`
  (`id`, `name`, `country`, `country_code`, `domain`, `source`, `directory_version`,
  `added_at`) and `models.InstitutionSource` (`HIPO_DIRECTORY`, `MANUAL`) from Task 2's
  `models.py`.
- Produces: `load_institution_directory(json_path: str, conn: sqlite3.Connection,
  directory_version: str) -> int` and `list_institutions(conn: sqlite3.Connection, country:
  str) -> list[Institution]` — called later by discovery's `run.py` (Task 15, to enumerate
  the institutions a discovery run must consider for `filter.country`) and by `cli.py`
  (Task 26, for a one-time directory-load command).

Deterministic file+DB logic, no network/LLM call — tested directly against a small local
fixture, no mocking required. The real ~9,000-entry Hipo dataset is vendored separately by a
later manual step (`data/university_directory.json`, per the file structure), not by this
test.

- [ ] **Step 1: Create the fixture and write the failing test**

```json
[
  {
    "name": "University of Toronto",
    "country": "Canada",
    "alpha_two_code": "CA",
    "domains": ["utoronto.ca"],
    "web_pages": ["https://www.utoronto.ca/"]
  },
  {
    "name": "University of British Columbia",
    "country": "Canada",
    "alpha_two_code": "CA",
    "domains": ["ubc.ca"],
    "web_pages": ["https://www.ubc.ca/"]
  },
  {
    "name": "McGill University",
    "country": "Canada",
    "alpha_two_code": "CA",
    "domains": ["mcgill.ca"],
    "web_pages": ["https://www.mcgill.ca/"]
  },
  {
    "name": "University of Melbourne",
    "country": "Australia",
    "alpha_two_code": "AU",
    "domains": ["unimelb.edu.au"],
    "web_pages": ["https://www.unimelb.edu.au/"]
  }
]
```

Save the JSON above as `tests/fixtures/institution_directory_sample.json`.

```python
# tests/unit/test_directory.py
from pathlib import Path

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.directory import load_institution_directory, list_institutions
from opportunity_tracker.models import Institution, InstitutionSource

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "institution_directory_sample.json"
)


def test_load_institution_directory_inserts_new_rows():
    conn = get_connection(":memory:")
    init_db(conn)

    inserted = load_institution_directory(
        str(FIXTURE_PATH), conn, directory_version="2026-08-01"
    )

    assert inserted == 4
    canada = list_institutions(conn, "canada")  # lower-case: case-insensitive match
    assert [i.name for i in canada] == [
        "McGill University",
        "University of British Columbia",
        "University of Toronto",
    ]
    assert all(isinstance(i, Institution) for i in canada)
    assert all(i.source == InstitutionSource.HIPO_DIRECTORY for i in canada)
    assert all(i.directory_version == "2026-08-01" for i in canada)


def test_load_institution_directory_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    load_institution_directory(str(FIXTURE_PATH), conn, directory_version="2026-08-01")

    second_pass = load_institution_directory(
        str(FIXTURE_PATH), conn, directory_version="2026-09-01"
    )

    assert second_pass == 0
    total = conn.execute("SELECT COUNT(*) AS n FROM institution").fetchone()["n"]
    assert total == 4


def test_load_institution_directory_does_not_overwrite_manual_row():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "U of T (manually added)",
            "Canada",
            "CA",
            "utoronto.ca",
            InstitutionSource.MANUAL.value,
            None,
            "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()

    inserted = load_institution_directory(
        str(FIXTURE_PATH), conn, directory_version="2026-08-01"
    )

    assert inserted == 3  # utoronto.ca already present as a manual row, skipped
    row = conn.execute(
        "SELECT name, source FROM institution WHERE domain = ?", ("utoronto.ca",)
    ).fetchone()
    assert row["name"] == "U of T (manually added)"
    assert row["source"] == InstitutionSource.MANUAL.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_directory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.directory'`

- [ ] **Step 3: Write `src/opportunity_tracker/directory.py`**

```python
"""Hipo world_universities_and_domains.json -> `institution` table loader.
See spec §4.3, §6.0, §11.

Append-only, keyed by domain: reloading the directory inserts new institutions and
never deletes or updates existing rows — including rows a domain shares with a
manually-added institution, which always wins and is never overwritten.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from opportunity_tracker.models import Institution, InstitutionSource


def _row_to_institution(row: sqlite3.Row) -> Institution:
    return Institution(
        id=row["id"],
        name=row["name"],
        country=row["country"],
        country_code=row["country_code"],
        domain=row["domain"],
        source=InstitutionSource(row["source"]),
        directory_version=row["directory_version"],
        added_at=row["added_at"],
    )


def load_institution_directory(
    json_path: str, conn: sqlite3.Connection, directory_version: str
) -> int:
    with open(json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    inserted = 0
    added_at = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        name = entry.get("name")
        country = entry.get("country")
        country_code = entry.get("alpha_two_code")
        for domain in entry.get("domains") or []:
            existing = conn.execute(
                "SELECT id FROM institution WHERE domain = ?", (domain,)
            ).fetchone()
            if existing is not None:
                continue
            conn.execute(
                "INSERT INTO institution (name, country, country_code, domain, "
                "source, directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    country,
                    country_code,
                    domain,
                    InstitutionSource.HIPO_DIRECTORY.value,
                    directory_version,
                    added_at,
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def list_institutions(conn: sqlite3.Connection, country: str) -> list[Institution]:
    rows = conn.execute(
        "SELECT * FROM institution WHERE LOWER(country) = LOWER(?) ORDER BY name",
        (country,),
    ).fetchall()
    return [_row_to_institution(row) for row in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_directory.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/directory.py tests/unit/test_directory.py tests/fixtures/institution_directory_sample.json
git commit -m "feat: institution directory loader (directory.py)"
```
