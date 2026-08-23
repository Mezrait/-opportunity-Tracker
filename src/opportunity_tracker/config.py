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


def get_groq_api_key() -> str:
    """Powers the extractor and digger's structured-extraction calls (spec §6.2, §6.3) --
    swapped in from Anthropic 2026-08-23 for cost; see the web-UI design spec's decision
    log. Groq's free tier (14,400 requests/day) comfortably covers a full run."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key


def get_tavily_api_key() -> str:
    """Powers discovery and digger's web-search calls (spec §6.0, §6.3) -- swapped in
    from Anthropic's web_search tool 2026-08-23 for cost. Tavily's free tier is 1,000
    search credits/month, roughly 6-10 full runs at this tool's default institution_cap."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key
