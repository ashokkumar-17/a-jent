"""
Job Sources Discovery & Fetching Module
---------------------------------------
Extracted from job_search_agent.py (Task 6).

Responsible for:
- HTTP source fetching with requests.Session
- Source-specific response parsing (JSON, HTML, RSS)
- Source-specific normalization into standard job dictionaries:
    - id
    - title
    - company
    - url
    - location
    - description
    - source
    - posted_at
- Source aggregation across all platforms
- Playwright-based browser-source coordination (Internshala, Indeed, Unstop)
"""

import os
import sys
import re
import json
import logging
import urllib.parse
from pathlib import Path

import requests
import feedparser

log = logging.getLogger("agent")

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
        print(f"[WARN] Could not load config.yaml in job_sources: {e}")
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
        print(f"[WARN] Could not load .env in job_sources: {e}")


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


# --- Configuration constants for sources ---
GREENHOUSE_COMPANY_SLUGS = _get("GREENHOUSE_COMPANY_SLUGS", [])
if isinstance(GREENHOUSE_COMPANY_SLUGS, str):
    GREENHOUSE_COMPANY_SLUGS = [x.strip() for x in GREENHOUSE_COMPANY_SLUGS.split(",") if x.strip()]

LEVER_COMPANY_SLUGS = _get("LEVER_COMPANY_SLUGS", [])
if isinstance(LEVER_COMPANY_SLUGS, str):
    LEVER_COMPANY_SLUGS = [x.strip() for x in LEVER_COMPANY_SLUGS.split(",") if x.strip()]

BROWSER_ENABLED = str(_get("BROWSER_ENABLED", "false")).lower() == "true"
BROWSER_HEADLESS = str(_get("BROWSER_HEADLESS", "true")).lower() == "true"
INDEED_QUERY = str(_get("INDEED_QUERY", "software engineer intern"))
INDEED_LOCATION = str(_get("INDEED_LOCATION", "India"))
UNSTOP_INCLUDE_HACKATHONS = str(_get("UNSTOP_INCLUDE_HACKATHONS", "true")).lower() == "true"

WWR_RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]


# -----------------------------------------------------------------------
# HTTP SESSION & HELPERS
# -----------------------------------------------------------------------
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; job-search-agent/3.0)"})


def _safe_get(url: str, timeout: int = 15, **kwargs):
    """GET with error logging; returns Response or None."""
    try:
        r = _SESSION.get(url, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"GET {url} failed: {e}")
        return None


# -----------------------------------------------------------------------
# SOURCE FETCHERS
# -----------------------------------------------------------------------
def fetch_remoteok() -> list:
    jobs = []
    r = _safe_get("https://remoteok.com/api")
    if not r:
        return jobs
    for item in r.json():
        if not isinstance(item, dict) or "id" not in item:
            continue
        jobs.append({
            "id": f"remoteok_{item.get('id')}",
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "url": item.get("url", ""),
            "location": "Remote",
            "description": (item.get("description") or "")[:3000],
            "source": "RemoteOK",
            "posted_at": item.get("date", ""),
        })
    return jobs


def fetch_arbeitnow() -> list:
    jobs = []
    r = _safe_get("https://www.arbeitnow.com/api/job-board-api")
    if not r:
        return jobs
    for item in r.json().get("data", []):
        jobs.append({
            "id": f"arbeitnow_{item.get('slug')}",
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "url": item.get("url", ""),
            "location": item.get("location", ""),
            "description": (item.get("description") or "")[:3000],
            "source": "Arbeitnow",
            "posted_at": item.get("created_at", ""),
        })
    return jobs


