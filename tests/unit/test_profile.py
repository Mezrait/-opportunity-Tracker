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
