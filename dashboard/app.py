"""
A-Jent (Autonomous Job Exploration and Navigation Tool) Dashboard Server
---------------------
Serves the local web dashboard at http://localhost:8765
Reads seen_jobs.json and log/cycle_stats.json — read-only, never modifies agent state.

Usage:
    python dashboard/app.py

Then open http://localhost:8765 in your browser.
"""
import json
import sys
import os
import hmac
import hashlib
import uuid
import calendar
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, send_from_directory, request, redirect, Response, stream_with_context

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
SEEN_JOBS_FILE = BASE_DIR / "seen_jobs.json"
CYCLE_STATS_FILE = BASE_DIR / "log" / "cycle_stats.json"
LOG_FILE = BASE_DIR / "log" / "agent.log"
APPLIED_JOBS_FILE = BASE_DIR / "applied_jobs.json"
SUBSCRIPTIONS_FILE = BASE_DIR / "subscriptions.json"
DASHBOARD_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

ALLOWED_RESUME_EXTS = {".pdf", ".docx", ".doc"}

# ── Cashfree / Subscription config ───────────────────────────────────────────
def _load_yaml_cfg() -> dict:
    cfg_file = BASE_DIR / "config.yaml"
    if not cfg_file.exists():
        return {}
    try:
        import yaml
        with open(cfg_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

_cfg = _load_yaml_cfg()

def _gcfg(key, default):
    return os.environ.get(key.upper(), _cfg.get(key.lower(), default))

CASHFREE_APP_ID     = _gcfg("cashfree_app_id", "")
CASHFREE_SECRET     = _gcfg("cashfree_secret_key", "")
CASHFREE_ENV        = _gcfg("cashfree_env", "test")   # "test" or "prod"
SUBSCRIPTION_AMT    = int(_gcfg("subscription_amount", 75))
SUBSCRIPTION_REQ    = str(_gcfg("subscription_required", "true")).lower() == "true"

# Cashfree base URLs
_CF_BASE = (
    "https://sandbox.cashfree.com/pg"
    if CASHFREE_ENV == "test"
    else "https://api.cashfree.com/pg"
)
_CF_JS = (
    "https://sdk.cashfree.com/js/v3/cashfree.js"
    if CASHFREE_ENV == "test"
    else "https://sdk.cashfree.com/js/v3/cashfree.js"
)

app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="")

import requests as _requests   # for Cashfree API calls

import sys
sys.path.insert(0, str(BASE_DIR))
import db


# ── Backfill existing subscribers into users.json on startup ─────────────────

def _backfill_subscribers():
    """Sync any active subscriptions.json subscribers into users.json.

    This ensures subscribers who paid before the sync logic existed (or who
    subscribed before registering an account) are picked up by the agent
    immediately on the next cycle.
    """
    import hashlib as _hl
    if not SUBSCRIPTIONS_FILE.exists():
        return
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            subs = json.load(f)
    except Exception:
        return

    now = datetime.now(timezone.utc)
    users = db.load_users()

    for sub in subs.get("subscribers", []):
        if sub.get("status") != "active":
            continue
        email = (sub.get("email") or "").strip().lower()
        if not email:
            continue
        # Skip if already in users.json with active status
        existing = users.get(email, {})
        if existing.get("subscription_status") == "active":
            continue
        user_id = existing.get("user_id") or f"usr_{_hl.md5(email.encode()).hexdigest()[:12]}"
        plan = sub.get("plan", "monthly")
        user_doc = {
            **existing,
            "user_id": user_id,
            "email": email,
            "name": sub.get("name") or existing.get("name") or email.split("@")[0],
            "subscription_status": "active",
            "plan": plan,
            "subscribed_at": sub.get("subscribed_at", now.isoformat()),
        }
        if sub.get("order_id"):
            user_doc["order_id"] = sub["order_id"]
        if sub.get("payment_id"):
            user_doc["payment_id"] = sub["payment_id"]
        if "created_at" not in user_doc:
            user_doc["created_at"] = now.isoformat()
        db.save_user(user_doc)

_backfill_subscribers()


# -- Helpers ------------------------------------------------------------------

def load_seen(user_id: str = None) -> dict:
    return db.load_seen(user_id=user_id)


def load_cycle_stats() -> list:
    return db.load_cycle_stats()


def tail_log(n: int = 200) -> list:
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return []


