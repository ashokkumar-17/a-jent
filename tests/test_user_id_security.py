"""
Automated Tests for Task 3: Unpredictable Cryptographically Random User IDs.

Covers:
a. Newly registered users receive a random-format user ID (usr_<24 hex chars>).
b. Two newly registered users receive different IDs.
c. The generated ID does not contain or derive directly from the email.
d. Existing users retain their current IDs.
e. Existing user-associated jobs/applications/resumes remain associated with the same user.
f. MongoDB and JSON fallback paths both work.
g. Authentication still works after registration/login.
h. User data isolation still works.
i. A collision is handled safely rather than silently overwriting another user.
"""

import os
import sys
import json
import hashlib
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
from dashboard.app import app


class TestUserIdSecurity(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = True
        self.client = app.test_client()

    def _get_csrf_token(self, client=None) -> str:
        c = client or self.client
        res = c.get("/api/csrf-token")
        data = json.loads(res.data.decode("utf-8"))
        return data["csrf_token"]

    def _register(self, client, email, password, name="Test User"):
        token = self._get_csrf_token(client)
        return client.post(
            "/api/auth/register",
            data=json.dumps({"name": name, "email": email, "password": password}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )

    def _login(self, client, email, password):
        token = self._get_csrf_token(client)
        return client.post(
            "/api/auth/login",
            data=json.dumps({"email": email, "password": password}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )

    # ── a. Random format: usr_<24 hex chars> ──────────────────────────────────

    def test_newly_registered_users_receive_random_format_id(self):
        """Newly created users receive an ID matching 'usr_<24 hex chars>' (96 bits entropy)."""
        email = "random_id_test@example.com"
        user = db.create_user(email, "Password123", name="Random User")
        self.assertIsNotNone(user)
        uid = user.get("user_id", "")

        # Must start with usr_
        self.assertTrue(uid.startswith("usr_"), f"User ID should start with usr_, got {uid}")

        # Total length: 'usr_' (4 chars) + 24 hex chars = 28 characters
        self.assertEqual(len(uid), 28, f"Expected 28 chars for usr_<24 hex chars>, got {len(uid)} ({uid})")

        # Hex component must be valid hexadecimal
        hex_part = uid[4:]
        self.assertEqual(len(hex_part), 24)
        int(hex_part, 16)  # will raise ValueError if not valid hex

    # ── b. Different IDs for different users ───────────────────────────────────

    def test_two_new_users_receive_different_ids(self):
        """Two distinct newly created users must receive completely different IDs."""
        user_a = db.create_user("user_a@example.com", "Password123", name="User A")
        user_b = db.create_user("user_b@example.com", "Password123", name="User B")

        self.assertIsNotNone(user_a)
        self.assertIsNotNone(user_b)
        self.assertNotEqual(user_a["user_id"], user_b["user_id"])

    # ── c. ID does not derive from or contain email ───────────────────────────

    def test_generated_id_does_not_contain_or_derive_from_email(self):
        """User ID must not contain the email or derive from MD5(email)."""
        email = "predictable_test@example.com"
        old_predictable_md5 = f"usr_{hashlib.md5(email.encode()).hexdigest()[:12]}"

        user = db.create_user(email, "Password123", name="Predictable Test")
        actual_uid = user["user_id"]

        # Must NOT equal the old MD5-derived ID
        self.assertNotEqual(actual_uid, old_predictable_md5)

        # Must not contain email or username substring
        self.assertNotIn("predictable", actual_uid.lower())
        self.assertNotIn("example", actual_uid.lower())

    # ── d. Existing users retain their current IDs ─────────────────────────────

    def test_existing_users_retain_current_ids(self):
        """Existing user accounts in storage must NOT have their IDs altered."""
        email = "retained_user@example.com"
        original_uid = "usr_legacy_md5_01"

        # Manually save a user with an established ID
        existing_doc = {
            "user_id": original_uid,
            "email": email,
            "name": "Retained User",
            "password_hash": db.hash_password("Password123"),
            "subscription_status": "trial",
        }
        db.save_user(existing_doc)

        # Verify load_users() preserves the exact existing ID
        users = db.load_users()
        self.assertEqual(users[email]["user_id"], original_uid)

        # Authenticating must preserve the exact existing ID
        auth_user = db.authenticate_user(email, "Password123")
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user["user_id"], original_uid)

        # Calling create_user on existing email returns None and does not overwrite
        dup = db.create_user(email, "Password123")
        self.assertIsNone(dup)
        self.assertEqual(db.load_users()[email]["user_id"], original_uid)

    # ── e. Existing associated data remains linked to same user ───────────────

    def test_existing_user_associated_data_remains_associated(self):
        """Seen jobs, applied jobs, and profile remain associated with existing user ID."""
        email = "data_linked@example.com"
        uid = "usr_existing_data_01"

        user_doc = {
            "user_id": uid,
            "email": email,
            "name": "Data Linked",
            "password_hash": db.hash_password("Password123"),
        }
        db.save_user(user_doc)

        # Associate seen jobs
        seen_data = {"job_101": {"title": "Software Engineer", "score": 0.85}}
        db.save_seen(seen_data, user_id=uid)

        # Associate applied jobs
        applied_data = {"job_101": {"title": "Software Engineer", "status": "submitted"}}
        db.save_applied(applied_data, user_id=uid)

        # Associate user resumes
        user_doc["resumes"] = [{"id": "res_101", "filename": "my_resume.pdf", "is_primary": True}]
        db.save_user(user_doc)

        # Verify retrieval with the user ID works
        loaded_seen = db.load_seen(user_id=uid)
        self.assertIn("job_101", loaded_seen)

        loaded_applied = db.load_applied(user_id=uid)
        self.assertIn("job_101", loaded_applied)

        loaded_user = db.load_users()[email]
        self.assertEqual(loaded_user["user_id"], uid)
        self.assertEqual(len(loaded_user.get("resumes", [])), 1)
        self.assertEqual(loaded_user["resumes"][0]["filename"], "my_resume.pdf")

        # In fallback mode, profile returns {'user_id': uid}
        profile_fallback = db.get_user_profile(user_id=uid)
        self.assertEqual(profile_fallback.get("user_id"), uid)

        # When MongoDB is connected, full profile is retrieved by user_id
        mock_db = MagicMock()
        mock_db.user_profiles.find_one.return_value = {"user_id": uid, "full_name": "Data Linked"}
        with patch("db.is_mongodb_connected", return_value=True), patch("db._db", mock_db):
            profile = db.get_user_profile(user_id=uid)
            self.assertEqual(profile.get("user_id"), uid)
            self.assertEqual(profile.get("full_name"), "Data Linked")

    # ── f. MongoDB and JSON fallback paths both work ──────────────────────────

    def test_json_fallback_id_generation(self):
        """JSON fallback storage generates and saves random user ID properly."""
        with patch("db.is_mongodb_connected", return_value=False):
            email = "json_id_test@example.com"
            user = db.create_user(email, "Password123", name="JSON ID User")
            self.assertIsNotNone(user)
            self.assertTrue(user["user_id"].startswith("usr_"))
            self.assertEqual(len(user["user_id"]), 28)

    def test_mongodb_path_collision_check(self):
        """MongoDB path checks for collisions using _user_id_exists."""
        mock_db = MagicMock()
        with patch("db.is_mongodb_connected", return_value=True), patch("db._db", mock_db):
            # First find_one returns a collision doc, second find_one returns None
            mock_db.users.find_one.side_effect = [{"_id": "1"}, None]

            uid = db.generate_user_id()
            self.assertTrue(uid.startswith("usr_"))
            self.assertEqual(len(uid), 28)
            # find_one should have been called to check for collision
            self.assertGreaterEqual(mock_db.users.find_one.call_count, 1)

    # ── g. Authentication works after registration/login ──────────────────────

    def test_auth_works_after_registration_and_login_with_random_id(self):
        """Registration and login flow via API works end-to-end with the new random user ID."""
        email = "api_random_flow@example.com"
        pwd = "ApiPassword123!"
        res_reg = self._register(self.client, email, pwd, name="API Random Flow")
        self.assertEqual(res_reg.status_code, 200)
        reg_data = json.loads(res_reg.data.decode("utf-8"))
        assigned_uid = reg_data["user"]["user_id"]
        self.assertTrue(assigned_uid.startswith("usr_"))
        self.assertEqual(len(assigned_uid), 28)

        # Login
        client2 = app.test_client()
        res_login = self._login(client2, email, pwd)
        self.assertEqual(res_login.status_code, 200)
        login_data = json.loads(res_login.data.decode("utf-8"))
        self.assertEqual(login_data["user"]["user_id"], assigned_uid)

        # Access /api/auth/me
        res_me = client2.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)
        me_data = json.loads(res_me.data.decode("utf-8"))
        self.assertEqual(me_data["user"]["user_id"], assigned_uid)

    # ── h. User data isolation still works ────────────────────────────────────

    def test_user_data_isolation_with_random_ids(self):
        """Users with new random IDs have isolated sessions and data."""
        client1 = app.test_client()
        client2 = app.test_client()

        u1 = db.create_user("iso_1@example.com", "Password123!", name="Iso One")
        u2 = db.create_user("iso_2@example.com", "Password123!", name="Iso Two")

        self.assertNotEqual(u1["user_id"], u2["user_id"])

        self._login(client1, "iso_1@example.com", "Password123!")
        self._login(client2, "iso_2@example.com", "Password123!")

        me1 = json.loads(client1.get("/api/auth/me").data.decode("utf-8"))
        me2 = json.loads(client2.get("/api/auth/me").data.decode("utf-8"))

        self.assertEqual(me1["user"]["user_id"], u1["user_id"])
        self.assertEqual(me2["user"]["user_id"], u2["user_id"])

    # ── i. Collision handling: retries safely ──────────────────────────────────

    def test_collision_handled_safely(self):
        """If a generated candidate ID already exists, generate_user_id loops until a unique ID is found."""
        existing_uid = "usr_collision_candidate_1"
        db.save_user({
            "user_id": existing_uid,
            "email": "collision_existing@example.com",
            "name": "Collision Existing",
            "password_hash": db.hash_password("Pass123"),
        })

        # Mock secrets.token_hex to return the colliding hex first, then a fresh hex
        colliding_hex = existing_uid.replace("usr_", "")
        fresh_hex = "abcdef1234567890abcdef12"

        with patch("secrets.token_hex", side_effect=[colliding_hex, fresh_hex]):
            resolved_uid = db.generate_user_id()
            self.assertEqual(resolved_uid, f"usr_{fresh_hex}")
            self.assertNotEqual(resolved_uid, existing_uid)


if __name__ == "__main__":
    unittest.main()
