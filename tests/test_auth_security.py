"""
Automated Security and Authentication Tests for A-Jent Dashboard.

Covers:
1. Public route accessibility vs Protected route authentication enforcement.
2. Rejection of unauthenticated requests with 401 JSON responses on all protected endpoints.
3. Invalidation of authentication bypass vectors:
   - Supplying X-User-Id header must not authenticate the caller.
   - Supplying ?user_id= query parameter must not authenticate the caller.
   - Supplying raw a_jent_user_id / jent_user_id cookies must not authenticate the caller.
   - Supplying user_id in request body must not authenticate the caller.
4. Login creates a signed, secure session cookie.
5. Logout invalidates the session completely on the server.
6. CSRF protection on state-changing POST requests (with CSRF exemption for payment webhook).
7. User isolation: Authenticated User A cannot access User B's jobs/profile/subscription/resume.
"""

import os
import sys
import json
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
from dashboard.app import app, csrf


class TestAuthSecurity(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = True
        self.client = app.test_client()

        # Seed test users in db
        self.user1_email = "alice@example.com"
        self.user1_pass = "securePassword123"
        self.user1 = db.create_user(self.user1_email, self.user1_pass, name="Alice")
        if not self.user1:
            self.user1 = db.load_users()[self.user1_email]

        self.user2_email = "bob@example.com"
        self.user2_pass = "secretPassword456"
        self.user2 = db.create_user(self.user2_email, self.user2_pass, name="Bob")
        if not self.user2:
            self.user2 = db.load_users()[self.user2_email]

    def _get_csrf_token(self, client=None) -> str:
        """Helper to fetch a fresh valid CSRF token from /api/csrf-token."""
        c = client or self.client
        res = c.get("/api/csrf-token")
        data = json.loads(res.data.decode("utf-8"))
        return data["csrf_token"]

    def _login(self, client, email, password):
        """Helper to log in using a CSRF token."""
        token = self._get_csrf_token(client)
        return client.post(
            "/api/auth/login",
            data=json.dumps({"email": email, "password": password}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )

    # ── 1. Route Classification: Public vs Protected ─────────────────────────

    def test_public_routes_accessible_without_auth(self):
        """Verify public endpoints return 200 without authentication."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)

        res = self.client.get("/api/csrf-token")
        self.assertEqual(res.status_code, 200)

    def test_protected_routes_reject_unauthenticated(self):
        """Verify that all protected API routes return 401 when no session is present."""
        protected_endpoints = [
            ("GET", "/api/jobs"),
            ("GET", "/api/stats"),
            ("GET", "/api/log"),
            ("GET", "/api/applied-jobs"),
            ("GET", "/api/subscription-status"),
            ("GET", "/api/resume-status"),
            ("GET", "/api/search-status"),
            ("GET", "/api/auth/me"),
            ("POST", "/api/create-order"),
            ("POST", "/api/verify-payment"),
            ("POST", "/api/upload-resume"),
            ("POST", "/api/set-primary-resume"),
            ("POST", "/api/delete-resume"),
            ("POST", "/api/start-search"),
        ]

        token = self._get_csrf_token()
        headers = {"X-CSRFToken": token, "Content-Type": "application/json"}

        for method, endpoint in protected_endpoints:
            with self.subTest(method=method, endpoint=endpoint):
                if method == "GET":
                    res = self.client.get(endpoint, headers={"Accept": "application/json"})
                else:
                    res = self.client.post(endpoint, data=json.dumps({}), headers=headers)
                self.assertEqual(
                    res.status_code,
                    401,
                    f"Expected 401 for unauthenticated {method} {endpoint}, got {res.status_code}",
                )
                data = json.loads(res.data.decode("utf-8"))
                self.assertIn("error", data)

    # ── 2. Rejection of Authentication Bypass Vectors ────────────────────────

    def test_cannot_authenticate_via_x_user_id_header(self):
        """Supplying X-User-Id header must NEVER authenticate the request."""
        target_uid = self.user1["user_id"]
        res = self.client.get(
            "/api/jobs",
            headers={"X-User-Id": target_uid, "Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

        res = self.client.get(
            "/api/auth/me",
            headers={"X-User-Id": target_uid, "Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

        res = self.client.get(
            "/api/subscription-status",
            headers={"X-User-Id": target_uid, "Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

        res = self.client.get(
            "/api/resume-status",
            headers={"X-User-Id": target_uid, "Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

    def test_cannot_authenticate_via_query_param(self):
        """Supplying ?user_id= must NEVER authenticate the request."""
        target_uid = self.user1["user_id"]
        res = self.client.get(
            f"/api/jobs?user_id={target_uid}",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

        res = self.client.get(
            f"/api/subscription-status?user_id={target_uid}",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

        res = self.client.get(
            f"/api/resume-status?user_id={target_uid}",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(res.status_code, 401)

    def test_cannot_authenticate_via_raw_unsigned_cookies(self):
        """Supplying raw a_jent_user_id or jent_user_id cookies must NEVER authenticate."""
        target_uid = self.user1["user_id"]
        self.client.set_cookie("a_jent_user_id", target_uid)
        self.client.set_cookie("jent_user_id", target_uid)

        res = self.client.get("/api/auth/me", headers={"Accept": "application/json"})
        self.assertEqual(res.status_code, 401)

        res = self.client.get("/api/jobs", headers={"Accept": "application/json"})
        self.assertEqual(res.status_code, 401)

    def test_cannot_authenticate_via_request_body_user_id(self):
        """Supplying user_id in POST body must NEVER authenticate an unauthenticated user."""
        token = self._get_csrf_token()
        target_uid = self.user1["user_id"]
        res = self.client.post(
            "/api/create-order",
            data=json.dumps({"user_id": target_uid}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res.status_code, 401)

    # ── 3. Session Lifecycle: Login & Logout ─────────────────────────────────

    def test_login_creates_valid_session(self):
        """Logging in creates a valid signed session and grants access to protected routes."""
        res = self._login(self.client, self.user1_email, self.user1_pass)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data.decode("utf-8"))
        self.assertTrue(data.get("authenticated"))
        self.assertEqual(data["user"]["email"], self.user1_email)

        # Access protected route /api/auth/me
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)
        data_me = json.loads(res_me.data.decode("utf-8"))
        self.assertTrue(data_me["authenticated"])
        self.assertEqual(data_me["user"]["email"], self.user1_email)

        # Access /api/jobs
        res_jobs = self.client.get("/api/jobs")
        self.assertEqual(res_jobs.status_code, 200)

        # Access /api/subscription-status
        res_sub = self.client.get("/api/subscription-status")
        self.assertEqual(res_sub.status_code, 200)
        data_sub = json.loads(res_sub.data.decode("utf-8"))
        self.assertEqual(data_sub["email"], self.user1_email)

    def test_logout_invalidates_session(self):
        """Logging out must invalidate the session so subsequent requests fail."""
        # Log in first
        self._login(self.client, self.user1_email, self.user1_pass)
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)

        # Log out
        token = self._get_csrf_token()
        res_logout = self.client.post(
            "/api/auth/logout",
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(res_logout.status_code, 200)

        # Subsequent requests must now be rejected
        res_me_after = self.client.get("/api/auth/me")
        self.assertEqual(res_me_after.status_code, 401)

        res_jobs_after = self.client.get("/api/jobs")
        self.assertEqual(res_jobs_after.status_code, 401)

    # ── 4. CSRF Protection ───────────────────────────────────────────────────

    def test_csrf_token_required_for_post_routes(self):
        """State-changing POST routes without CSRF token must fail with 400."""
        # Unauthenticated login attempt without CSRF token
        res = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": self.user1_email, "password": self.user1_pass}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data.decode("utf-8"))
        self.assertIn("error", data)
        self.assertIn("CSRF", data["error"])

    def test_payment_webhook_exempt_from_csrf(self):
        """Cashfree webhook must be exempt from CSRF protection as it is server-to-server."""
        res = self.client.post(
            "/api/payment-webhook",
            data=json.dumps({"data": {}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data.decode("utf-8"))
        self.assertEqual(data.get("status"), "ok")

    # ── 5. User Data Isolation ───────────────────────────────────────────────

    def test_user_data_isolation(self):
        """User A must only receive User A's data, never User B's data."""
        client_a = app.test_client()
        client_b = app.test_client()

        # Log in User A
        self._login(client_a, self.user1_email, self.user1_pass)
        # Log in User B
        self._login(client_b, self.user2_email, self.user2_pass)

        # Alice's subscription
        res_a = client_a.get("/api/subscription-status")
        self.assertEqual(res_a.status_code, 200)
        data_a = json.loads(res_a.data.decode("utf-8"))
        self.assertEqual(data_a["email"], self.user1_email)
        self.assertEqual(data_a["user_id"], self.user1["user_id"])

        # Bob's subscription
        res_b = client_b.get("/api/subscription-status")
        self.assertEqual(res_b.status_code, 200)
        data_b = json.loads(res_b.data.decode("utf-8"))
        self.assertEqual(data_b["email"], self.user2_email)
        self.assertEqual(data_b["user_id"], self.user2["user_id"])

        # Alice trying to spoof Bob via header
        res_spoof = client_a.get("/api/subscription-status", headers={"X-User-Id": self.user2["user_id"]})
        data_spoof = json.loads(res_spoof.data.decode("utf-8"))
        # Must still return Alice's data, ignoring the spoof header
        self.assertEqual(data_spoof["email"], self.user1_email)
        self.assertEqual(data_spoof["user_id"], self.user1["user_id"])

    # ── 6. Cookie Security Configuration ─────────────────────────────────────

    def test_session_cookie_security_settings(self):
        """Ensure session cookie security flags are configured securely."""
        self.assertTrue(app.config.get("SESSION_COOKIE_HTTPONLY"))
        self.assertIn(str(app.config.get("SESSION_COOKIE_SAMESITE")).lower(), ["lax", "strict"])


if __name__ == "__main__":
    unittest.main()
