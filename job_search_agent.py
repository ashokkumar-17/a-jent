"""
A-Jent (Autonomous Job Exploration and Navigation Tool) - v3
-------------------------------------------------------------
Runs 24/7 as a local daemon. No API keys required. Ranks jobs against your
resume using local TF-IDF + cosine similarity (scikit-learn) — the "AI"
layer — fully offline. Sends new matches via Zapier webhook, direct Gmail
SMTP, Telegram bot, or Discord webhook.

SOURCES (all free, no auth, no login):
  - RemoteOK                     https://remoteok.com/api
  - Arbeitnow Job Board          https://www.arbeitnow.com/api/job-board-api
  - Jobicy                       https://jobicy.com/api/v2/remote-jobs
  - Himalayas                    https://himalayas.app/jobs/api
  - Remotive                     https://remotive.com/api/remote-jobs
  - Hacker News "Who's Hiring"   via Algolia HN Search API
  - We Work Remotely RSS feeds
  - Greenhouse / Lever           public per-company job boards (opt-in list)

SETUP
  1. pip install -r requirements.txt
  2. Edit config.yaml (or set env vars - env vars always win)
  3. Drop resume.pdf or resume.docx in this folder
  4. Test:      python job_search_agent.py --once --dry-run
  5. Run once:  python job_search_agent.py --once
  6. Run 24/7:  python job_search_agent.py
"""

import os
import re
import sys
import json
import time
import math
import signal
import logging
import smtplib
import requests
import feedparser
from pathlib import Path
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import db
from a_jent import job_sources
from a_jent import notifications
from a_jent import job_matcher
from a_jent import resume_parser
from a_jent import job_filter

# -----------------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------------
BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = BASE_DIR / "config.yaml"
SEEN_JOBS_FILE = BASE_DIR / "seen_jobs.json"
LOG_DIR = BASE_DIR / "log"
LOG_FILE = LOG_DIR / "agent.log"
CYCLE_STATS_FILE = LOG_DIR / "cycle_stats.json"


