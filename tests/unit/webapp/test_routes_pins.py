"""Tests for the Pinned Links screen (Task 6). A pin is an operator-curated URL that
flows through the same fetch/extract/evaluate pipeline as a discovered candidate, but is
recorded with `discovery_run_id IS NULL` -- that's what distinguishes it from a
discovery-found candidate. POSTing a pin must write it to `seeds.yaml`
(`config.SEEDS_PATH`) AND actually call `discovery_run.ingest_manual_pins` so a real
`candidate` row lands in the database -- these tests check the database, not just the
YAML file shape."""
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opportunity_tracker import config, db
from opportunity_tracker.models import InstitutionSource
from opportunity_tracker.webapp import routes_pins
from opportunity_tracker.webapp.deps import get_db


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(routes_pins.router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_db():
    """Return an in-memory SQLite connection with initialized schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _isolated_seeds_path(tmp_path, monkeypatch):
    """`config.SEEDS_PATH` is read fresh on every request, so patching the module
    attribute is enough -- no need to touch anything inside routes_pins itself."""
    monkeypatch.setattr(config, "SEEDS_PATH", str(tmp_path / "seeds.yaml"))


@pytest.fixture
def wired(app, seeded_db):
    """Wire the test app's get_db dependency to the seeded in-memory connection."""
    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    return seeded_db


def _seed_institution(conn, domain, name="Test Uni", country="Testland"):
    cursor = conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, 'XX', ?, ?, NULL, '2026-08-23T00:00:00')",
        (name, country, domain, InstitutionSource.MANUAL.value),
    )
    conn.commit()
    return cursor.lastrowid


def test_get_pins_empty_state(client, wired):
    """Case 1: GET /pins with no pins yet -> 200, empty-state message."""
    response = client.get("/pins")
    assert response.status_code == 200
    assert "no pinned links" in response.text.lower() or "no pins" in response.text.lower()


def test_post_pin_writes_seed_and_creates_candidate(client, wired):
    """Case 2: POST /pins/add with institution_domain/url only (domain matches a
    pre-seeded institution row) -> 303 redirect to /pins; seeds.yaml now exists and
    contains one entry with just those two keys; a candidate row now exists with
    discovery_run_id IS NULL for that institution."""
    institution_id = _seed_institution(wired, domain="uwa.edu.au")

    response = client.post(
        "/pins/add",
        data={
            "institution_domain": "uwa.edu.au",
            "url": "https://www.uwa.edu.au/study/scholarships/international-rtp",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/pins"

    seeds_path = Path(config.SEEDS_PATH)
    assert seeds_path.exists()
    seeds = yaml.safe_load(seeds_path.read_text(encoding="utf-8"))
    assert seeds == [
        {
            "institution_domain": "uwa.edu.au",
            "url": "https://www.uwa.edu.au/study/scholarships/international-rtp",
        }
    ]

    candidate_row = wired.execute(
        "SELECT * FROM candidate WHERE url = ?",
        ("https://www.uwa.edu.au/study/scholarships/international-rtp",),
    ).fetchone()
    assert candidate_row is not None
    assert candidate_row["discovery_run_id"] is None
    assert candidate_row["institution_id"] == institution_id


def test_get_pins_after_post_shows_pinned_url(client, wired):
    """Case 3: GET /pins after Case 2 -> 200, response body shows the pinned URL."""
    _seed_institution(wired, domain="uwa.edu.au")
    client.post(
        "/pins/add",
        data={
            "institution_domain": "uwa.edu.au",
            "url": "https://www.uwa.edu.au/study/scholarships/international-rtp",
        },
        follow_redirects=False,
    )

    response = client.get("/pins")
    assert response.status_code == 200
    assert "https://www.uwa.edu.au/study/scholarships/international-rtp" in response.text


def test_duplicate_pin_post_still_one_candidate_row(client, wired):
    """Case 4: POST /pins/add twice with the identical domain+url -> still only one
    candidate row (dedup is ingest_manual_pins's own already-tested job -- this test
    just confirms the route doesn't break it)."""
    _seed_institution(wired, domain="uwa.edu.au")
    data = {
        "institution_domain": "uwa.edu.au",
        "url": "https://www.uwa.edu.au/study/scholarships/international-rtp",
    }

    first = client.post("/pins/add", data=data, follow_redirects=False)
    second = client.post("/pins/add", data=data, follow_redirects=False)

    assert first.status_code == 303
    assert second.status_code == 303

    rows = wired.execute(
        "SELECT * FROM candidate WHERE url = ?",
        ("https://www.uwa.edu.au/study/scholarships/international-rtp",),
    ).fetchall()
    assert len(rows) == 1


def test_post_pin_unmatched_domain_with_declared_tier_and_name_country(client, wired):
    """Case 5: POST /pins/add with declared_tier=1 and a domain NOT in any existing
    institution row, plus name/country provided -> succeeds. This is the
    Erasmus-Mundus-style worked example from seeds.example.yaml -- a domain matching no
    institution still ingests correctly when name/country are supplied."""
    response = client.post(
        "/pins/add",
        data={
            "institution_domain": "cybersure-master.eu",
            "url": "https://www.cybersure-master.eu/admission",
            "name": "CyberSure Erasmus Mundus Joint Master",
            "country": "Belgium",
            "declared_tier": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303

    institution_row = wired.execute(
        "SELECT * FROM institution WHERE domain = ?", ("cybersure-master.eu",)
    ).fetchone()
    assert institution_row is not None
    assert institution_row["name"] == "CyberSure Erasmus Mundus Joint Master"
    assert institution_row["country"] == "Belgium"

    candidate_row = wired.execute(
        "SELECT * FROM candidate WHERE url = ?",
        ("https://www.cybersure-master.eu/admission",),
    ).fetchone()
    assert candidate_row is not None
    assert candidate_row["discovery_run_id"] is None
    assert candidate_row["declared_tier"] == 1

    seeds_path = Path(config.SEEDS_PATH)
    seeds = yaml.safe_load(seeds_path.read_text(encoding="utf-8"))
    assert seeds == [
        {
            "institution_domain": "cybersure-master.eu",
            "url": "https://www.cybersure-master.eu/admission",
            "name": "CyberSure Erasmus Mundus Joint Master",
            "country": "Belgium",
            "declared_tier": 1,
        }
    ]
