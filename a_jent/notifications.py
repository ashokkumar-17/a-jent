"""
Notification Delivery Module
----------------------------
Extracted from job_search_agent.py (Task 7).

Responsible for:
- Email formatting (HTML and plain text)
- Primary dispatch channels:
    - SendGrid API (preferred, no rate limits on paid plan)
    - Gmail SMTP (free fallback)
    - Zapier Catch Hook (catch-all fallback)
- Additive supplemental channels:
    - Telegram Bot API
    - Discord Webhook
- Dry-run handling and delivery logging
"""

import os
import sys
import logging
import smtplib
from pathlib import Path
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

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
        print(f"[WARN] Could not load config.yaml in notifications: {e}")
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
        print(f"[WARN] Could not load .env in notifications: {e}")


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


# --- Delivery Configuration Constants ---
ZAPIER_WEBHOOK_URL = _get("ZAPIER_WEBHOOK_URL", "PASTE_YOUR_ZAPIER_CATCH_HOOK_URL_HERE")
GMAIL_ADDRESS = _get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = _get("GMAIL_APP_PASSWORD", "")
GMAIL_TO_ADDRESS = _get("GMAIL_TO_ADDRESS", "") or GMAIL_ADDRESS
FORCE_DIRECT_GMAIL = str(_get("FORCE_DIRECT_GMAIL", "false")).lower() == "true"
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = _get("DISCORD_WEBHOOK_URL", "")
SENDGRID_API_KEY = _get("SENDGRID_API_KEY", "")

_DRY_RUN = "--dry-run" in sys.argv

# Dedicated HTTP Session for notifications
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; job-search-agent/3.0)"})


# -----------------------------------------------------------------------
# NOTIFICATION FORMATTING
# -----------------------------------------------------------------------
_SCORE_COLORS = [
    (0.40, "#22c55e"),   # green  — excellent
    (0.25, "#f59e0b"),   # amber  — good
    (0.12, "#6366f1"),   # indigo — decent
    (0.00, "#94a3b8"),   # slate  — low
]


def _score_color(score: float) -> str:
    for threshold, color in _SCORE_COLORS:
        if score >= threshold:
            return color
    return "#94a3b8"