def find_resume():
    """Return info about the current resume file, or None."""
    for ext in ALLOWED_RESUME_EXTS:
        path = BASE_DIR / f"resume{ext}"
        if path.exists():
            stat = path.stat()
            return {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "path": str(path),
            }
    return None


# -- Subscription helpers ------------------------------------------------------

def load_subscriptions() -> dict:
    if not SUBSCRIPTIONS_FILE.exists():
        return {"subscribers": []}
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"subscribers": []}


def save_subscriptions(data: dict):
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_active_subscriber() -> dict | None:
    """Return the most recent active subscriber record, or None."""
    if not SUBSCRIPTION_REQ:
        return {"email": "dev-bypass", "status": "active", "plan": "dev"}
    data = load_subscriptions()
    now = datetime.now(timezone.utc)
    for sub in reversed(data.get("subscribers", [])):
        if sub.get("status") != "active":
            continue
        # Check monthly expiry: subscribed_at + 31 days
        try:
            sub_date = datetime.fromisoformat(sub["subscribed_at"])
            if now - sub_date <= timedelta(days=31):
                return sub
        except Exception:
            return sub  # if date parsing fails, treat as valid
    return None


def _cf_headers() -> dict:
    return {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET,
        "x-api-version": "2023-08-01",
        "Content-Type": "application/json",
    }



# -- Authentication API Routes ------------------------------------------------

SESSION_MAX_AGE = 86400 * 30


def _request_user_id():
    return (
        request.cookies.get("a_jent_user_id")
        or request.cookies.get("jent_user_id")
        or request.headers.get("X-User-Id")
        or request.args.get("user_id")
    )


def _find_session_user():
    uid = _request_user_id()
    if not uid:
        return None
    users = db.load_users()
    return next((user for user in users.values() if user.get("user_id") == uid), None)


def _public_user(user: dict) -> dict:
    return {
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "plan": user.get("plan", ""),
        "subscription_status": user.get("subscription_status", ""),
    }


def _set_session_cookie(response, user_id: str):
    response.set_cookie(
        "a_jent_user_id",
        user_id,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
        path="/",
    )
    return response


@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    body = request.get_json(force=True) or {}
    email    = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()
    name     = (body.get("name") or "").strip()
    
    if not email or "@" not in email:
        return jsonify({"error": "Valid email address required"}), 400
    if not password or len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400

    user = db.create_user(email, password, name)
    if not user:
        return jsonify({"error": "Email is already registered. Please login instead."}), 400

    res = jsonify({"success": True, "authenticated": True, "user": _public_user(user)})
    return _set_session_cookie(res, user["user_id"])


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    body = request.get_json(force=True) or {}
    email    = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    user = db.authenticate_user(email, password)
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401

    res = jsonify({"success": True, "authenticated": True, "user": _public_user(user)})
    return _set_session_cookie(res, user["user_id"])


@app.route("/api/auth/me")
def api_auth_me():
    user = _find_session_user()
    if not user:
        return jsonify({"authenticated": False, "user": None, "error": "Authentication required."}), 401
    profile = db.get_user_profile(user["user_id"])
    return jsonify({"authenticated": True, "user": _public_user(user), "profile": profile})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    response = jsonify({"success": True, "authenticated": False})
    response.delete_cookie("a_jent_user_id", path="/")
    response.delete_cookie("jent_user_id", path="/")
    return response


# -- Auth middleware -----------------------------------------------------------

from functools import wraps

