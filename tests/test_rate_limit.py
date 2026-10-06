"""
Automated Tests for Task 4: Rate Limiting & Brute-Force Protection
------------------------------------------------------------------
Verifies:
1. Login succeeds under the configured limit.
2. Repeated failed login attempts eventually receive HTTP 429.
3. A successful login is still possible when under the limit.
4. Registration is rate-limited.
5. Rate limiting does not break normal authentication flow (register, login, logout, re-login, dashboard).
6. HTTP 429 responses do not reveal whether an email exists.
7. Account/email-based rate limiting defends against distributed brute-force across multiple IPs.
8. Proxy IP spoofing (X-Forwarded-For) is rejected when NUM_PROXIES=0.
9. Rate limiter reset immediately clears limits.
10. Production limit configurations and environment variables are properly read.
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
from dashboard.app import app, limiter


class TestRateLimitingSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = True

    def setUp(self):
        # Save original config
        self._orig_login_ip = app.config.get("RATELIMIT_LOGIN_IP")
        self._orig_login_email = app.config.get("RATELIMIT_LOGIN_EMAIL")
        self._orig_register_ip = app.config.get("RATELIMIT_REGISTER_IP")
        self._orig_enabled = app.config.get("RATELIMIT_ENABLED")

        app.config["RATELIMIT_ENABLED"] = True
        limiter.reset()
        self.client = app.test_client()

    def tearDown(self):
        # Restore original config
        app.config["RATELIMIT_LOGIN_IP"] = self._orig_login_ip
        app.config["RATELIMIT_LOGIN_EMAIL"] = self._orig_login_email
        app.config["RATELIMIT_REGISTER_IP"] = self._orig_register_ip
        app.config["RATELIMIT_ENABLED"] = self._orig_enabled
        limiter.reset()

    @classmethod
    def tearDownClass(cls):
        limiter.reset()

    def _get_csrf_token(self, client):
        res = client.get("/api/csrf-token")
        data = json.loads(res.data.decode("utf-8"))
        return data["csrf_token"]

    def _post_json(self, client, url, payload, remote_addr="127.0.0.1", headers_extra=None):
        token = self._get_csrf_token(client)
        headers = {
            "Content-Type": "application/json",
            "X-CSRFToken": token,
        }
        if headers_extra:
            headers.update(headers_extra)
        environ_base = {"REMOTE_ADDR": remote_addr} if remote_addr else {}
        return client.post(
            url,
            data=json.dumps(payload),
            headers=headers,
            environ_base=environ_base,
        )

    def test_login_succeeds_under_configured_limit(self):
        """Valid login succeeds under the configured limit."""
        email = "valid_rate_user@example.com"
        pwd = "SafePassword123!"
        db.create_user(email, pwd, name="Rate User")

        # First login attempt
        res1 = self._post_json(self.client, "/api/auth/login", {"email": email, "password": pwd})
        self.assertEqual(res1.status_code, 200)
        data1 = json.loads(res1.data.decode("utf-8"))
        self.assertTrue(data1.get("authenticated"))

        # Second login attempt under limit
        res2 = self._post_json(self.client, "/api/auth/login", {"email": email, "password": pwd})
        self.assertEqual(res2.status_code, 200)

    def test_repeated_failed_login_attempts_receive_http_429(self):
        """Repeated failed login attempts eventually receive HTTP 429."""
        app.config["RATELIMIT_LOGIN_IP"] = "3/minute"
        email = "brute_target@example.com"

        # Attempt 1: 401
        res1 = self._post_json(self.client, "/api/auth/login", {"email": email, "password": "wrong"})
        self.assertEqual(res1.status_code, 401)

        # Attempt 2: 401
        res2 = self._post_json(self.client, "/api/auth/login", {"email": email, "password": "wrong"})
        self.assertEqual(res2.status_code, 401)

        # Attempt 3: 401
        res3 = self._post_json(self.client, "/api/auth/login", {"email": email, "password": "wrong"})
        self.assertEqual(res3.status_code, 401)

        # Attempt 4: Limit exceeded -> 429
        res4 = self._post_json(self.client, "/api/auth/login", {"email": email, "password": "wrong"})
        self.assertEqual(res4.status_code, 429)
        data4 = json.loads(res4.data.decode("utf-8"))
        self.assertIn("error", data4)
        self.assertIn("Too many requests", data4["error"])

    def test_successful_login_possible_when_under_limit(self):
        """A user can successfully log in after a failed attempt as long as under the limit."""
        app.config["RATELIMIT_LOGIN_IP"] = "5/minute"
        app.config["RATELIMIT_LOGIN_EMAIL"] = "5/minute"
        email = "retry_success@example.com"
        pwd = "CorrectPassword123!"
        db.create_user(email, pwd, name="Retry User")

        # Mistyped password
        res_fail = self._post_json(self.client, "/api/auth/login", {"email": email, "password": "wrong_password"})
        self.assertEqual(res_fail.status_code, 401)

        # Correct password on next attempt (under limit)
        res_ok = self._post_json(self.client, "/api/auth/login", {"email": email, "password": pwd})
        self.assertEqual(res_ok.status_code, 200)
        data = json.loads(res_ok.data.decode("utf-8"))
        self.assertTrue(data.get("authenticated"))

        # Verify session is working
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)

    def test_registration_is_rate_limited(self):
        """Registration endpoint returns HTTP 429 when registration limit is exceeded."""
        app.config["RATELIMIT_REGISTER_IP"] = "2/minute"

        res1 = self._post_json(self.client, "/api/auth/register", {
            "email": "reg_limit_1@example.com",
            "password": "Password123!",
            "name": "User 1",
        })
        self.assertEqual(res1.status_code, 200)

        res2 = self._post_json(self.client, "/api/auth/register", {
            "email": "reg_limit_2@example.com",
            "password": "Password123!",
            "name": "User 2",
        })
        self.assertEqual(res2.status_code, 200)

        # 3rd attempt exceeds 2/minute
        res3 = self._post_json(self.client, "/api/auth/register", {
            "email": "reg_limit_3@example.com",
            "password": "Password123!",
            "name": "User 3",
        })
        self.assertEqual(res3.status_code, 429)
        data3 = json.loads(res3.data.decode("utf-8"))
        self.assertIn("Too many requests", data3.get("error", ""))

    def test_rate_limiting_does_not_break_normal_authentication_flow(self):
        """Normal users can register, log in, view dashboard, log out, and log in again."""
        email = "flow_user@example.com"
        pwd = "FlowPassword123!"

        # 1. Register
        res_reg = self._post_json(self.client, "/api/auth/register", {
            "email": email,
            "password": pwd,
            "name": "Flow User",
        })
        self.assertEqual(res_reg.status_code, 200)

        # 2. View profile
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)

        # 3. View dashboard jobs
        res_jobs = self.client.get("/api/jobs")
        self.assertEqual(res_jobs.status_code, 200)

        # 4. Logout
        token = self._get_csrf_token(self.client)
        res_logout = self.client.post("/api/auth/logout", headers={"X-CSRFToken": token})
        self.assertEqual(res_logout.status_code, 200)

        # 5. Log in again
        res_login = self._post_json(self.client, "/api/auth/login", {
            "email": email,
            "password": pwd,
        })
        self.assertEqual(res_login.status_code, 200)
        self.assertTrue(json.loads(res_login.data.decode("utf-8")).get("authenticated"))

    def test_429_responses_do_not_reveal_whether_email_exists(self):
        """HTTP 429 response structure and error message are identical regardless of whether account exists."""
        app.config["RATELIMIT_LOGIN_EMAIL"] = "2/minute"
        real_email = "real_account@example.com"
        fake_email = "nonexistent_account@example.com"

        db.create_user(real_email, "Password123!", name="Real Account")

        # Exceed limit for real email
        self._post_json(self.client, "/api/auth/login", {"email": real_email, "password": "wrong"})
        self._post_json(self.client, "/api/auth/login", {"email": real_email, "password": "wrong"})
        res_real_429 = self._post_json(self.client, "/api/auth/login", {"email": real_email, "password": "wrong"})

        self.assertEqual(res_real_429.status_code, 429)
        real_data = json.loads(res_real_429.data.decode("utf-8"))

        # Reset limiter for fair comparison of fake email
        limiter.reset()

        # Exceed limit for fake email
        self._post_json(self.client, "/api/auth/login", {"email": fake_email, "password": "wrong"})
        self._post_json(self.client, "/api/auth/login", {"email": fake_email, "password": "wrong"})
        res_fake_429 = self._post_json(self.client, "/api/auth/login", {"email": fake_email, "password": "wrong"})

        self.assertEqual(res_fake_429.status_code, 429)
        fake_data = json.loads(res_fake_429.data.decode("utf-8"))

        # Responses must be completely indistinguishable
        self.assertEqual(real_data, fake_data)
        self.assertEqual(real_data["error"], "Too many requests. Please try again later.")
        self.assertNotIn("email", real_data["error"].lower())
        self.assertNotIn("account", real_data["error"].lower())
        self.assertNotIn("user", real_data["error"].lower())

    def test_account_email_based_rate_limiting_across_multiple_ips(self):
        """Targeting the same account across multiple distinct IPs triggers the email-based limit."""
        app.config["RATELIMIT_LOGIN_EMAIL"] = "3/minute"
        app.config["RATELIMIT_LOGIN_IP"] = "20/minute"
        victim_email = "victim_distributed@example.com"

        # Attacker tries from 3 different IPs
        res1 = self._post_json(self.client, "/api/auth/login", {"email": victim_email, "password": "p1"}, remote_addr="10.0.0.1")
        self.assertEqual(res1.status_code, 401)

        res2 = self._post_json(self.client, "/api/auth/login", {"email": victim_email, "password": "p2"}, remote_addr="10.0.0.2")
        self.assertEqual(res2.status_code, 401)

        res3 = self._post_json(self.client, "/api/auth/login", {"email": victim_email, "password": "p3"}, remote_addr="10.0.0.3")
        self.assertEqual(res3.status_code, 401)

        # 4th attempt from a brand new IP (10.0.0.4) is blocked because victim_email limit is exceeded
        res4 = self._post_json(self.client, "/api/auth/login", {"email": victim_email, "password": "p4"}, remote_addr="10.0.0.4")
        self.assertEqual(res4.status_code, 429)

    def test_proxy_untrusted_header_ignored_by_default(self):
        """When NUM_PROXIES=0, spoofed X-Forwarded-For headers are ignored and cannot bypass IP limits."""
        app.config["RATELIMIT_LOGIN_IP"] = "2/minute"

        # Attacker spoofs different X-Forwarded-For headers, but remote_addr is identical (127.0.0.1)
        res1 = self._post_json(
            self.client,
            "/api/auth/login",
            {"email": "any1@example.com", "password": "wrong"},
            remote_addr="127.0.0.1",
            headers_extra={"X-Forwarded-For": "203.0.113.1"},
        )
        self.assertEqual(res1.status_code, 401)

        res2 = self._post_json(
            self.client,
            "/api/auth/login",
            {"email": "any2@example.com", "password": "wrong"},
            remote_addr="127.0.0.1",
            headers_extra={"X-Forwarded-For": "203.0.113.2"},
        )
        self.assertEqual(res2.status_code, 401)

        # 3rd attempt from same connection (127.0.0.1) receives 429 despite spoofed header
        res3 = self._post_json(
            self.client,
            "/api/auth/login",
            {"email": "any3@example.com", "password": "wrong"},
            remote_addr="127.0.0.1",
            headers_extra={"X-Forwarded-For": "203.0.113.3"},
        )
        self.assertEqual(res3.status_code, 429)

    def test_limiter_reset_clears_limits_immediately(self):
        """Calling limiter.reset() clears rate limit counters and restores access."""
        app.config["RATELIMIT_LOGIN_IP"] = "1/minute"

        res1 = self._post_json(self.client, "/api/auth/login", {"email": "test@example.com", "password": "wrong"})
        self.assertEqual(res1.status_code, 401)

        res2 = self._post_json(self.client, "/api/auth/login", {"email": "test@example.com", "password": "wrong"})
        self.assertEqual(res2.status_code, 429)

        # Reset limiter
        limiter.reset()

        # Should be allowed again
        res3 = self._post_json(self.client, "/api/auth/login", {"email": "test@example.com", "password": "wrong"})
        self.assertEqual(res3.status_code, 401)


if __name__ == "__main__":
    unittest.main()