def fetch_jobicy() -> list:
    jobs = []
    r = _safe_get("https://jobicy.com/api/v2/remote-jobs")
    if not r:
        return jobs
    for item in r.json().get("jobs", []):
        jobs.append({
            "id": f"jobicy_{item.get('id')}",
            "title": item.get("jobTitle", ""),
            "company": item.get("companyName", ""),
            "url": item.get("url", ""),
            "location": item.get("jobGeo", "Remote"),
            "description": (item.get("jobExcerpt") or item.get("jobDescription") or "")[:3000],
            "source": "Jobicy",
            "posted_at": item.get("pubDate", ""),
        })
    return jobs


def fetch_himalayas() -> list:
    jobs = []
    r = _safe_get("https://himalayas.app/jobs/api")
    if not r:
        return jobs
    data = r.json()
    listings = data.get("jobs", data) if isinstance(data, dict) else data
    for item in listings:
        jobs.append({
            "id": f"himalayas_{item.get('guid', item.get('id'))}",
            "title": item.get("title", ""),
            "company": item.get("companyName", ""),
            "url": item.get("applicationLink", item.get("url", "")),
            "location": item.get("location", "Remote"),
            "description": (item.get("description") or "")[:3000],
            "source": "Himalayas",
            "posted_at": item.get("pubDate", ""),
        })
    return jobs


def fetch_remotive() -> list:
    """Remotive — popular remote-first board with category filtering."""
    jobs = []
    r = _safe_get("https://remotive.com/api/remote-jobs")
    if not r:
        return jobs
    for item in r.json().get("jobs", []):
        jobs.append({
            "id": f"remotive_{item.get('id')}",
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "url": item.get("url", ""),
            "location": item.get("candidate_required_location", "Remote"),
            "description": re.sub(r"<[^<]+?>", " ", item.get("description") or "")[:3000],
            "source": "Remotive",
            "posted_at": item.get("publication_date", ""),
        })
    return jobs


def fetch_hn_whoishiring() -> list:
    jobs = []
    r = _safe_get(
        "https://hn.algolia.com/api/v1/search_by_date"
        "?tags=story,author_whoishiring&query=Who%20is%20hiring"
    )
    if not r:
        return jobs
    hits = r.json().get("hits", [])
    if not hits:
        return jobs
    story_id = hits[0]["objectID"]
    r2 = _safe_get(f"https://hn.algolia.com/api/v1/items/{story_id}")
    if not r2:
        return jobs
    for c in r2.json().get("children", []):
        text = c.get("text") or ""
        if not text:
            continue
        clean = re.sub(r"<[^<]+?>", " ", text).strip()
        jobs.append({
            "id": f"hn_{c.get('id')}",
            "title": clean.split("\n")[0][:200],
            "company": "(see post)",
            "url": f"https://news.ycombinator.com/item?id={c.get('id')}",
            "location": "",
            "description": clean[:3000],
            "source": "HN Who's Hiring",
            "posted_at": "",
        })
    return jobs


def fetch_wwr_rss(feed_urls: list = None) -> list:
    jobs = []
    urls = feed_urls if feed_urls is not None else WWR_RSS_FEEDS
    for feed_url in urls:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                jobs.append({
                    "id": f"wwr_{entry.get('id', entry.get('link'))}",
                    "title": entry.get("title", ""),
                    "company": "",
                    "url": entry.get("link", ""),
                    "location": "Remote",
                    "description": entry.get("summary", "")[:3000],
                    "source": "We Work Remotely",
                    "posted_at": "",
                })
        except Exception as e:
            log.warning(f"WWR RSS fetch failed for {feed_url}: {e}")
    return jobs


