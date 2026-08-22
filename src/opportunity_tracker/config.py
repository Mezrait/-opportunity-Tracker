"""Environment loading and tunable constants. Values here are the spec's defaults —
see docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md §9.3, §11, §6.0."""
import os

from dotenv import load_dotenv

load_dotenv()

STALENESS_DAYS = 30
TRUST_THRESHOLD_DEFAULT = 0.85
INSTITUTION_CAP_DEFAULT = 50

# Lead time added per missing prerequisite, in days (§6.4). A tuple is a (min, max) range.
FEASIBILITY_LEAD_DAYS: dict[str, int | tuple[int, int]] = {
    "english_test_result": 21,
    "supervisor_agreement": (28, 42),
    "transcripts": 7,
}

DB_PATH = "opportunity_tracker.db"
UNIVERSITY_DIRECTORY_PATH = "data/university_directory.json"
PROFILE_PATH = "profile.yaml"
FILTER_PATH = "filter.yaml"
SEEDS_PATH = "seeds.yaml"
DENY_LIST_PATH = "data/tier3_deny_list.yaml"


def get_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key