def require_auth(f):
    """Decorator: reject requests with no valid a_jent_user_id / jent_user_id cookie/header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        uid = _request_user_id()
        if not uid:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        if not _find_session_user():
            return jsonify({"error": "Invalid session. Please log in again."}), 401
        return f(*args, **kwargs)
    return decorated


# -- API Routes ---------------------------------------------------------------

def _get_current_user_id():
    return _request_user_id() or db.DEFAULT_USER_ID

@app.route("/api/jobs")
@require_auth
def api_jobs():
    uid = _get_current_user_id()
    seen = load_seen(user_id=uid)
    jobs = []
    for jid, info in seen.items():
        if not isinstance(info, dict) or not info.get("title"):
            continue
        jobs.append({
            "id": jid,
            "title": info.get("title", ""),
            "company": info.get("company", ""),
            "url": info.get("url", ""),
            "source": info.get("source", ""),
            "location": info.get("location", ""),
            "score": info.get("score", 0),
            "found_at": info.get("found_at", ""),
        })
    jobs.sort(key=lambda j: (j["score"], j["found_at"]), reverse=True)

    min_score = float(request.args.get("min_score", 0))
    source_filter = request.args.get("source", "").strip().lower()
    if min_score > 0:
        jobs = [j for j in jobs if j["score"] >= min_score]
    if source_filter:
        jobs = [j for j in jobs if source_filter in j["source"].lower()]

    return jsonify({"jobs": jobs, "total": len(jobs)})


@app.route("/api/stats")
@require_auth
def api_stats():
    uid = _get_current_user_id()
    seen = load_seen(user_id=uid)
    cycles = load_cycle_stats()

    total_seen = len(seen)
    total_matches = sum(
        1 for info in seen.values()
        if isinstance(info, dict) and info.get("score", 0) > 0 and info.get("title")
    )
    source_counts = {}
    for info in seen.values():
        if not isinstance(info, dict) or not info.get("source"):
            continue
        src = info["source"]
        source_counts[src] = source_counts.get(src, 0) + 1

    applied_count = len(db.load_applied(user_id=uid))

    return jsonify({
        "total_seen": total_seen,
        "total_matches": total_matches,
        "total_applied": applied_count,
        "last_cycle": cycles[-1] if cycles else None,
        "source_breakdown": source_counts,
        "recent_cycles": cycles[-20:] if cycles else [],
    })


@app.route("/api/log")
@require_auth
def api_log():
    n = int(request.args.get("n", 150))
    return jsonify({"lines": tail_log(n)})


@app.route("/api/log/stream")
@require_auth
def api_log_stream():
    """Server-Sent Events stream for live log tailing."""
    def generate():
        last_size = 0
        last_line_count = 0
        # Send initial backlog (last 80 lines)
        initial = tail_log(80)
        for line in initial:
            yield f"data: {json.dumps({'line': line, 'initial': True})}\n\n"
        last_line_count = sum(1 for _ in open(LOG_FILE, 'r', encoding='utf-8', errors='replace')) if LOG_FILE.exists() else 0
        # Stream new lines as they appear
        while True:
            time.sleep(1.5)
            if not LOG_FILE.exists():
                continue
            try:
                with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                current_count = len(lines)
                if current_count > last_line_count:
                    new_lines = lines[last_line_count:]
                    for line in new_lines:
                        yield f"data: {json.dumps({'line': line.rstrip(), 'initial': False})}\n\n"
                    last_line_count = current_count
            except Exception:
                pass
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route("/api/subscribe-email", methods=["POST"])
def api_subscribe_email():
    """Save a free email subscription for notifications (no payment required)."""
    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()
    name  = (body.get("name") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    subs = load_subscriptions()
    # Check if already registered
    for sub in subs.get("subscribers", []):
        if sub.get("email", "").lower() == email and sub.get("status") == "active":
            return jsonify({"success": True, "message": "Already registered", "email": email})
    # Mark old active subs as superseded
    for sub in subs.get("subscribers", []):
        if sub.get("status") == "active" and sub.get("plan") == "notify":
            sub["status"] = "superseded"
    subs.setdefault("subscribers", []).append({
        "email": email,
        "name": name,
        "subscribed_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "plan": "notify",
        "order_id": None,
        "payment_id": None,
        "amount": 0,
    })
    save_subscriptions(subs)

    # ── Sync into users.json so the agent emails this subscriber ──────────────
    import hashlib as _hl
    users = db.load_users()
    existing = users.get(email, {})
    user_id = existing.get("user_id") or f"usr_{_hl.md5(email.encode()).hexdigest()[:12]}"
    user_doc = {
        **existing,
        "user_id": user_id,
        "email": email,
        "name": name or existing.get("name") or email.split("@")[0],
        "subscription_status": "active",
        "plan": "notify",
    }
    if "created_at" not in user_doc:
        user_doc["created_at"] = datetime.now(timezone.utc).isoformat()
    db.save_user(user_doc)

    return jsonify({"success": True, "message": f"Email {email} registered for notifications", "email": email})


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "dashboard_version": "4.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seen_jobs_exists": SEEN_JOBS_FILE.exists(),
        "log_exists": LOG_FILE.exists(),
        "mongodb_connected": db.is_mongodb_connected(),
    })


# -- Subscription API Routes --------------------------------------------------

@app.route("/api/subscription-status")
def api_subscription_status():
    user = _find_session_user()
    if not user:
        return jsonify({
            "authenticated": False,
            "active": False,
            "amount": SUBSCRIPTION_AMT,
            "subscription_required": SUBSCRIPTION_REQ,
            "message": "Log in to view your personalized subscription.",
        })

    status = user.get("subscription_status", "inactive")
    plan = user.get("plan", "trial")
    subscribed_at_str = user.get("subscribed_at") or user.get("created_at")
    expires_at_str = user.get("subscription_expires_at")

    now = datetime.now(timezone.utc)
    days_left = 0
    if expires_at_str:
        try:
            exp_date = datetime.fromisoformat(expires_at_str)
            days_left = max(0, (exp_date - now).days)
        except Exception:
            days_left = 7
    elif subscribed_at_str:
        try:
            duration = 31 if plan == "monthly" else 7
            sub_date = datetime.fromisoformat(subscribed_at_str)
            exp_date = sub_date + timedelta(days=duration)
            days_left = max(0, (exp_date - now).days)
        except Exception:
            days_left = 7

    if not SUBSCRIPTION_REQ:
        is_active = True
    elif status in ("active", "trial", "dev"):
        if days_left > 0 or (expires_at_str and datetime.fromisoformat(expires_at_str) > now):
            is_active = True
        else:
            is_active = False
            user["subscription_status"] = "expired"
            db.save_user(user)
            status = "expired"
    else:
        is_active = False

    return jsonify({
        "authenticated": True,
        "user_id": user.get("user_id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "active": is_active,
        "status": status,
        "subscription_status": status,
        "plan": plan,
        "subscribed_at": subscribed_at_str,
        "subscription_expires_at": expires_at_str,
        "days_left": days_left,
        "amount": SUBSCRIPTION_AMT,
        "subscription_required": SUBSCRIPTION_REQ,
    })


@app.route("/api/create-order", methods=["POST"])
def api_create_order():
    """Create a Cashfree order or simulated activation for the authenticated session user."""
    user = _find_session_user()
    if not user:
        return jsonify({"error": "Authentication required. Please log in first."}), 401

    customer_name = (user.get("name") or "").strip() or user["email"].split("@")[0]
    customer_email = user["email"].strip().lower()
    user_id = user["user_id"]

    order_id = f"a_jent_{user_id}_{uuid.uuid4().hex[:6]}"

    # If Cashfree credentials are missing or placeholder, provide a seamless simulated activation for testing
    if not CASHFREE_APP_ID or not CASHFREE_SECRET or "YOUR_CASHFREE" in CASHFREE_APP_ID:
        _activate_subscription(
            email=customer_email,
            name=customer_name,
            order_id=order_id,
            payment_id=f"sim_{uuid.uuid4().hex[:8]}",
            amount=SUBSCRIPTION_AMT,
            user_id=user_id,
        )
        return jsonify({
            "success": True,
            "simulated": True,
            "message": f"Personalized subscription activated for {customer_email}!",
            "order_id": order_id,
        })

    body = request.get_json(force=True) or {}
    customer_phone = (body.get("phone") or "").strip() or "9999999999"
    return_url = request.host_url.rstrip("/") + f"/api/payment-success?order_id={order_id}&email={customer_email}"

    payload = {
        "order_id": order_id,
        "order_amount": SUBSCRIPTION_AMT,
        "order_currency": "INR",
        "order_note": f"A-Jent Monthly Subscription for {customer_email}",
        "customer_details": {
            "customer_id": f"a_jent_{user_id}",
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
        },
        "order_meta": {
            "return_url": return_url,
            "notify_url": request.host_url.rstrip("/") + "/api/payment-webhook",
        },
    }

    try:
        resp = _requests.post(
            f"{_CF_BASE}/orders",
            json=payload,
            headers=_cf_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return jsonify({
            "order_id": order_id,
            "payment_session_id": data.get("payment_session_id", ""),
            "cf_js": _CF_JS,
            "env": CASHFREE_ENV,
        })
    except Exception as e:
        return jsonify({"error": f"Cashfree order creation failed: {e}"}), 500


@app.route("/api/payment-success")
def api_payment_success():
    """Cashfree redirects here after payment. Verify and activate subscription."""
    order_id = request.args.get("order_id", "")
    email    = request.args.get("email", "")

    activated = False
    if order_id and CASHFREE_APP_ID:
        try:
            resp = _requests.get(
                f"{_CF_BASE}/orders/{order_id}",
                headers=_cf_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            order_data = resp.json()
            status = order_data.get("order_status", "")
            if status == "PAID":
                payments = order_data.get("order_payment_details", {})
                payment_id = str(payments.get("payment_id", order_id))
                _activate_subscription(
                    email=email,
                    name=order_data.get("customer_details", {}).get("customer_name", ""),
                    order_id=order_id,
                    payment_id=payment_id,
                    amount=SUBSCRIPTION_AMT,
                )
                activated = True
        except Exception:
            pass

    # Redirect back to dashboard with status param
    return redirect(f"/?sub={'success' if activated else 'pending'}")


@app.route("/api/verify-payment", methods=["POST"])
def api_verify_payment():
    """Frontend calls this to verify an order and activate subscription."""
    body = request.get_json(force=True) or {}
    order_id = body.get("order_id", "")
    email    = body.get("email", "")

    if not order_id:
        return jsonify({"error": "order_id required"}), 400

    try:
        resp = _requests.get(
            f"{_CF_BASE}/orders/{order_id}",
            headers=_cf_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        order_data = resp.json()
        status = order_data.get("order_status", "")

        if status == "PAID":
            payments = order_data.get("order_payment_details", {})
            payment_id = str(payments.get("payment_id", order_id))
            customer  = order_data.get("customer_details", {})
            _activate_subscription(
                email=email or customer.get("customer_email", ""),
                name=customer.get("customer_name", ""),
                order_id=order_id,
                payment_id=payment_id,
                amount=SUBSCRIPTION_AMT,
            )
            return jsonify({"success": True, "status": status})
        return jsonify({"success": False, "status": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/payment-webhook", methods=["POST"])
def api_payment_webhook():
    """Cashfree server-to-server payment notification."""
    try:
        data = request.get_json(force=True) or {}
        order = data.get("data", {}).get("order", {})
        payment = data.get("data", {}).get("payment", {})
        if payment.get("payment_status") == "SUCCESS":
            order_id   = order.get("order_id", "")
            payment_id = payment.get("cf_payment_id", order_id)
            customer   = data.get("data", {}).get("customer_details", {})
            _activate_subscription(
                email=customer.get("customer_email", ""),
                name=customer.get("customer_name", ""),
                order_id=order_id,
                payment_id=str(payment_id),
                amount=SUBSCRIPTION_AMT,
            )
    except Exception:
        pass
    return jsonify({"status": "ok"})


def _activate_subscription(email, name, order_id, payment_id, amount, user_id=None):
    """Write subscriber record to subscriptions.json and sync into users.json with personalized 31-day expiry."""
    subs = load_subscriptions()
    email_clean = (email or "").strip().lower()
    now = datetime.now(timezone.utc)
    for s in subs.get("subscribers", []):
        if s.get("email", "").lower() == email_clean and s.get("status") == "active":
            s["status"] = "expired"
    subs.setdefault("subscribers", []).append({
        "email": email_clean,
        "name": name,
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": amount,
        "subscribed_at": now.isoformat(),
        "status": "active",
        "plan": "monthly",
    })
    save_subscriptions(subs)

    # ── Sync into users.json with personalized 31-day expiry ──────────────────
    import hashlib as _hl
    users = db.load_users()
    existing = users.get(email_clean, {})
    uid = user_id or existing.get("user_id") or f"usr_{_hl.md5(email_clean.encode()).hexdigest()[:12]}"
    user_doc = {
        **existing,
        "user_id": uid,
        "email": email_clean,
        "name": name or existing.get("name") or email_clean.split("@")[0],
        "subscription_status": "active",
        "plan": "monthly",
        "subscribed_at": now.isoformat(),
        "subscription_expires_at": (now + timedelta(days=31)).isoformat(),
        "order_id": order_id,
        "payment_id": payment_id,
    }
    if "created_at" not in user_doc:
        user_doc["created_at"] = now.isoformat()
    db.save_user(user_doc)
    return user_doc



def _extract_resume_text(path) -> str:
    """Extract plain text from a PDF or DOCX resume file."""
    ext = str(path).lower().rsplit(".", 1)[-1]
    try:
        if ext == "pdf":
            import pdfplumber
            parts = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    parts.append(page.extract_text() or "")
            return "\n".join(parts)
        elif ext in ("docx", "doc"):
            import docx as _docx
            d = _docx.Document(str(path))
            return "\n".join(p.text for p in d.paragraphs)
    except Exception as e:
        app.logger.warning(f"[Resume] Could not parse {path}: {e}")
    return ""


def _sync_primary_resume_to_base_dir(primary_resume: dict):
    """Ensure the primary resume file is placed at BASE_DIR / resume{ext} for system-wide fallback and auto-apply."""
    if not primary_resume:
        return
    file_path = primary_resume.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return
    ext = Path(file_path).suffix.lower()
    if ext not in ALLOWED_RESUME_EXTS:
        ext = ".pdf"
    for old_ext in ALLOWED_RESUME_EXTS:
        old_p = BASE_DIR / f"resume{old_ext}"
        if old_p.exists():
            try:
                old_p.unlink()
            except Exception:
                pass
    dest_p = BASE_DIR / f"resume{ext}"
    try:
        import shutil
        shutil.copyfile(file_path, str(dest_p))
    except Exception as e:
        app.logger.warning(f"Could not copy primary resume to base dir: {e}")


def _ensure_user_resumes(user: dict) -> list:
    """Ensure user has a 'resumes' list and a primary resume. Backfills existing resume if needed."""
    if not user:
        return []
    resumes = user.get("resumes")
    if resumes is None:
        resumes = []
        user["resumes"] = resumes

    # Backward compatibility: if user has existing resume_text or resume_filename but empty resumes
    if not resumes and (user.get("resume_text") or user.get("resume_filename")):
        fn = user.get("resume_filename") or "resume.pdf"
        fpath = BASE_DIR / fn
        if not fpath.exists():
            for ext in ALLOWED_RESUME_EXTS:
                candidate = BASE_DIR / f"resume{ext}"
                if candidate.exists():
                    fpath = candidate
                    fn = candidate.name
                    break
        size_bytes = fpath.stat().st_size if fpath.exists() else len((user.get("resume_text") or "").encode("utf-8"))
        res_id = f"res_{uuid.uuid4().hex[:8]}"
        initial_entry = {
            "id": res_id,
            "filename": fn,
            "size_bytes": size_bytes,
            "size_kb": round(size_bytes / 1024, 1),
            "uploaded_at": user.get("resume_updated_at") or user.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "resume_text": user.get("resume_text", ""),
            "is_primary": True,
            "file_path": str(fpath) if fpath.exists() else "",
        }
        resumes.append(initial_entry)
        user["primary_resume_id"] = res_id
        db.save_user(user)

    # Ensure strictly one resume is primary
    if resumes:
        primary_count = sum(1 for r in resumes if r.get("is_primary"))
        if primary_count == 0:
            resumes[0]["is_primary"] = True
            user["primary_resume_id"] = resumes[0]["id"]
            user["resume_filename"] = resumes[0]["filename"]
            user["resume_text"] = resumes[0].get("resume_text", "")
            user["resume_updated_at"] = resumes[0].get("uploaded_at") or datetime.now(timezone.utc).isoformat()
            db.save_user(user)
        elif primary_count > 1:
            primary_id = user.get("primary_resume_id")
            found = False
            for r in resumes:
                if not found and (r.get("id") == primary_id or primary_id is None):
                    r["is_primary"] = True
                    found = True
                else:
                    r["is_primary"] = False
            db.save_user(user)

    return resumes


@app.route("/api/resume-status")
def api_resume_status():
    user = _find_session_user()
    if user:
        resumes = _ensure_user_resumes(user)
        primary = next((r for r in resumes if r.get("is_primary")), None)
        
        primary_info = None
        if primary:
            primary_info = {
                "id": primary["id"],
                "filename": primary["filename"],
                "size_bytes": primary.get("size_bytes", 0),
                "size_kb": primary.get("size_kb", 0),
                "modified": primary.get("uploaded_at"),
                "chars_extracted": len(primary.get("resume_text", "")),
                "is_primary": True,
            }
        
        resumes_summary = [
            {
                "id": r["id"],
                "filename": r["filename"],
                "size_bytes": r.get("size_bytes", 0),
                "size_kb": r.get("size_kb", 0),
                "uploaded_at": r.get("uploaded_at"),
                "is_primary": bool(r.get("is_primary")),
                "chars_extracted": len(r.get("resume_text", "")),
            }
            for r in resumes
        ]

        return jsonify({
            "authenticated": True,
            "resume": primary_info,
            "has_resume": primary_info is not None,
            "resumes": resumes_summary,
            "primary_resume_id": primary.get("id") if primary else None,
            "primary_resume_filename": primary.get("filename") if primary else None,
        })
    else:
        # Fallback for unauthenticated or default user
        info = find_resume()
        resumes_summary = []
        if info:
            resumes_summary = [{
                "id": "res_default",
                "filename": info["filename"],
                "size_bytes": info.get("size_bytes", 0),
                "size_kb": info.get("size_kb", 0),
                "uploaded_at": info.get("modified"),
                "is_primary": True,
                "chars_extracted": 0,
            }]
        return jsonify({
            "authenticated": False,
            "resume": info,
            "has_resume": info is not None,
            "resumes": resumes_summary,
            "primary_resume_id": "res_default" if info else None,
            "primary_resume_filename": info["filename"] if info else None,
        })


@app.route("/api/upload-resume", methods=["POST"])
@require_auth
def api_upload_resume():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    orig_filename = Path(f.filename).name
    ext = Path(orig_filename).suffix.lower()
    if ext not in ALLOWED_RESUME_EXTS:
        return jsonify({"error": f"Unsupported file type '{ext}'. Use PDF or DOCX."}), 400

    uid = _get_current_user_id()
    user = _find_session_user()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    res_id = f"res_{uuid.uuid4().hex[:8]}"
    user_resumes_dir = BASE_DIR / "uploads" / "resumes" / uid
    user_resumes_dir.mkdir(parents=True, exist_ok=True)

    saved_file_path = user_resumes_dir / f"{res_id}_{orig_filename}"
    f.save(str(saved_file_path))
    stat = saved_file_path.stat()

    resume_text = _extract_resume_text(saved_file_path)

    _ensure_user_resumes(user)
    resumes = user.get("resumes", [])

    # Mark all other resumes as non-primary
    for r in resumes:
        r["is_primary"] = False

    new_resume = {
        "id": res_id,
        "filename": orig_filename,
        "size_bytes": stat.st_size,
        "size_kb": round(stat.st_size / 1024, 1),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "resume_text": resume_text,
        "is_primary": True,
        "file_path": str(saved_file_path),
    }
    # Prepend new resume to list so latest is on top
    resumes.insert(0, new_resume)
    user["resumes"] = resumes
    user["primary_resume_id"] = res_id
    user["resume_filename"] = orig_filename
    user["resume_text"] = resume_text
    user["resume_updated_at"] = new_resume["uploaded_at"]

    # Sync to BASE_DIR / resume{ext} for system-wide fallbacks and auto-apply
    _sync_primary_resume_to_base_dir(new_resume)

    db.save_user(user)

    # Log to agent.log
    log_msg = f"[Primary Resume] User {user.get('email')} uploaded '{orig_filename}' and set it as Primary Resume. Agent will use this as source of truth."
    app.logger.info(log_msg)
    try:
        if LOG_FILE.exists():
            with open(LOG_FILE, "a", encoding="utf-8") as lf:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                lf.write(f"[{now_str}] [INFO] {log_msg}\n")
    except Exception:
        pass

    return jsonify({
        "success": True,
        "filename": orig_filename,
        "size_kb": round(stat.st_size / 1024, 1),
        "chars_extracted": len(resume_text),
        "message": f"Resume uploaded and set as Primary Resume. The AI Agent will use '{orig_filename}' for all job matching and actions.",
        "resume_id": res_id,
        "is_primary": True,
    })


@app.route("/api/set-primary-resume", methods=["POST"])
@require_auth
def api_set_primary_resume():
    user = _find_session_user()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    body = request.get_json(force=True) or {}
    target_id = (body.get("resume_id") or "").strip()
    target_filename = (body.get("filename") or "").strip()

    if not target_id and not target_filename:
        return jsonify({"error": "resume_id or filename is required."}), 400

    _ensure_user_resumes(user)
    resumes = user.get("resumes", [])
    if not resumes:
        return jsonify({"error": "No uploaded resumes found."}), 404

    target = None
    if target_id:
        target = next((r for r in resumes if r.get("id") == target_id), None)
    if not target and target_filename:
        target = next((r for r in resumes if r.get("filename") == target_filename), None)

    if not target:
        return jsonify({"error": "Specified resume not found."}), 404

    # Ensure strictly one resume is primary
    for r in resumes:
        r["is_primary"] = (r.get("id") == target["id"])

    user["primary_resume_id"] = target["id"]
    user["resume_filename"] = target["filename"]
    user["resume_text"] = target.get("resume_text", "")
    user["resume_updated_at"] = datetime.now(timezone.utc).isoformat()

    _sync_primary_resume_to_base_dir(target)
    db.save_user(user)

    log_msg = f"[Primary Resume] Switched primary resume to '{target['filename']}' for {user.get('email')}. Agent will use this resume as source of truth for all matching & actions."
    app.logger.info(log_msg)
    try:
        if LOG_FILE.exists():
            with open(LOG_FILE, "a", encoding="utf-8") as lf:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                lf.write(f"[{now_str}] [INFO] {log_msg}\n")
    except Exception:
        pass

    return jsonify({
        "success": True,
        "message": f"Primary resume updated to '{target['filename']}'. The AI Agent will use this resume as its source of truth.",
        "primary_resume_id": target["id"],
        "primary_resume_filename": target["filename"],
    })


@app.route("/api/delete-resume", methods=["POST"])
@require_auth
def api_delete_resume():
    user = _find_session_user()
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    body = request.get_json(force=True) or {}
    target_id = (body.get("resume_id") or "").strip()
    if not target_id:
        return jsonify({"error": "resume_id required."}), 400

    _ensure_user_resumes(user)
    resumes = user.get("resumes", [])
    target = next((r for r in resumes if r.get("id") == target_id), None)
    if not target:
        return jsonify({"error": "Resume not found."}), 404

    was_primary = target.get("is_primary", False)
    user["resumes"] = [r for r in resumes if r.get("id") != target_id]

    fp = target.get("file_path")
    if fp and os.path.exists(fp):
        try:
            os.remove(fp)
        except Exception:
            pass

    if was_primary:
        if user["resumes"]:
            new_primary = user["resumes"][0]
            new_primary["is_primary"] = True
            user["primary_resume_id"] = new_primary["id"]
            user["resume_filename"] = new_primary["filename"]
            user["resume_text"] = new_primary.get("resume_text", "")
            user["resume_updated_at"] = datetime.now(timezone.utc).isoformat()
            _sync_primary_resume_to_base_dir(new_primary)
        else:
            user["primary_resume_id"] = None
            user["resume_filename"] = None
            user["resume_text"] = ""
            for ext in ALLOWED_RESUME_EXTS:
                old_p = BASE_DIR / f"resume{ext}"
                if old_p.exists():
                    try:
                        old_p.unlink()
                    except Exception:
                        pass

    db.save_user(user)

    log_msg = f"[Primary Resume] User {user.get('email')} removed resume '{target['filename']}'."
    app.logger.info(log_msg)

    return jsonify({
        "success": True,
        "message": f"Resume '{target['filename']}' deleted.",
        "primary_resume_id": user.get("primary_resume_id"),
        "primary_resume_filename": user.get("resume_filename"),
    })



@app.route("/api/applied-jobs")
@require_auth
def api_applied_jobs():
    try:
        uid = _get_current_user_id()
        data = db.load_applied(user_id=uid)
        jobs = [{"id": jid, **info} for jid, info in data.items()]
        jobs.sort(key=lambda j: j.get("applied_at", ""), reverse=True)
        in_progress = sum(1 for j in jobs if j.get("status") == "in_progress")
        submitted = sum(1 for j in jobs if j.get("status") == "submitted")
        return jsonify({
            "jobs": jobs,
            "total": len(jobs),
            "in_progress": in_progress,
            "submitted": submitted,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory(str(DASHBOARD_DIR), "index.html")


# -- Main ---------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8765))
    print(f"\n  A-Jent (Autonomous Job Exploration and Navigation Tool) Dashboard running at http://localhost:{port}")
    print(f"  Reading data from: {BASE_DIR}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