def fetch_linkedin_rss() -> list:
    """
    LinkedIn public job RSS — no login required.
    Format: https://www.linkedin.com/jobs/search/?keywords=<q>&location=<loc>&f_TPR=r86400&f_JT=I
    Returns an RSS feed parseable by feedparser.
    f_TPR=r86400  = posted in last 24 h
    f_JT=I        = Internship job type
    """
    jobs = []
    queries = [
        ("software engineer intern", "India"),
        ("data science intern", "India"),
        ("developer internship", "India"),
        ("machine learning intern", "India"),
    ]
    seen_ids: set = set()
    for q, loc in queries:
        params = urllib.parse.urlencode({
            "keywords": q,
            "location": loc,
            "f_TPR": "r604800",   # last 7 days
            "f_JT": "I",           # Internship type
            "position": 1,
            "pageNum": 0,
        })
        rss_endpoint = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{params}&start=0"
        try:
            r = _safe_get(
                rss_endpoint,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Referer": "https://www.linkedin.com/",
                }
            )
            if not r:
                continue
            html = r.text
            # Extract job card data from LinkedIn's public guest API response
            ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:([0-9]+)"', html)
            titles   = re.findall(r'class="base-search-card__title"[^>]*>\s*([^<]+)\s*<', html)
            companies = re.findall(r'class="base-search-card__subtitle"[^>]*>\s*<[^>]+>\s*([^<]+)\s*<', html)
            locations = re.findall(r'class="job-search-card__location"[^>]*>\s*([^<]+)\s*<', html)
            for i, jid in enumerate(ids):
                uid = f"linkedin_{jid}"
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                title = titles[i].strip() if i < len(titles) else f"Internship ({jid})"
                company = companies[i].strip() if i < len(companies) else ""
                location = locations[i].strip() if i < len(locations) else "India"
                jobs.append({
                    "id": uid,
                    "title": title,
                    "company": company,
                    "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                    "location": location,
                    "description": f"{title} at {company}. Location: {location}. Found via LinkedIn India.",
                    "source": "LinkedIn",
                    "posted_at": "",
                })
            log.debug(f"[LinkedIn] {q!r}: {len(ids)} listings")
        except Exception as e:
            log.debug(f"[LinkedIn] RSS error for {q!r}: {e}")
    return jobs


def fetch_greenhouse(slugs: list) -> list:
    jobs = []
    for slug in slugs:
        r = _safe_get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not r:
            continue
        for item in r.json().get("jobs", []):
            jobs.append({
                "id": f"greenhouse_{item.get('id')}",
                "title": item.get("title", ""),
                "company": slug,
                "url": item.get("absolute_url", ""),
                "location": item.get("location", {}).get("name", ""),
                "description": re.sub(r"<[^<]+?>", " ", item.get("content") or "")[:3000],
                "source": f"Greenhouse ({slug})",
                "posted_at": item.get("updated_at", ""),
            })
    return jobs


def fetch_lever(slugs: list) -> list:
    jobs = []
    for slug in slugs:
        r = _safe_get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not r:
            continue
        for item in r.json():
            jobs.append({
                "id": f"lever_{item.get('id')}",
                "title": item.get("text", ""),
                "company": slug,
                "url": item.get("hostedUrl", ""),
                "location": item.get("categories", {}).get("location", ""),
                "description": re.sub(
                    r"<[^<]+?>", " ",
                    item.get("descriptionPlain") or item.get("description") or ""
                )[:3000],
                "source": f"Lever ({slug})",
                "posted_at": "",
            })
    return jobs


