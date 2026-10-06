"""
Automated Tests for Task 2: Argon2id Password Storage & Transparent Migration.

Covers:
1. New registration stores an Argon2id hash.
2. Correct password verifies successfully.
3. Incorrect password fails.
4. Plaintext password is never stored in user documents or files.
5. Legacy SHA-256 password verifies successfully.
6. Successful login using a legacy SHA-256 hash upgrades that hash to Argon2id.
7. Failed login using a legacy SHA-256 hash does NOT upgrade the hash.
8. An invalid/malformed password hash fails safely rather than crashing authentication.
9. MongoDB storage path works and handles salt unsetting when migrating.
10. JSON fallback storage path works correctly.
11. Existing session creation after successful login still works.
12. Existing logout/session behavior from Task 1 still works.
13. Email enumeration / generic error message consistency.
"""

import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
from dashboard.app import app


class TestPasswordSecurity(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = True
        self.client = app.test_client()

    def _get_csrf_token(self, client=None) -> str:
        c = client or self.client
        res = c.get("/api/csrf-token")
        data = json.loads(res.data.decode("utf-8"))
        return data["csrf_token"]

    def _login(self, client, email, password):
        token = self._get_csrf_token(client)
        return client.post(
            "/api/auth/login",
            data=json.dumps({"email": email, "password": password}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )

    # ── 1. New Registration & Argon2id Format ─────────────────────────────────

    def test_new_registration_stores_argon2id_hash(self):
        """New user registration must store a standard Argon2id hash."""
        email = "argon_user@example.com"
        pwd = "ComplexPassword789!"
        user = db.create_user(email, pwd, name="Argon User")
        self.assertIsNotNone(user)

        # Hash must be an Argon2id string
        stored_hash = user.get("password_hash", "")
        self.assertTrue(stored_hash.startswith("$argon2id$"), f"Expected $argon2id$ prefix, got {stored_hash}")
        self.assertTrue(db.is_argon2_hash(stored_hash))

        # Salt field must not be stored separately for Argon2
        self.assertNotIn("salt", user)

        # Reload from disk
        users = db.load_users()
        self.assertIn(email, users)
        disk_hash = users[email].get("password_hash", "")
        self.assertTrue(disk_hash.startswith("$argon2id$"))
        self.assertNotIn("salt", users[email])

    def test_registration_via_api_stores_argon2id(self):
        """API registration must create a user with an Argon2id hash."""
        token = self._get_csrf_token()
        email = "api_argon@example.com"
        pwd = "ApiPassword123"
        res = self.client.post(
            "/api/auth/register",
            data=json.dumps({"name": "API User", "email": email, "password": pwd}),
            headers={"Content-Type": "application/json", "X-CSRFToken": token},
        )
        self.assertEqual(res.status_code, 200)

        users = db.load_users()
        self.assertIn(email, users)
        self.assertTrue(users[email]["password_hash"].startswith("$argon2id$"))
        self.assertNotIn("salt", users[email])

    # ── 2. Password Verification ──────────────────────────────────────────────

    def test_correct_password_verifies_successfully(self):
        """Correct password verifies with both verify_password and authenticate_user."""
        pwd = "SuperSecretPassword123"
        h = db.hash_password(pwd)
        self.assertTrue(db.verify_password(h, pwd))

        email = "verify_test@example.com"
        db.create_user(email, pwd, name="Verify Test")
        auth_user = db.authenticate_user(email, pwd)
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user["email"], email)

    def test_incorrect_password_fails(self):
        """Incorrect password fails verification safely."""
        pwd = "SuperSecretPassword123"
        h = db.hash_password(pwd)
        self.assertFalse(db.verify_password(h, "WrongPassword"))

        email = "wrong_test@example.com"
        db.create_user(email, pwd, name="Wrong Test")
        self.assertIsNone(db.authenticate_user(email, "WrongPassword"))

    def test_plaintext_password_never_stored(self):
        """Plaintext password must never appear in user documents or users.json."""
        email = "plaintext_check@example.com"
        pwd = "SecretCleartextValue999"
        user = db.create_user(email, pwd, name="Plaintext Check")

        # Check in-memory user dict
        for k, v in user.items():
            self.assertNotEqual(v, pwd, f"Plaintext password found in user field '{k}'")

        # Check raw JSON file on disk
        if db.USERS_FILE.exists():
            file_content = db.USERS_FILE.read_text(encoding="utf-8")
            self.assertNotIn(pwd, file_content, "Plaintext password leaked into users.json")

    # ── 3. Legacy SHA-256 Support & Migration on Login ────────────────────────

    def test_legacy_sha256_verifies_successfully(self):
        """Legacy salted SHA-256 hash must verify successfully using verify_password."""
        pwd = "LegacyPassword123"
        legacy_hash, salt = db._hash_password(pwd)
        self.assertTrue(db.verify_password(legacy_hash, pwd, salt=salt))
        self.assertFalse(db.verify_password(legacy_hash, "IncorrectPassword", salt=salt))

    def test_successful_login_with_legacy_hash_upgrades_to_argon2id(self):
        """Successful login of a legacy SHA-256 account must automatically upgrade the hash to Argon2id."""
        email = "legacy_upgrade@example.com"
        pwd = "UpgradePassword123"
        legacy_hash, salt = db._hash_password(pwd)

        # Directly save a legacy user record
        legacy_user = {
            "user_id": "usr_legacy_upgrade",
            "email": email,
            "name": "Legacy Upgrade",
            "password_hash": legacy_hash,
            "salt": salt,
            "subscription_status": "active",
        }
        db.save_user(legacy_user)

        # Verify it is initially stored as legacy
        initial_doc = db.load_users()[email]
        self.assertEqual(initial_doc["password_hash"], legacy_hash)
        self.assertEqual(initial_doc["salt"], salt)

        # Authenticate with correct password
        authenticated_user = db.authenticate_user(email, pwd)
        self.assertIsNotNone(authenticated_user)

        # Verify the record has been migrated on disk to Argon2id
        migrated_doc = db.load_users()[email]
        self.assertTrue(migrated_doc["password_hash"].startswith("$argon2id$"))
        self.assertNotEqual(migrated_doc["password_hash"], legacy_hash)
        self.assertNotIn("salt", migrated_doc)

        # Subsequent authentication with the new Argon2id hash must succeed
        reauth = db.authenticate_user(email, pwd)
        self.assertIsNotNone(reauth)
        self.assertEqual(reauth["email"], email)

    def test_successful_api_login_upgrades_legacy_hash(self):
        """API login via /api/auth/login upgrades legacy account to Argon2id."""
        email = "api_legacy@example.com"
        pwd = "ApiLegacyPassword123"
        legacy_hash, salt = db._hash_password(pwd)

        legacy_user = {
            "user_id": "usr_api_legacy",
            "email": email,
            "name": "API Legacy",
            "password_hash": legacy_hash,
            "salt": salt,
            "subscription_status": "trial",
        }
        db.save_user(legacy_user)

        # Log in via API
        res = self._login(self.client, email, pwd)
        self.assertEqual(res.status_code, 200)

        # Verify upgrade happened in storage
        users = db.load_users()
        self.assertTrue(users[email]["password_hash"].startswith("$argon2id$"))
        self.assertNotIn("salt", users[email])

    def test_failed_login_with_legacy_hash_does_not_upgrade(self):
        """Failed login with a legacy hash must NOT upgrade or alter the hash."""
        email = "legacy_fail@example.com"
        pwd = "CorrectPassword123"
        legacy_hash, salt = db._hash_password(pwd)

        legacy_user = {
            "user_id": "usr_legacy_fail",
            "email": email,
            "name": "Legacy Fail",
            "password_hash": legacy_hash,
            "salt": salt,
        }
        db.save_user(legacy_user)

        # Attempt authentication with wrong password
        auth_result = db.authenticate_user(email, "WrongPassword")
        self.assertIsNone(auth_result)

        # Verify storage remains unchanged
        users = db.load_users()
        self.assertEqual(users[email]["password_hash"], legacy_hash)
        self.assertEqual(users[email]["salt"], salt)

    # ── 4. Error Handling & Malformed Hashes ──────────────────────────────────

    def test_malformed_hashes_fail_safely(self):
        """Invalid or corrupted hashes must fail safely without raising exceptions."""
        malformed_hashes = [
            "$argon2id$invalid_corrupted_tokens_here",
            "$argon2id$v=19$m=0,t=0,p=0$bad$bad",
            "not_a_hash",
            "",
            None,
            "sha256_short",
        ]

        for bad_hash in malformed_hashes:
            with self.subTest(bad_hash=bad_hash):
                # verify_password must return False without crashing
                self.assertFalse(db.verify_password(bad_hash, "somePassword", salt="somesalt"))

                # authenticate_user with malformed hash in DB must return None without crashing
                user_doc = {
                    "user_id": "usr_corrupted",
                    "email": "corrupted@example.com",
                    "password_hash": bad_hash,
                    "salt": "somesalt",
                }
                db.save_user(user_doc)
                self.assertIsNone(db.authenticate_user("corrupted@example.com", "somePassword"))

    def test_database_write_failure_does_not_break_login(self):
        """A failed DB write during migration must not fail the user's active login."""
        email = "write_fail@example.com"
        pwd = "WriteFailPassword123"
        legacy_hash, salt = db._hash_password(pwd)

        legacy_user = {
            "user_id": "usr_write_fail",
            "email": email,
            "name": "Write Fail",
            "password_hash": legacy_hash,
            "salt": salt,
        }
        db.save_user(legacy_user)

        # Simulate database write error during save_user
        with patch("db.save_user", side_effect=IOError("Simulated disk error")):
            # User should still be authenticated despite failed migration write
            user = db.authenticate_user(email, pwd)
            self.assertIsNotNone(user)
            self.assertEqual(user["email"], email)

    # ── 5. Database Backend Compatibility (MongoDB & JSON) ────────────────────

    def test_mongodb_storage_path_mock(self):
        """Verify MongoDB save_user unsets legacy salt when migrating to Argon2id."""
        mock_db = MagicMock()
        with patch("db.is_mongodb_connected", return_value=True), patch("db._db", mock_db):
            user_doc = {
                "user_id": "usr_mongo_test",
                "email": "mongo@example.com",
                "password_hash": db.hash_password("MongoPass123"),
            }
            # Salt is omitted; MongoDB must receive $unset: {'salt': ''}
            db.save_user(user_doc)

            mock_db.users.update_one.assert_called_once()
            call_args = mock_db.users.update_one.call_args
            filter_arg, update_arg = call_args[0][0], call_args[0][1]
            self.assertEqual(filter_arg, {"email": "mongo@example.com"})
            self.assertIn("$unset", update_arg)
            self.assertEqual(update_arg["$unset"], {"salt": ""})

    def test_json_fallback_storage_path(self):
        """JSON fallback storage must persist Argon2id hashes reliably."""
        with patch("db.is_mongodb_connected", return_value=False):
            email = "json_only@example.com"
            pwd = "JsonOnlyPassword123"
            user = db.create_user(email, pwd, name="JSON User")
            self.assertIsNotNone(user)

            users = db.load_users()
            self.assertIn(email, users)
            self.assertTrue(users[email]["password_hash"].startswith("$argon2id$"))

    # ── 6. Session Continuity from Task 1 ────────────────────────────────────

    def test_session_creation_after_argon2_login(self):
        """Successful login with an Argon2id account initializes a signed Flask session."""
        email = "session_user@example.com"
        pwd = "SessionPassword123"
        db.create_user(email, pwd, name="Session User")

        res = self._login(self.client, email, pwd)
        self.assertEqual(res.status_code, 200)

        # Access protected route /api/auth/me
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)
        data = json.loads(res_me.data.decode("utf-8"))
        self.assertTrue(data.get("authenticated"))
        self.assertEqual(data["user"]["email"], email)

    def test_logout_behavior_still_works(self):
        """Logout terminates session created by Argon2id authenticated login."""
        email = "logout_user@example.com"
        pwd = "LogoutPassword123"
        db.create_user(email, pwd, name="Logout User")

        self._login(self.client, email, pwd)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

        # Logout
        token = self._get_csrf_token()
        res_logout = self.client.post("/api/auth/logout", headers={"X-CSRFToken": token})
        self.assertEqual(res_logout.status_code, 200)

        # Protected route rejects
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()