def _score_bar(score: float) -> str:
    pct = int(min(score * 250, 100))  # scale 0-0.4 → 0-100%
    return "█" * (pct // 10) + "░" * (10 - pct // 10)


def build_html_email(job: dict) -> str:
    score = job.get("score", 0)
    color = _score_color(score)
    bar = _score_bar(score)
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    source = job.get("source", "")
    url = job.get("url", "#")
    location = job.get("location", "") or "Not specified"
    found_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 0; }}
  .card {{ max-width: 600px; margin: 32px auto; background: #1e293b; border-radius: 16px; overflow: hidden; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
  .header {{ background: linear-gradient(135deg, #1d4ed8, #7c3aed); padding: 28px 32px; }}
  .header h1 {{ margin: 0 0 4px 0; font-size: 22px; color: #fff; }}
  .header p {{ margin: 0; color: #bfdbfe; font-size: 14px; }}
  .body {{ padding: 28px 32px; }}
  .score-badge {{ display: inline-block; background: {color}22; border: 1px solid {color}; color: {color}; padding: 4px 14px; border-radius: 99px; font-size: 13px; font-weight: 600; margin-bottom: 18px; }}
  .field {{ margin-bottom: 12px; }}
  .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: #64748b; margin-bottom: 3px; }}
  .value {{ font-size: 15px; color: #f1f5f9; }}
  .bar {{ font-family: monospace; color: {color}; letter-spacing: 2px; }}
  .apply-btn {{ display: block; text-align: center; margin: 28px 0 0; padding: 14px; background: linear-gradient(90deg, #1d4ed8, #7c3aed); color: #fff; text-decoration: none; border-radius: 10px; font-size: 16px; font-weight: 700; letter-spacing: .03em; }}
  .footer {{ padding: 16px 32px; background: #0f172a; font-size: 11px; color: #475569; text-align: center; }}
</style></head>
<body>
<div class="card">
  <div class="header">
    <h1>🎯 New Job Match Found</h1>
    <p>A-Jent (Autonomous Job Exploration and Navigation Tool) · {found_at}</p>
  </div>
  <div class="body">
    <div class="score-badge">Match Score: {score:.1%}</div>
    <div class="field"><div class="label">Position</div><div class="value" style="font-size:19px;font-weight:700;">{title}</div></div>
    <div class="field"><div class="label">Company</div><div class="value">{company}</div></div>
    <div class="field"><div class="label">Location</div><div class="value">{location}</div></div>
    <div class="field"><div class="label">Source</div><div class="value">{source}</div></div>
    <div class="field"><div class="label">Match Strength</div><div class="bar">{bar}</div></div>
    <a href="{url}" class="apply-btn">Apply Now →</a>
  </div>
  <div class="footer">A-Jent v3 · Autonomous Job Exploration and Navigation Tool · This match was found by your local job search agent</div>
</div>
</body>
</html>"""


# -----------------------------------------------------------------------
# NOTIFICATION DISPATCH CHANNELS
# -----------------------------------------------------------------------
def send_to_zapier(job: dict, webhook_url: str = None) -> bool:
    url = webhook_url if webhook_url is not None else ZAPIER_WEBHOOK_URL
    if not url or "PASTE_YOUR" in url:
        return False
    payload = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "url": job.get("url", ""),
        "location": job.get("location", ""),
        "source": job.get("source", ""),
        "match_score": job.get("score", 0),
        "found_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = _SESSION.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info(f"[OK] Zapier: {job.get('score', 0):.2f}  {job.get('title', '')} @ {job.get('company', '')}")
        return True
    except Exception as e:
        log.warning(f"Zapier send failed: {e}")
        return False


def send_via_sendgrid(
    job: dict,
    to_address: str = None,
    api_key: str = None,
    from_address: str = None,
) -> bool:
    """Send job match email via SendGrid API (no daily cap on paid plan).
    Falls back silently if SENDGRID_API_KEY is not set.
    """
    key = api_key if api_key is not None else SENDGRID_API_KEY
    if not key:
        return False
    to = (to_address or GMAIL_TO_ADDRESS or "").strip()
    if not to:
        return False
    from_email = (from_address if from_address is not None else GMAIL_ADDRESS) or "noreply@a-jent.ai"
    score = job.get("score", 0)
    subject = f"Job Match ({score:.0%}): {job.get('title', '')} @ {job.get('company', '')}"
    html_body = build_html_email(job)
    plain_body = (
        f"New job match!\n\nTitle:    {job.get('title', '')}\n"
        f"Company:  {job.get('company', '')}\nLocation: {job.get('location', '')}\n"
        f"Score:    {score:.3f}\nLink:     {job.get('url', '')}\n"
    )
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_body},
            {"type": "text/html",  "value": html_body},
        ],
    }
    try:
        resp = _SESSION.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        log.info(f"[OK] SendGrid → {to}: {score:.2f}  {job.get('title', '')} @ {job.get('company', '')}")
        return True
    except Exception as e:
        log.warning(f"SendGrid send failed: {e}")
        return False


def send_via_gmail(
    job: dict,
    to_address: str = None,
    gmail_address: str = None,
    app_password: str = None,
) -> bool:
    sender = gmail_address if gmail_address is not None else GMAIL_ADDRESS
    password = app_password if app_password is not None else GMAIL_APP_PASSWORD
    to = (to_address or GMAIL_TO_ADDRESS or "").strip()
    if not sender or not password or not to:
        return False

    score = job.get("score", 0)
    subject = f"Job Match ({score:.0%}): {job.get('title', '')} @ {job.get('company', '')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    # Plain-text fallback
    plain = (
        f"New job match!\n\n"
        f"Title:    {job.get('title', '')}\n"
        f"Company:  {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Source:   {job.get('source', '')}\n"
        f"Score:    {score:.3f}\n"
        f"Link:     {job.get('url', '')}\n"
        f"Found at: {datetime.now(timezone.utc).isoformat()}\n"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(build_html_email(job), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.sendmail(sender, [to], msg.as_string())
        log.info(f"[OK] Gmail → {to}: {score:.2f}  {job.get('title', '')} @ {job.get('company', '')}")
        return True
    except Exception as e:
        log.warning(f"Gmail send failed: {e}")
        return False


def send_via_telegram(
    job: dict,
    bot_token: str = None,
    chat_id: str = None,
) -> bool:
    token = bot_token if bot_token is not None else TELEGRAM_BOT_TOKEN
    chat = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
    if not token or not chat:
        return False
    score = job.get("score", 0)
    text = (
        f"🎯 *New Job Match* ({score:.0%})\n\n"
        f"*{job.get('title', '')}*\n"
        f"🏢 {job.get('company', '')}\n"
        f"📍 {job.get('location', '') or 'Remote'}\n"
        f"📡 {job.get('source', '')}\n\n"
        f"[Apply Now]({job.get('url', '')})"
    )
    try:
        resp = _SESSION.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
        resp.raise_for_status()
        log.info(f"[OK] Telegram: {job.get('title', '')}")
        return True
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")
        return False


def send_via_discord(
    job: dict,
    webhook_url: str = None,
) -> bool:
    url = webhook_url if webhook_url is not None else DISCORD_WEBHOOK_URL
    if not url:
        return False
    score = job.get("score", 0)
    color = int(_score_color(score).lstrip("#"), 16)
    embed = {
        "title": f"🎯 {job.get('title', '')}",
        "url": job.get("url", ""),
        "color": color,
        "fields": [
            {"name": "Company", "value": job.get("company", "—"), "inline": True},
            {"name": "Location", "value": job.get("location", "") or "Remote", "inline": True},
            {"name": "Source", "value": job.get("source", ""), "inline": True},
            {"name": "Match Score", "value": f"{score:.1%}", "inline": True},
        ],
        "footer": {"text": "A-Jent (Autonomous Job Exploration and Navigation Tool)"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = _SESSION.post(url, json={"embeds": [embed]}, timeout=15)
        resp.raise_for_status()
        log.info(f"[OK] Discord: {job.get('title', '')}")
        return True
    except Exception as e:
        log.warning(f"Discord send failed: {e}")
        return False


# -----------------------------------------------------------------------
# UNIFIED NOTIFY ENTRY POINT
# -----------------------------------------------------------------------
def notify(
    job: dict,
    to_email: str = None,
    dry_run: bool = None,
    force_direct_gmail: bool = None,
    sendgrid_api_key: str = None,
    gmail_address: str = None,
    gmail_app_password: str = None,
    zapier_webhook_url: str = None,
    telegram_bot_token: str = None,
    telegram_chat_id: str = None,
    discord_webhook_url: str = None,
) -> bool:
    """
    Delivery priority:
      SendGrid (if key set) → Gmail → Zapier → Telegram → Discord → dry-run print
    Telegram and Discord always fire alongside the primary channel (additive).
    SendGrid has no daily cap on paid plans; Gmail is the free fallback.

    If to_email is provided, email is sent to that address (per-subscriber delivery).
    Returns True if primary delivery succeeded (or was forced), False otherwise.
    """
    is_dry_run = _DRY_RUN if dry_run is None else dry_run
    score = job.get("score", 0)
    title = job.get("title", "")
    company = job.get("company", "")

    if is_dry_run:
        log.info(f"[DRY RUN] {score:.2f}  {title} @ {company}")
        return False

    is_force_gmail = FORCE_DIRECT_GMAIL if force_direct_gmail is None else force_direct_gmail
    tg_token = TELEGRAM_BOT_TOKEN if telegram_bot_token is None else telegram_bot_token
    tg_chat = TELEGRAM_CHAT_ID if telegram_chat_id is None else telegram_chat_id
    dc_url = DISCORD_WEBHOOK_URL if discord_webhook_url is None else discord_webhook_url

    sent = False
    if is_force_gmail:
        sent = send_via_gmail(
            job,
            to_address=to_email,
            gmail_address=gmail_address,
            app_password=gmail_app_password,
        )
    else:
        # Try SendGrid first (no send limits), fall back to Gmail, then Zapier
        sent = (
            send_via_sendgrid(
                job,
                to_address=to_email,
                api_key=sendgrid_api_key,
                from_address=gmail_address,
            )
            or send_via_gmail(
                job,
                to_address=to_email,
                gmail_address=gmail_address,
                app_password=gmail_app_password,
            )
            or send_to_zapier(
                job,
                webhook_url=zapier_webhook_url,
            )
        )

    # Always also fire supplemental channels
    send_via_telegram(job, bot_token=tg_token, chat_id=tg_chat)
    send_via_discord(job, webhook_url=dc_url)

    if not sent and not tg_token and not dc_url:
        log.info(
            f"[NO DELIVERY CONFIGURED] {score:.2f}  {title} @ {company} — "
            f"set GMAIL_ADDRESS/GMAIL_APP_PASSWORD, TELEGRAM_BOT_TOKEN, or DISCORD_WEBHOOK_URL"
        )

    return sent
