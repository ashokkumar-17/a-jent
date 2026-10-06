"""
Job Filtering Module
--------------------
Extracted from job_search_agent.py (Task 10).

Responsible for:
- Seniority/level filter configuration and evaluation (passes_level_filter)
- Location preference configuration and evaluation (passes_location_filter)
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
CONFIG_FILE = BASE_DIR / "config.yaml"


# -----------------------------------------------------------------------
# CONFIG LOADER — env var > config.yaml > default
# -----------------------------------------------------------------------
def _load_yaml_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[WARN] Could not load config.yaml in job_filter: {e}")
        return {}


def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception as e:
        print(f"[WARN] Could not load .env in job_filter: {e}")


_load_dotenv()
_cfg = _load_yaml_config()


def _get(key: str, default, cast=None):
    """Resolve: env var > config.yaml > default."""
    env_val = os.environ.get(key.upper())
    if env_val is not None:
        val = env_val
    else:
        val = _cfg.get(key.lower(), default)
    if cast and val is not None:
        try:
            return cast(val)
        except Exception:
            return default
    return val


# --- Filter Configuration Constants ---
LEVEL_FILTERS = _get("LEVEL_FILTERS", ["intern", "internship", "entry level", "junior", "new grad", "graduate"])
if isinstance(LEVEL_FILTERS, str):
    LEVEL_FILTERS = [x.strip() for x in LEVEL_FILTERS.split(",") if x.strip()]

PREFER_REMOTE = str(_get("PREFER_REMOTE", "true")).lower() == "true"

PREFERRED_LOCATIONS = _get("PREFERRED_LOCATIONS", [])
if isinstance(PREFERRED_LOCATIONS, str):
    PREFERRED_LOCATIONS = [x.strip() for x in PREFERRED_LOCATIONS.split(",") if x.strip()]


# -----------------------------------------------------------------------
# ELIGIBILITY FILTERS
# -----------------------------------------------------------------------
def passes_level_filter(job: dict, level_filters: list = None) -> bool:
    """Pass if: any level keyword is found in the combined title and description.
    If no level filters are configured, all jobs pass.
    """
    filters = LEVEL_FILTERS if level_filters is None else level_filters
    if isinstance(filters, str):
        filters = [x.strip() for x in filters.split(",") if x.strip()]
    if not filters:
        return True
    blob = f"{job.get('title', '')} {job.get('description', '')}".lower()
    return any(str(lvl).lower() in blob for lvl in filters)


def passes_location_filter(
    job: dict,
    prefer_remote: bool = None,
    preferred_locations: list = None,
) -> bool:
    """Pass if: remote preferred and job is remote, or location in preferred list."""
    pref_remote = PREFER_REMOTE if prefer_remote is None else prefer_remote
    pref_locs = PREFERRED_LOCATIONS if preferred_locations is None else preferred_locations
    if isinstance(pref_locs, str):
        pref_locs = [x.strip() for x in pref_locs.split(",") if x.strip()]

    if not pref_remote and not pref_locs:
        return True
    loc = (job.get("location") or "").lower()
    if pref_remote and ("remote" in loc or not loc):
        return True
    if pref_locs:
        return any(pl.lower() in loc for pl in pref_locs)
    return pref_remote and not loc