def fetch_browser_sources(
    enabled: bool = None,
    headless: bool = None,
    indeed_query: str = None,
    indeed_location: str = None,
    unstop_hackathons: bool = None,
) -> tuple:
    """
    Run Playwright-based scrapers for Internshala, Indeed, and Unstop.
    Only runs if BROWSER_ENABLED=true in config.yaml or environment.
    Returns (jobs_list, source_counts_dict).
    """
    jobs = []
    source_counts = {}

    is_enabled = BROWSER_ENABLED if enabled is None else enabled
    if not is_enabled:
        return jobs, source_counts

    is_headless = BROWSER_HEADLESS if headless is None else headless
    query = INDEED_QUERY if indeed_query is None else indeed_query
    location = INDEED_LOCATION if indeed_location is None else indeed_location
    hackathons = UNSTOP_INCLUDE_HACKATHONS if unstop_hackathons is None else unstop_hackathons

    try:
        from scrapers.browser_base import check_playwright
        if not check_playwright():
            log.warning(
                "[Browser] playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
            return jobs, source_counts
    except ImportError:
        log.warning("[Browser] scrapers package not found.")
        return jobs, source_counts

    # --- Internshala ---
    try:
        from scrapers.internshala import fetch_internshala
        log.info("[Browser] Fetching Internshala...")
        fetched = fetch_internshala(headless=is_headless)
        source_counts["Internshala"] = len(fetched)
        jobs += fetched
        log.info(f"  Internshala: {len(fetched)} listings")
    except Exception as e:
        log.warning(f"[Browser] Internshala scraper failed: {e}")

    # --- Indeed ---
    try:
        from scrapers.indeed import fetch_indeed
        log.info(f"[Browser] Fetching Indeed ({query!r} in {location!r})...")
        fetched = fetch_indeed(
            query=query,
            location=location,
            headless=is_headless,
        )
        source_counts["Indeed"] = len(fetched)
        jobs += fetched
        log.info(f"  Indeed: {len(fetched)} listings")
    except Exception as e:
        log.warning(f"[Browser] Indeed scraper failed: {e}")

    # --- Unstop ---
    try:
        from scrapers.unstop import fetch_unstop
        log.info("[Browser] Fetching Unstop...")
        fetched = fetch_unstop(
            include_hackathons=hackathons,
            headless=is_headless,
        )
        source_counts["Unstop"] = len(fetched)
        jobs += fetched
        log.info(f"  Unstop: {len(fetched)} listings")
    except Exception as e:
        log.warning(f"[Browser] Unstop scraper failed: {e}")

    return jobs, source_counts


def fetch_all_sources(
    greenhouse_slugs: list = None,
    lever_slugs: list = None,
    browser_enabled: bool = None,
    browser_headless: bool = None,
    indeed_query: str = None,
    indeed_location: str = None,
    unstop_include_hackathons: bool = None,
) -> tuple[list, dict]:
    """
    Fetch from all enabled HTTP APIs, RSS feeds, and browser scrapers.
    Returns (all_jobs, source_counts).
    """
    sources = [
        ("RemoteOK", fetch_remoteok),
        ("Arbeitnow", fetch_arbeitnow),
        ("Jobicy", fetch_jobicy),
        ("Himalayas", fetch_himalayas),
        ("Remotive", fetch_remotive),
        ("HN Who's Hiring", fetch_hn_whoishiring),
        ("We Work Remotely", fetch_wwr_rss),
        ("LinkedIn", fetch_linkedin_rss),
    ]
    jobs = []
    source_counts = {}
    for name, fn in sources:
        fetched = fn()
        source_counts[name] = len(fetched)
        jobs += fetched
        log.info(f"  {name}: {len(fetched)} listings")

    gh_slugs = GREENHOUSE_COMPANY_SLUGS if greenhouse_slugs is None else greenhouse_slugs
    if gh_slugs:
        fetched = fetch_greenhouse(gh_slugs)
        source_counts["Greenhouse"] = len(fetched)
        jobs += fetched

    l_slugs = LEVER_COMPANY_SLUGS if lever_slugs is None else lever_slugs
    if l_slugs:
        fetched = fetch_lever(l_slugs)
        source_counts["Lever"] = len(fetched)
        jobs += fetched

    # Browser-based scrapers (Internshala, Indeed, Unstop)
    b_enabled = BROWSER_ENABLED if browser_enabled is None else browser_enabled
    if b_enabled:
        b_jobs, b_counts = fetch_browser_sources(
            enabled=b_enabled,
            headless=browser_headless,
            indeed_query=indeed_query,
            indeed_location=indeed_location,
            unstop_hackathons=unstop_include_hackathons,
        )
        jobs += b_jobs
        source_counts.update(b_counts)

    return jobs, source_counts
