"""
Automated Tests for Task 5: Payment & Subscription Hardening (Prototype Flow)
-----------------------------------------------------------------------------
Verifies:
1. Pay button successfully activates the selected valid plan.
2. Repeated Pay requests do not corrupt subscription state (idempotency).
3. Invalid plan names are rejected safely with HTTP 400.
4. Missing required payment fields and malformed inputs are handled safely.
5. Unauthenticated payment requests are rejected according to session auth rules.
6. Existing subscription data remains compatible.
7. Payment endpoint errors do not expose secrets or API credentials.
8. Authenticated session user identity is strictly enforced (cannot spoof email).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
from dashboard.app import app, limiter, SUBSCRIPTIONS_FILE, _activate_subscription


class TestPaymentHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = True

    def setUp(self):
        limiter.reset()
        self.client = app.test_client()
        # Backup subscriptions file if present
        self._backup_subs = None
        if SUBSCRIPTIONS_FILE.exists():
            try:
                self._backup_subs = SUBSCRIPTIONS_FILE.read_text(encoding="utf-8")
            except Exception:
                pass

    def tearDown(self):
        limiter.reset()
        if self._backup_subs is not None:
            try:
                SUBSCRIPTIONS_FILE.write_text(self._backup_subs, encoding="utf-8")
            except Exception:
                pass

    def _get_csrf_token(self, client):
        res = client.get("/api/csrf-token")
        data = json.loads(res.data.decode("utf-8"))
        return data["csrf_token"]

    def _register_and_login(self, client, email, password="Password123!", name="Test User"):
        # Remove any leftover test user from previous runs to ensure test isolation
        users = db.load_users()
        if email in users:
            users.pop(email, None)
            try:
                with open(db.USERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        token = self._get_csrf_token(client)
        res = client.post(
            "/api/auth/register",
            data=json.dumps({"name": name, "email": email, "password": password}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res.status_code, 200)
        return json.loads(res.data.decode("utf-8"))

    def test_pay_button_successfully_activates_selected_valid_plan(self):
        """Clicking Pay (POST /api/create-order) activates the selected valid plan for the prototype."""
        email = "pay_valid@example.com"
        self._register_and_login(self.client, email)

        # Initially on trial
        res_initial = self.client.get("/api/subscription-status")
        initial_data = json.loads(res_initial.data.decode("utf-8"))
        self.assertEqual(initial_data.get("plan"), "trial")

        # Click Pay button (/api/create-order)
        token = self._get_csrf_token(self.client)
        res_order = self.client.post(
            "/api/create-order",
            data=json.dumps({"plan": "monthly"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res_order.status_code, 200)
        data = json.loads(res_order.data.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("simulated"))
        self.assertEqual(data.get("plan"), "monthly")

        # Verify active subscription status
        res_status = self.client.get("/api/subscription-status")
        status_data = json.loads(res_status.data.decode("utf-8"))
        self.assertTrue(status_data.get("active"))
        self.assertEqual(status_data.get("status"), "active")
        self.assertEqual(status_data.get("plan"), "monthly")
        self.assertGreaterEqual(status_data.get("days_left", 0), 30)

    def test_repeated_pay_requests_do_not_corrupt_subscription_state(self):
        """Repeated calls to Pay button or activation update state idempotently without duplicate records."""
        email = "idempotent_sub@example.com"
        self._register_and_login(self.client, email)
        token = self._get_csrf_token(self.client)

        # 1st Pay request
        res1 = self.client.post(
            "/api/create-order",
            data=json.dumps({"plan": "monthly"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res1.status_code, 200)

        # 2nd Pay request
        res2 = self.client.post(
            "/api/create-order",
            data=json.dumps({"plan": "monthly"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res2.status_code, 200)

        # 3rd Pay request
        res3 = self.client.post(
            "/api/create-order",
            data=json.dumps({"plan": "monthly"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res3.status_code, 200)

        # Check subscriptions.json: exactly 1 active record for this email
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            subs = json.load(f)
        active_for_user = [
            s for s in subs.get("subscribers", [])
            if s.get("email") == email and s.get("status") == "active"
        ]
        self.assertEqual(len(active_for_user), 1)

        # Check user document in DB
        users = db.load_users()
        self.assertEqual(users[email]["subscription_status"], "active")
        self.assertEqual(users[email]["plan"], "monthly")

    def test_invalid_plan_is_rejected_safely(self):
        """Requesting an invalid plan returns HTTP 400 and preserves existing subscription."""
        email = "invalid_plan_user@example.com"
        self._register_and_login(self.client, email)
        token = self._get_csrf_token(self.client)

        # Attempt to order invalid plan
        res = self.client.post(
            "/api/create-order",
            data=json.dumps({"plan": "vip_unlimited_free"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data.decode("utf-8"))
        self.assertIn("error", data)
        self.assertIn("Invalid plan requested", data["error"])

        # User's plan should still be trial, not activated
        res_status = self.client.get("/api/subscription-status")
        status_data = json.loads(res_status.data.decode("utf-8"))
        self.assertEqual(status_data.get("plan"), "trial")

    def test_missing_required_payment_fields_handled_safely(self):
        """Missing or malformed fields return HTTP 400 safely without crashing."""
        email = "fields_test@example.com"
        self._register_and_login(self.client, email)
        token = self._get_csrf_token(self.client)

        # 1. Missing order_id in /api/verify-payment
        res_missing = self.client.post(
            "/api/verify-payment",
            data=json.dumps({}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res_missing.status_code, 400)
        self.assertIn("order_id required", json.loads(res_missing.data.decode("utf-8"))["error"])

        # 2. Malformed order_id with path traversal / special characters
        res_malformed = self.client.post(
            "/api/verify-payment",
            data=json.dumps({"order_id": "../../etc/passwd"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res_malformed.status_code, 400)
        self.assertIn("Invalid order_id format", json.loads(res_malformed.data.decode("utf-8"))["error"])

        # 3. Webhook with empty or missing payment fields handled safely without crashing
        res_webhook = self.client.post(
            "/api/payment-webhook",
            data=json.dumps({"data": {}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res_webhook.status_code, 200)
        self.assertEqual(json.loads(res_webhook.data.decode("utf-8")).get("status"), "ok")

    def test_unauthenticated_payment_requests_rejected(self):
        """Unauthenticated clients cannot access or trigger payment endpoints."""
        token = self._get_csrf_token(self.client)

        # /api/create-order
        res_create = self.client.post(
            "/api/create-order",
            data=json.dumps({"plan": "monthly"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res_create.status_code, 401)

        # /api/verify-payment
        res_verify = self.client.post(
            "/api/verify-payment",
            data=json.dumps({"order_id": "test_order"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res_verify.status_code, 401)

        # /api/subscription-status
        res_status = self.client.get("/api/subscription-status")
        self.assertEqual(res_status.status_code, 401)

    def test_existing_subscription_data_remains_compatible(self):
        """Existing subscribers in subscriptions.json remain fully compatible."""
        existing_email = "existing_subscriber@example.com"
        db.create_user(existing_email, "Password123!", name="Existing Sub")

        # Activate directly simulating an existing record
        _activate_subscription(
            email=existing_email,
            name="Existing Sub",
            order_id="order_legacy_001",
            payment_id="pay_legacy_001",
            amount=75,
            plan="monthly",
        )

        # Log in and check subscription status
        client = app.test_client()
        token = self._get_csrf_token(client)
        client.post(
            "/api/auth/login",
            data=json.dumps({"email": existing_email, "password": "Password123!"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )

        res_status = client.get("/api/subscription-status")
        self.assertEqual(res_status.status_code, 200)
        status_data = json.loads(res_status.data.decode("utf-8"))
        self.assertTrue(status_data.get("active"))
        self.assertEqual(status_data.get("plan"), "monthly")

    def test_payment_endpoint_errors_do_not_expose_secrets(self):
        """Cashfree communication failures return sanitized 502 without leaking secrets."""
        email = "leak_check@example.com"
        self._register_and_login(self.client, email)
        token = self._get_csrf_token(self.client)

        secret_marker = "SUPER_SECRET_LEAK_TOKEN_XYZ987"

        with patch("dashboard.app.CASHFREE_APP_ID", "CF_TEST_APP_ID"), \
             patch("dashboard.app.CASHFREE_SECRET", secret_marker), \
             patch("dashboard.app._requests.post", side_effect=Exception(f"Network error with key {secret_marker}")):

            res = self.client.post(
                "/api/create-order",
                data=json.dumps({"plan": "monthly"}),
                headers={"Content-Type": "application/json", "X-CSRFToken": token},
            )
            self.assertEqual(res.status_code, 502)
            raw_body = res.data.decode("utf-8")
            self.assertNotIn(secret_marker, raw_body)
            self.assertIn("Payment order creation failed", raw_body)

    def test_verify_payment_enforces_authenticated_session_user_identity(self):
        """POST /api/verify-payment cannot activate subscriptions for arbitrary other emails."""
        user_a = "user_a_legit@example.com"
        user_b = "user_b_victim@example.com"

        self._register_and_login(self.client, user_a)
        users = db.load_users()
        if user_b in users:
            users.pop(user_b, None)
            with open(db.USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
        db.create_user(user_b, "Password123!", name="User B")

        token = self._get_csrf_token(self.client)

        # User A tries to pass User B's email
        res = self.client.post(
            "/api/verify-payment",
            data=json.dumps({"order_id": "sim_order_test_99", "email": user_b}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res.status_code, 200)

        # Check DB: User A is activated, User B is untouched (still trial)
        users = db.load_users()
        self.assertEqual(users[user_a]["subscription_status"], "active")
        self.assertEqual(users[user_b]["subscription_status"], "trial")


if __name__ == "__main__":
    unittest.main()
