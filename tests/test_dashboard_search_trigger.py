"""
Tests for Manual Job Search Trigger After Resume Upload.

Covers:
1. Unauthenticated users cannot start a job search (401 error).
2. Authenticated user without an uploaded resume receives 400 error.
3. Authenticated user with a valid resume starts a job search (200 success).
4. Request delegates to the existing job_search_agent pipeline.
5. Repeated/concurrent start requests for the same user prevent duplicate searches (409 Conflict).
6. GET /api/search-status reports active vs idle search state correctly.
7. job_search_agent reusable orchestration (evaluate_jobs_for_user, run_search_for_user, run_once).
"""

import sys
import json
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
import job_search_agent
from dashboard.app import app, limiter, _active_searches, _active_searches_lock


class TestDashboardSearchTrigger(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False  # Simplify test calls where CSRF is not the test focus
        app.config["SYNCHRONOUS_SEARCH"] = True  # Run synchronously in test mode
        self.client = app.test_client()

        # Reset rate limiter
        limiter.reset()

        # Clean active searches
        with _active_searches_lock:
            _active_searches.clear()

        # Seed test user
        self.user_email = "search_tester@example.com"
        self.user_pass = "TestPass123!"
        self.user = db.create_user(self.user_email, self.user_pass, name="Search Tester")
        if not self.user:
            self.user = db.load_users()[self.user_email]

        # Ensure clean state without resume
        self.user["resume_text"] = ""
        self.user["resumes"] = []
        self.user["primary_resume_id"] = None
        db.save_user(self.user)

    def tearDown(self):
        with _active_searches_lock:
            _active_searches.clear()

    def _login(self, email=None, password=None):
        return self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": email or self.user_email, "password": password or self.user_pass}),
            content_type="application/json",
        )

    def test_unauthenticated_cannot_start_search(self):
        """Unauthenticated user receives 401 when calling /api/start-search."""
        res = self.client.post("/api/start-search")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertIn("error", data)

    def test_user_without_resume_receives_error(self):
        """Authenticated user without any uploaded resume receives 400 error."""
        self._login()
        res = self.client.post("/api/start-search")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("status"), "error")
        self.assertIn("Please upload a resume", data.get("message", ""))

    @patch("job_search_agent.run_search_for_user")
    def test_authenticated_user_with_resume_starts_search(self, mock_run_search):
        """Authenticated user with a valid primary resume can trigger a search."""
        self.user["resume_text"] = "Python software engineer with AWS and Flask experience."
        self.user["resumes"] = [{
            "id": "res_123",
            "filename": "my_resume.pdf",
            "resume_text": self.user["resume_text"],
            "is_primary": True,
        }]
        self.user["primary_resume_id"] = "res_123"
        db.save_user(self.user)

        self._login()
        res = self.client.post("/api/start-search")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "started")
        self.assertEqual(data.get("message"), "Job search started")

        # Verify delegation to pipeline
        mock_run_search.assert_called_once()
        called_user = mock_run_search.call_args[0][0]
        self.assertEqual(called_user.get("user_id"), self.user.get("user_id"))

    def test_repeated_start_requests_prevent_duplicate_searches(self):
        """If a search is already active for this user, returns 409 Conflict."""
        self.user["resume_text"] = "Experienced backend developer."
        db.save_user(self.user)

        self._login()

        # Simulate currently active search
        uid = self.user.get("user_id")
        with _active_searches_lock:
            _active_searches.add(uid)

        res = self.client.post("/api/start-search")
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("status"), "already_running")
        self.assertIn("already running", data.get("message", ""))

    def test_search_status_endpoint(self):
        """GET /api/search-status reports accurate running state."""
        self._login()
        res = self.client.get("/api/search-status")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.get_json().get("running"))
        self.assertEqual(res.get_json().get("status"), "idle")

        uid = self.user.get("user_id")
        with _active_searches_lock:
            _active_searches.add(uid)

        res = self.client.get("/api/search-status")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("running"))
        self.assertEqual(res.get_json().get("status"), "running")

    def test_job_search_agent_orchestration(self):
        """Verify evaluate_jobs_for_user and run_search_for_user directly."""
        import uuid
        job_id = f"test_job_{uuid.uuid4().hex}"
        mock_jobs = [
            {
                "id": job_id,
                "title": "Junior Python Backend Engineer",
                "company": "Tech Corp",
                "url": "https://example.com/testjob",
                "source": "RemoteOK",
                "location": "Remote",
                "description": "Looking for junior entry level Python, Django, Flask, PostgreSQL engineer.",
            }
        ]

        test_user = {
            "user_id": "test_uid_99",
            "email": "test99@example.com",
            "resume_text": "Junior Python developer experienced in Django, Flask, PostgreSQL.",
            "resumes": [],
        }

        # Dry run search with mock pre-fetched jobs
        ranked = job_search_agent.evaluate_jobs_for_user(
            sub=test_user,
            all_jobs=mock_jobs,
            source_counts={"RemoteOK": 1},
            dry_run=True,
        )

        self.assertIsInstance(ranked, list)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], job_id)
        self.assertGreater(ranked[0].get("score", 0), 0)

        # Also verify run_search_for_user accepts pre-fetched jobs and dry_run
        ranked_run = job_search_agent.run_search_for_user(
            user=test_user,
            all_jobs=mock_jobs,
            source_counts={"RemoteOK": 1},
            dry_run=True,
        )
        self.assertEqual(len(ranked_run), 1)

    @patch("job_search_agent.run_search_for_user")
    def test_run_once_with_target_user_id(self, mock_run_search):
        """run_once delegates to run_search_for_user when target_user_id is passed."""
        mock_run_search.return_value = [{"id": "job_1"}, {"id": "job_2"}]
        count = job_search_agent.run_once(target_user_id="alice_123")
        self.assertEqual(count, 2)
        mock_run_search.assert_called_once_with("alice_123")

    def test_background_thread_cleans_up_active_searches(self):
        """Verify asynchronous background thread execution and proper active search cleanup."""
        import time
        app.config["SYNCHRONOUS_SEARCH"] = False
        self.user["resume_text"] = "Backend dev"
        db.save_user(self.user)

        self._login()
        with patch("job_search_agent.run_search_for_user") as mock_search:
            res = self.client.post("/api/start-search")
            self.assertEqual(res.status_code, 200)
            # Allow background thread a moment to finish
            time.sleep(0.1)
            mock_search.assert_called_once()
            # Ensure user was removed from _active_searches
            uid = self.user.get("user_id")
            with _active_searches_lock:
                self.assertNotIn(uid, _active_searches)

    def test_csrf_protection_on_start_search(self):
        """Verify CSRF token is required when WTF_CSRF_ENABLED is active."""
        app.config["WTF_CSRF_ENABLED"] = True
        self.user["resume_text"] = "Backend dev"
        db.save_user(self.user)

        # 1. Login without CSRF should fail if CSRF enabled, but login can use token
        csrf_res = self.client.get("/api/csrf-token")
        token = csrf_res.get_json()["csrf_token"]

        login_res = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": self.user_email, "password": self.user_pass}),
            headers={"X-CSRFToken": token, "Content-Type": "application/json"},
        )
        self.assertEqual(login_res.status_code, 200)

        # 2. Call /api/start-search without CSRF token -> Rejected (400)
        res_no_csrf = self.client.post("/api/start-search")
        self.assertEqual(res_no_csrf.status_code, 400)

        # 3. Call with valid post-login CSRF token -> Accepted (200)
        post_login_token = self.client.get("/api/csrf-token").get_json()["csrf_token"]
        with patch("job_search_agent.run_search_for_user"):
            res_with_csrf = self.client.post(
                "/api/start-search",
                headers={"X-CSRFToken": post_login_token},
            )
            self.assertEqual(res_with_csrf.status_code, 200)


if __name__ == "__main__":
    unittest.main()