# -----------------------------------------------------------------------
# CONFIG — load config.yaml first, then env vars override
# -----------------------------------------------------------------------
def _load_yaml_config() -> dict:
    """Load config.yaml if present; silently return empty dict if not."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[WARN] Could not load config.yaml: {e}")
        return {}


# -----------------------------------------------------------------------
# .env FILE LOADER (stdlib only — no python-dotenv needed)
# Loads .env before config.yaml so credentials stay out of the repo.
# -----------------------------------------------------------------------
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
                if key and key not in os.environ:  # env vars still win
                    os.environ[key] = val
    except Exception as e:
        print(f"[WARN] Could not load .env: {e}")


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


# --- Delivery (Extracted to notifications.py - Task 7) ---
ZAPIER_WEBHOOK_URL = notifications.ZAPIER_WEBHOOK_URL
GMAIL_ADDRESS = notifications.GMAIL_ADDRESS
GMAIL_APP_PASSWORD = notifications.GMAIL_APP_PASSWORD
GMAIL_TO_ADDRESS = notifications.GMAIL_TO_ADDRESS
FORCE_DIRECT_GMAIL = notifications.FORCE_DIRECT_GMAIL
TELEGRAM_BOT_TOKEN = notifications.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = notifications.TELEGRAM_CHAT_ID
DISCORD_WEBHOOK_URL = notifications.DISCORD_WEBHOOK_URL
SENDGRID_API_KEY = notifications.SENDGRID_API_KEY

# --- Matching (Extracted to job_matcher.py - Task 8) ---
RESUME_PATH = resume_parser.RESUME_PATH
SIMILARITY_THRESHOLD = job_matcher.SIMILARITY_THRESHOLD
TITLE_BOOST_MULTIPLIER = job_matcher.TITLE_BOOST_MULTIPLIER
LEVEL_FILTERS = job_filter.LEVEL_FILTERS

# --- Scheduling ---
CHECK_INTERVAL_HOURS = _get("CHECK_INTERVAL_HOURS", 2.0, float)

# --- Location (Extracted to job_filter.py - Task 10) ---
PREFER_REMOTE = job_filter.PREFER_REMOTE
PREFERRED_LOCATIONS = job_filter.PREFERRED_LOCATIONS

# --- Company watchlists ---
GREENHOUSE_COMPANY_SLUGS = _get("GREENHOUSE_COMPANY_SLUGS", [])
if isinstance(GREENHOUSE_COMPANY_SLUGS, str):
    GREENHOUSE_COMPANY_SLUGS = [x.strip() for x in GREENHOUSE_COMPANY_SLUGS.split(",") if x.strip()]
LEVER_COMPANY_SLUGS = _get("LEVER_COMPANY_SLUGS", [])
if isinstance(LEVER_COMPANY_SLUGS, str):
    LEVER_COMPANY_SLUGS = [x.strip() for x in LEVER_COMPANY_SLUGS.split(",") if x.strip()]

# --- Browser scrapers (Internshala / Indeed / Unstop) ---
BROWSER_ENABLED = str(_get("BROWSER_ENABLED", "false")).lower() == "true"
BROWSER_HEADLESS = str(_get("BROWSER_HEADLESS", "true")).lower() == "true"
INDEED_QUERY = str(_get("INDEED_QUERY", "software engineer intern"))
INDEED_LOCATION = str(_get("INDEED_LOCATION", "India"))
UNSTOP_INCLUDE_HACKATHONS = str(_get("UNSTOP_INCLUDE_HACKATHONS", "true")).lower() == "true"

# --- Auto-Apply ---
AUTO_APPLY_ENABLED = str(_get("AUTO_APPLY_ENABLED", "false")).lower() == "true"
AUTO_APPLY_THRESHOLD = _get("AUTO_APPLY_THRESHOLD", 0.25, float)
AUTO_APPLY_PLATFORMS = _get("AUTO_APPLY_PLATFORMS", ["internshala", "indeed", "unstop"])
if isinstance(AUTO_APPLY_PLATFORMS, str):
    AUTO_APPLY_PLATFORMS = [x.strip() for x in AUTO_APPLY_PLATFORMS.split(",") if x.strip()]
COVER_LETTER_TEMPLATE = str(_get(
    "COVER_LETTER_TEMPLATE",
    "Hi, I am a {level} student with strong skills in {top_skills}. "
    "I am very interested in the {title} role at {company} and believe my background "
    "makes me a strong candidate. Please find my resume attached. "
    "Looking forward to hearing from you!"
))

# --- Subscription ---
SUBSCRIPTION_REQUIRED = str(_get("SUBSCRIPTION_REQUIRED", "true")).lower() == "true"
SUBSCRIPTIONS_FILE = BASE_DIR / "subscriptions.json"

# --- Job feed URLs ---
WWR_RSS_FEEDS = job_sources.WWR_RSS_FEEDS

# --- Fallback Keyword Profile (Extracted to resume_parser.py - Task 9) ---
FALLBACK_KEYWORDS_TEXT = resume_parser.FALLBACK_KEYWORDS_TEXT

# -----------------------------------------------------------------------
# SYNONYM EXPANSION TABLE — Extracted to job_matcher.py (Task 8)
# -----------------------------------------------------------------------
SYNONYM_MAP = job_matcher.SYNONYM_MAP

# -----------------------------------------------------------------------
# SUBSCRIPTION GATE
# -----------------------------------------------------------------------
def check_subscription() -> bool:
    """
    Returns True if an active subscription is found in subscriptions.json,
    or if SUBSCRIPTION_REQUIRED is False (dev bypass).
    Logs a clear warning if subscription is missing/expired.
    """
    if not SUBSCRIPTION_REQUIRED:
        return True
    if not SUBSCRIPTIONS_FILE.exists():
        log.warning(
            "[Subscription] No subscription found. "
            "Visit http://localhost:8765 → 💳 Subscription tab to subscribe for ₹75/month. "
            "Notifications are paused until an active subscription exists."
        )
        return False
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        for sub in reversed(data.get("subscribers", [])):
            if sub.get("status") != "active":
                continue
            try:
                sub_date = datetime.fromisoformat(sub["subscribed_at"])
                if now - sub_date <= timedelta(days=31):
                    log.info(
                        f"[Subscription] Active — {sub.get('email', '')} "
                        f"(subscribed {sub_date.strftime('%Y-%m-%d')})"
                    )
                    return True
            except Exception:
                return True  # date parse failure → treat as valid
        # All records expired
        log.warning(
            "[Subscription] Subscription expired. "
            "Visit http://localhost:8765 → 💳 Subscription tab to renew for ₹75/month."
        )
        return False
    except Exception as e:
        log.warning(f"[Subscription] Could not read subscriptions.json: {e}")
        return False


# -----------------------------------------------------------------------
# SIGNAL HANDLING
# -----------------------------------------------------------------------
_RUNNING = True
_DRY_RUN = "--dry-run" in sys.argv


def _handle_stop(signum, frame):
    global _RUNNING
    print("\nStop signal received — finishing current cycle then exiting.")
    _RUNNING = False


try:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
except (ValueError, AttributeError):
    pass


# -----------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------
def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Rotating file handler — max 5 MB, keep 3 backups
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — force UTF-8 on Windows to avoid cp1252 errors
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)


setup_logging()
log = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# CYCLE STATS
# -----------------------------------------------------------------------
def load_cycle_stats() -> list:
    return db.load_cycle_stats()


def save_cycle_stats(stats: list):
    db.save_cycle_stats(stats)


# -----------------------------------------------------------------------
# RESUME TEXT EXTRACTION — Extracted to resume_parser.py (Task 9)
# -----------------------------------------------------------------------
extract_resume_text = resume_parser.extract_resume_text


def get_resume_text(resume_path: str = None) -> str:
    """Compatibility wrapper delegating to resume_parser.get_resume_text."""
    return resume_parser.get_resume_text(
        resume_path=resume_path if resume_path is not None else RESUME_PATH
    )


# -----------------------------------------------------------------------
# SYNONYM EXPANSION — Extracted to job_matcher.py (Task 8)
# -----------------------------------------------------------------------
expand_synonyms = job_matcher.expand_synonyms


# -----------------------------------------------------------------------
# SOURCE FETCHERS — Extracted to job_sources.py (Task 6)
# -----------------------------------------------------------------------
_SESSION = job_sources._SESSION
_safe_get = job_sources._safe_get
fetch_remoteok = job_sources.fetch_remoteok
fetch_arbeitnow = job_sources.fetch_arbeitnow
fetch_jobicy = job_sources.fetch_jobicy
fetch_himalayas = job_sources.fetch_himalayas
fetch_remotive = job_sources.fetch_remotive
fetch_hn_whoishiring = job_sources.fetch_hn_whoishiring
fetch_wwr_rss = job_sources.fetch_wwr_rss
fetch_linkedin_rss = job_sources.fetch_linkedin_rss
fetch_greenhouse = job_sources.fetch_greenhouse
fetch_lever = job_sources.fetch_lever
fetch_browser_sources = job_sources.fetch_browser_sources


def fetch_all_sources(
    greenhouse_slugs: list = None,
    lever_slugs: list = None,
    browser_enabled: bool = None,
    browser_headless: bool = None,
    indeed_query: str = None,
    indeed_location: str = None,
    unstop_include_hackathons: bool = None,
) -> tuple[list, dict]:
    """Compatibility wrapper delegating to job_sources.fetch_all_sources.

    Preserves existing runtime return value (jobs: list, source_counts: dict).
    """
    return job_sources.fetch_all_sources(
        greenhouse_slugs=greenhouse_slugs if greenhouse_slugs is not None else GREENHOUSE_COMPANY_SLUGS,
        lever_slugs=lever_slugs if lever_slugs is not None else LEVER_COMPANY_SLUGS,
        browser_enabled=browser_enabled if browser_enabled is not None else BROWSER_ENABLED,
        browser_headless=browser_headless if browser_headless is not None else BROWSER_HEADLESS,
        indeed_query=indeed_query if indeed_query is not None else INDEED_QUERY,
        indeed_location=indeed_location if indeed_location is not None else INDEED_LOCATION,
        unstop_include_hackathons=unstop_include_hackathons if unstop_include_hackathons is not None else UNSTOP_INCLUDE_HACKATHONS,
    )


# -----------------------------------------------------------------------
# LOCAL AI MATCHING — Extracted to job_matcher.py (Task 8)
# -----------------------------------------------------------------------
def rank_by_similarity(
    resume_text: str,
    jobs: list,
    similarity_threshold: float = None,
    title_boost_multiplier: float = None,
) -> list:
    """Compatibility wrapper delegating to job_matcher.rank_by_similarity."""
    return job_matcher.rank_by_similarity(
        resume_text=resume_text,
        jobs=jobs,
        similarity_threshold=similarity_threshold if similarity_threshold is not None else SIMILARITY_THRESHOLD,
        title_boost_multiplier=title_boost_multiplier if title_boost_multiplier is not None else TITLE_BOOST_MULTIPLIER,
    )


# -----------------------------------------------------------------------
# ELIGIBILITY FILTERS — Extracted to job_filter.py (Task 10)
# -----------------------------------------------------------------------
def passes_level_filter(job: dict, level_filters: list = None) -> bool:
    """Compatibility wrapper delegating to job_filter.passes_level_filter."""
    return job_filter.passes_level_filter(
        job=job,
        level_filters=level_filters if level_filters is not None else LEVEL_FILTERS,
    )


def passes_location_filter(
    job: dict,
    prefer_remote: bool = None,
    preferred_locations: list = None,
) -> bool:
    """Compatibility wrapper delegating to job_filter.passes_location_filter."""
    return job_filter.passes_location_filter(
        job=job,
        prefer_remote=prefer_remote if prefer_remote is None else PREFER_REMOTE,
        preferred_locations=preferred_locations if preferred_locations is not None else PREFERRED_LOCATIONS,
    )


# -----------------------------------------------------------------------
# DEDUPE STATE (augmented: stores score + timestamp)
# -----------------------------------------------------------------------
def load_seen(user_id: str = None) -> dict:
    return db.load_seen(user_id=user_id)


def save_seen(seen: dict, user_id: str = None):
    db.save_seen(seen, user_id=user_id)


# -----------------------------------------------------------------------
# NOTIFICATIONS — Extracted to notifications.py (Task 7)
# -----------------------------------------------------------------------
_SCORE_COLORS = notifications._SCORE_COLORS
_score_color = notifications._score_color
_score_bar = notifications._score_bar
build_html_email = notifications.build_html_email
send_to_zapier = notifications.send_to_zapier
send_via_sendgrid = notifications.send_via_sendgrid
send_via_gmail = notifications.send_via_gmail
send_via_telegram = notifications.send_via_telegram
send_via_discord = notifications.send_via_discord


def notify(job: dict, to_email: str = None, dry_run: bool = None) -> bool:
    """Compatibility wrapper delegating to notifications.notify.

    Preserves existing delivery order: SendGrid -> Gmail -> Zapier (plus Telegram and Discord).
    Respects _DRY_RUN unless explicitly overridden.
    """
    return notifications.notify(
        job=job,
        to_email=to_email,
        dry_run=_DRY_RUN if dry_run is None else dry_run,
        force_direct_gmail=FORCE_DIRECT_GMAIL,
        sendgrid_api_key=SENDGRID_API_KEY,
        gmail_address=GMAIL_ADDRESS,
        gmail_app_password=GMAIL_APP_PASSWORD,
        zapier_webhook_url=ZAPIER_WEBHOOK_URL,
        telegram_bot_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID,
        discord_webhook_url=DISCORD_WEBHOOK_URL,
    )


# -----------------------------------------------------------------------
# USER-SPECIFIC JOB EVALUATION & SEARCH (REUSABLE ORCHESTRATION BOUNDARY)
# -----------------------------------------------------------------------
def evaluate_jobs_for_user(
    sub: dict,
    all_jobs: list,
    source_counts: dict = None,
    dry_run: bool = None,
    global_resume_text: str = None,
) -> list:
    """Evaluate, rank, notify, and record seen jobs for a single user."""
    is_dry_run = _DRY_RUN if dry_run is None else dry_run
    uid = sub.get("user_id", "default_user")
    u_email = sub.get("email", "")
    log.info(f"[SaaS] Evaluating jobs for user: {u_email} ({uid})")

    user_seen = load_seen(user_id=uid)
    unseen = [j for j in all_jobs if j["id"] not in user_seen]
    level_ok = [j for j in unseen if passes_level_filter(j)]
    loc_ok = [j for j in level_ok if passes_location_filter(j)]

    # Resolve user's Primary Resume as the sole source of truth
    primary_resume_text = None
    for r in sub.get("resumes", []):
        if r.get("is_primary"):
            primary_resume_text = r.get("resume_text")
            break
    user_resume = primary_resume_text or sub.get("resume_text") or (global_resume_text if global_resume_text is not None else get_resume_text())
    primary_name = sub.get("resume_filename") or "primary resume"
    ranked = rank_by_similarity(user_resume, loc_ok)

    log.info(
        f"  [{u_email}] Source of truth: {primary_name} -> {len(unseen)} unseen -> {len(level_ok)} pass level -> "
        f"{len(loc_ok)} pass location -> {len(ranked)} matched"
    )

    for job in ranked:
        notify(job, to_email=u_email or None, dry_run=is_dry_run)

        if AUTO_APPLY_ENABLED and job.get("score", 0) >= AUTO_APPLY_THRESHOLD:
            try:
                from scrapers.auto_apply import auto_apply
                auto_apply(
                    job=job,
                    resume_text=user_resume,
                    cover_letter_template=COVER_LETTER_TEMPLATE,
                    enabled_platforms=AUTO_APPLY_PLATFORMS,
                    dry_run=is_dry_run,
                    user_id=uid,
                )
            except Exception as e:
                log.warning(f"[AutoApply] Error: {e}")

        if not is_dry_run:
            time.sleep(1)

    now_iso = datetime.now(timezone.utc).isoformat()
    if not is_dry_run:
        for job in all_jobs:
            if job["id"] not in user_seen:
                user_seen[job["id"]] = {
                    "score": job.get("score", 0),
                    "found_at": now_iso,
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "url": job.get("url", ""),
                    "source": job.get("source", ""),
                    "location": job.get("location", ""),
                }
        save_seen(user_seen, user_id=uid)

    # Save cycle stats
    stats = load_cycle_stats()
    stats.append({
        "timestamp": now_iso,
        "total_fetched": len(all_jobs),
        "unseen": len(unseen),
        "passed_level_filter": len(level_ok),
        "passed_location_filter": len(loc_ok),
        "new_matches": len(ranked),
        "sources": source_counts or {},
    })
    save_cycle_stats(stats)
    return ranked


def run_search_for_user(
    user: dict | str,
    all_jobs: list = None,
    source_counts: dict = None,
    dry_run: bool = None,
) -> list:
    """Execute a single job search cycle specifically for the given user.

    Reuses the existing job-search pipeline: fetches all sources, saves raw
    jobs to DB, and evaluates/matches/notifies for this user.
    """
    if isinstance(user, str):
        users = db.load_users()
        sub = next((u for u in users.values() if u.get("user_id") == user or u.get("email") == user), None)
        if not sub:
            sub = {"user_id": user, "email": user}
    else:
        uid = user.get("user_id")
        email = user.get("email")
        users = db.load_users()
        sub = next((u for u in users.values() if (uid and u.get("user_id") == uid) or (email and u.get("email") == email)), user)

    is_dry_run = _DRY_RUN if dry_run is None else dry_run
    cycle_start = datetime.now(timezone.utc)
    log.info("-" * 60)
    log.info(f"[Manual Trigger] User search start: {cycle_start.isoformat()} for {sub.get('email', '')} ({sub.get('user_id', '')})" + (" [DRY RUN]" if is_dry_run else ""))

    if all_jobs is None:
        log.info("Fetching all sources...")
        all_jobs, source_counts = fetch_all_sources()
        log.info(f"Fetched {len(all_jobs)} total listings across {len(source_counts)} sources.")
        db.save_raw_jobs(all_jobs)

    ranked = evaluate_jobs_for_user(
        sub,
        all_jobs,
        source_counts=source_counts,
        dry_run=is_dry_run,
    )
    log.info(f"[Manual Trigger] User search complete for {sub.get('email', '')}: {len(ranked)} matches found.\n")
    return ranked


# -----------------------------------------------------------------------
# ONE CYCLE (MULTI-TENANT SAAS AWARE)
# -----------------------------------------------------------------------
def run_once(target_user_id: str = None):
    if target_user_id:
        ranked = run_search_for_user(target_user_id)
        return len(ranked)

    cycle_start = datetime.now(timezone.utc)
    log.info("-" * 60)
    log.info(f"Cycle start: {cycle_start.isoformat()}" + (" [DRY RUN]" if _DRY_RUN else ""))

    global_resume_text = get_resume_text()

    log.info("Fetching all sources...")
    all_jobs, source_counts = fetch_all_sources()
    log.info(f"Fetched {len(all_jobs)} total listings across {len(source_counts)} sources.")
    db.save_raw_jobs(all_jobs)

    # Multi-tenant user loop
    subscribers = db.get_all_subscribers()
    log.info(f"[SaaS] Processing cycle for {len(subscribers)} active user(s)...")

    total_matches = 0

    for sub in subscribers:
        ranked = evaluate_jobs_for_user(
            sub,
            all_jobs,
            source_counts=source_counts,
            dry_run=_DRY_RUN,
            global_resume_text=global_resume_text,
        )
        total_matches += len(ranked)

    log.info(f"Cycle complete at {datetime.now().isoformat()}.\n")
    return total_matches


# -----------------------------------------------------------------------
# 24/7 LOOP
# -----------------------------------------------------------------------
def run_forever(interval_hours: float):
    log.info(f"Starting 24/7 loop — checking every {interval_hours}h. Ctrl+C to stop.")
    while _RUNNING:
        try:
            run_once()
        except Exception as e:
            log.error(f"Cycle failed, will retry next interval: {e}", exc_info=True)
        for _ in range(int(interval_hours * 3600)):
            if not _RUNNING:
                break
            time.sleep(1)
    log.info("Agent stopped.")


# -----------------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------------
if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    if _DRY_RUN:
        log.info("DRY RUN mode: no emails sent, seen_jobs.json not updated.")

    if "--once" in sys.argv:
        run_once()
    elif _DRY_RUN:
        # --dry-run without --once: do a single dry-run cycle and exit
        run_once()
    else:
        run_forever(CHECK_INTERVAL_HOURS)
