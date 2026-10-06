"""
Automated Tests for Task 7: Extracted Notification Delivery (notifications.py)
-----------------------------------------------------------------------------
Verifies:
1. build_html_email() produces valid output matching the existing template.
2. Score formatting and color thresholds remain unchanged.
3. Dry-run suppresses all outbound delivery channels.
4. Primary delivery priority: SendGrid -> Gmail -> Zapier fallback order is preserved.
5. FORCE_DIRECT_GMAIL bypasses SendGrid when enabled.
6. Telegram and Discord remain additive and always fire.
7. Missing credentials safely disable channels without raising exceptions.
8. Network and SMTP errors are caught safely and return False without crashing.
9. Backward compatibility: job_search_agent re-exports and delegation wrappers work seamlessly.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent import notifications
import job_search_agent


class TestNotifications(unittest.TestCase):
    def setUp(self):
        self.sample_job = {
            "title": "Software Engineer Intern",
            "company": "Tech Innovations Inc",
            "url": "https://example.com/jobs/123",
            "location": "Bangalore, India",
            "source": "RemoteOK",
            "score": 0.28,
        }

    # -------------------------------------------------------------------
    # 1. HTML Email Formatting & Score Visualization
    # -------------------------------------------------------------------
    def test_build_html_email_output_and_elements(self):
        """build_html_email() outputs valid HTML with job metadata, score, and CTA."""
        html = notifications.build_html_email(self.sample_job)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Software Engineer Intern", html)
        self.assertIn("Tech Innovations Inc", html)
        self.assertIn("Bangalore, India", html)
        self.assertIn("RemoteOK", html)
        self.assertIn("https://example.com/jobs/123", html)
        self.assertIn("Apply Now →", html)
        self.assertIn("Match Score: 28.0%", html)
        self.assertIn("#f59e0b", html)  # Amber color for 0.28 score
        self.assertIn("A-Jent v3 · Autonomous Job Exploration and Navigation Tool", html)

    def test_build_html_email_defaults_for_missing_fields(self):
        """build_html_email() handles sparse job dicts safely."""
        sparse_job = {}
        html = notifications.build_html_email(sparse_job)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Unknown", html)
        self.assertIn("Not specified", html)
        self.assertIn('href="#"', html)
        self.assertIn("Match Score: 0.0%", html)

    def test_score_color_thresholds(self):
        """_score_color() returns correct colors across defined thresholds."""
        # >= 0.40 -> Green
        self.assertEqual(notifications._score_color(0.50), "#22c55e")
        self.assertEqual(notifications._score_color(0.40), "#22c55e")

        # >= 0.25 -> Amber
        self.assertEqual(notifications._score_color(0.39), "#f59e0b")
        self.assertEqual(notifications._score_color(0.25), "#f59e0b")

        # >= 0.12 -> Indigo
        self.assertEqual(notifications._score_color(0.24), "#6366f1")
        self.assertEqual(notifications._score_color(0.12), "#6366f1")

        # < 0.12 -> Slate
        self.assertEqual(notifications._score_color(0.11), "#94a3b8")
        self.assertEqual(notifications._score_color(0.00), "#94a3b8")
        self.assertEqual(notifications._score_color(-0.10), "#94a3b8")

    def test_score_bar_visualization(self):
        """_score_bar() scales 0.0-0.4 to 10 blocks (filled and empty)."""
        self.assertEqual(notifications._score_bar(0.40), "██████████")
        self.assertEqual(notifications._score_bar(0.00), "░░░░░░░░░░")
        self.assertEqual(notifications._score_bar(0.20), "█████░░░░░")

    # -------------------------------------------------------------------
    # 2. Dry-Run Behavior
    # -------------------------------------------------------------------
    def test_dry_run_does_not_send_notifications(self):
        """When dry_run=True, notify() logs and returns False without dispatching."""
        with patch.object(notifications, "send_via_sendgrid") as mock_sg, \
             patch.object(notifications, "send_via_gmail") as mock_gm, \
             patch.object(notifications, "send_to_zapier") as mock_zp, \
             patch.object(notifications, "send_via_telegram") as mock_tg, \
             patch.object(notifications, "send_via_discord") as mock_dc:

            result = notifications.notify(self.sample_job, dry_run=True)

            self.assertFalse(result)
            mock_sg.assert_not_called()
            mock_gm.assert_not_called()
            mock_zp.assert_not_called()
            mock_tg.assert_not_called()
            mock_dc.assert_not_called()

    # -------------------------------------------------------------------
    # 3. Delivery Order and Fallbacks (SendGrid -> Gmail -> Zapier)
    # -------------------------------------------------------------------
    def test_sendgrid_succeeds_first_in_priority(self):
        """SendGrid takes priority when key is set and delivery succeeds."""
        with patch.object(notifications, "send_via_sendgrid", return_value=True) as mock_sg, \
             patch.object(notifications, "send_via_gmail") as mock_gm, \
             patch.object(notifications, "send_to_zapier") as mock_zp, \
             patch.object(notifications, "send_via_telegram") as mock_tg, \
             patch.object(notifications, "send_via_discord") as mock_dc:

            result = notifications.notify(
                self.sample_job,
                dry_run=False,
                sendgrid_api_key="SG.test_key",
                to_email="test@example.com",
            )

            self.assertTrue(result)
            mock_sg.assert_called_once()
            mock_gm.assert_not_called()
            mock_zp.assert_not_called()
            # Telegram & Discord remain additive
            mock_tg.assert_called_once()
            mock_dc.assert_called_once()

    def test_fallback_to_gmail_when_sendgrid_fails(self):
        """Falls back to Gmail when SendGrid fails or is unconfigured."""
        with patch.object(notifications, "send_via_sendgrid", return_value=False) as mock_sg, \
             patch.object(notifications, "send_via_gmail", return_value=True) as mock_gm, \
             patch.object(notifications, "send_to_zapier") as mock_zp, \
             patch.object(notifications, "send_via_telegram") as mock_tg, \
             patch.object(notifications, "send_via_discord") as mock_dc:

            result = notifications.notify(
                self.sample_job,
                dry_run=False,
                to_email="test@example.com",
            )

            self.assertTrue(result)
            mock_sg.assert_called_once()
            mock_gm.assert_called_once()
            mock_zp.assert_not_called()
            mock_tg.assert_called_once()
            mock_dc.assert_called_once()

    def test_fallback_to_zapier_when_gmail_fails(self):
        """Falls back to Zapier when SendGrid and Gmail both fail."""
        with patch.object(notifications, "send_via_sendgrid", return_value=False) as mock_sg, \
             patch.object(notifications, "send_via_gmail", return_value=False) as mock_gm, \
             patch.object(notifications, "send_to_zapier", return_value=True) as mock_zp, \
             patch.object(notifications, "send_via_telegram") as mock_tg, \
             patch.object(notifications, "send_via_discord") as mock_dc:

            result = notifications.notify(
                self.sample_job,
                dry_run=False,
                zapier_webhook_url="https://hooks.zapier.com/test",
            )

            self.assertTrue(result)
            mock_sg.assert_called_once()
            mock_gm.assert_called_once()
            mock_zp.assert_called_once()
            mock_tg.assert_called_once()
            mock_dc.assert_called_once()

    def test_force_direct_gmail_bypasses_sendgrid(self):
        """When FORCE_DIRECT_GMAIL is True, Gmail is called directly without SendGrid."""
        with patch.object(notifications, "send_via_sendgrid") as mock_sg, \
             patch.object(notifications, "send_via_gmail", return_value=True) as mock_gm, \
             patch.object(notifications, "send_to_zapier") as mock_zp, \
             patch.object(notifications, "send_via_telegram") as mock_tg, \
             patch.object(notifications, "send_via_discord") as mock_dc:

            result = notifications.notify(
                self.sample_job,
                dry_run=False,
                force_direct_gmail=True,
                to_email="test@example.com",
            )

            self.assertTrue(result)
            mock_sg.assert_not_called()
            mock_gm.assert_called_once()
            mock_zp.assert_not_called()
            mock_tg.assert_called_once()
            mock_dc.assert_called_once()

    # -------------------------------------------------------------------
    # 4. Supplemental Additive Channels (Telegram and Discord)
    # -------------------------------------------------------------------
    def test_telegram_and_discord_additive_on_total_primary_failure(self):
        """Telegram and Discord always fire even when all primary channels fail."""
        with patch.object(notifications, "send_via_sendgrid", return_value=False), \
             patch.object(notifications, "send_via_gmail", return_value=False), \
             patch.object(notifications, "send_to_zapier", return_value=False), \
             patch.object(notifications, "send_via_telegram") as mock_tg, \
             patch.object(notifications, "send_via_discord") as mock_dc:

            result = notifications.notify(self.sample_job, dry_run=False)

            self.assertFalse(result)
            mock_tg.assert_called_once()
            mock_dc.assert_called_once()

    # -------------------------------------------------------------------
    # 5. Missing Credentials Disable Channels Safely
    # -------------------------------------------------------------------
    def test_send_via_sendgrid_missing_credentials(self):
        """send_via_sendgrid returns False without making network request if key missing."""
        with patch.object(notifications._SESSION, "post") as mock_post:
            result = notifications.send_via_sendgrid(
                self.sample_job,
                to_address="test@example.com",
                api_key="",
            )
            self.assertFalse(result)
            mock_post.assert_not_called()

    def test_send_via_gmail_missing_credentials(self):
        """send_via_gmail returns False without opening SMTP if credentials missing."""
        with patch("smtplib.SMTP_SSL") as mock_smtp:
            result = notifications.send_via_gmail(
                self.sample_job,
                to_address="",
                gmail_address="",
                app_password="",
            )
            self.assertFalse(result)
            mock_smtp.assert_not_called()

    def test_send_to_zapier_missing_url(self):
        """send_to_zapier returns False without request if url is empty or placeholder."""
        with patch.object(notifications._SESSION, "post") as mock_post:
            # Placeholder URL
            self.assertFalse(notifications.send_to_zapier(self.sample_job, webhook_url="PASTE_YOUR_ZAPIER_CATCH_HOOK_URL_HERE"))
            # Empty URL
            self.assertFalse(notifications.send_to_zapier(self.sample_job, webhook_url=""))
            mock_post.assert_not_called()

    def test_send_via_telegram_missing_credentials(self):
        """send_via_telegram returns False if bot token or chat ID is empty."""
        with patch.object(notifications._SESSION, "post") as mock_post:
            self.assertFalse(notifications.send_via_telegram(self.sample_job, bot_token="", chat_id="12345"))
            self.assertFalse(notifications.send_via_telegram(self.sample_job, bot_token="token", chat_id=""))
            mock_post.assert_not_called()

    def test_send_via_discord_missing_url(self):
        """send_via_discord returns False if webhook URL is empty."""
        with patch.object(notifications._SESSION, "post") as mock_post:
            self.assertFalse(notifications.send_via_discord(self.sample_job, webhook_url=""))
            mock_post.assert_not_called()

    # -------------------------------------------------------------------
    # 6. Network Dispatch & Safe Error Handling (No Secret Leaks)
    # -------------------------------------------------------------------
    def test_sendgrid_dispatch_success(self):
        """send_via_sendgrid sends expected JSON payload and authorization header."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifications._SESSION, "post", return_value=mock_resp) as mock_post:
            ok = notifications.send_via_sendgrid(
                self.sample_job,
                to_address="candidate@example.com",
                api_key="SG.test_key_123",
                from_address="sender@example.com",
            )
            self.assertTrue(ok)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer SG.test_key_123")
            payload = call_kwargs["json"]
            self.assertEqual(payload["personalizations"][0]["to"][0]["email"], "candidate@example.com")
            self.assertEqual(payload["from"]["email"], "sender@example.com")

    def test_sendgrid_network_error_handled_safely(self):
        """send_via_sendgrid catches exceptions and returns False safely."""
        with patch.object(notifications._SESSION, "post", side_effect=Exception("Connection timed out")):
            ok = notifications.send_via_sendgrid(
                self.sample_job,
                to_address="candidate@example.com",
                api_key="SG.test_key_123",
            )
            self.assertFalse(ok)

    def test_gmail_dispatch_success(self):
        """send_via_gmail logs in and sends MIME message via SMTP_SSL."""
        mock_server = MagicMock()
        mock_server_context = MagicMock()
        mock_server_context.__enter__.return_value = mock_server

        with patch("smtplib.SMTP_SSL", return_value=mock_server_context) as mock_smtp:
            ok = notifications.send_via_gmail(
                self.sample_job,
                to_address="to@example.com",
                gmail_address="user@gmail.com",
                app_password="secret_password",
            )
            self.assertTrue(ok)
            mock_smtp.assert_called_once_with("smtp.gmail.com", 465, timeout=15)
            mock_server.login.assert_called_once_with("user@gmail.com", "secret_password")
            mock_server.sendmail.assert_called_once()

    def test_gmail_smtp_error_handled_safely(self):
        """send_via_gmail catches SMTP exceptions safely."""
        with patch("smtplib.SMTP_SSL", side_effect=Exception("SMTP authentication failed")):
            ok = notifications.send_via_gmail(
                self.sample_job,
                to_address="to@example.com",
                gmail_address="user@gmail.com",
                app_password="secret_password",
            )
            self.assertFalse(ok)

    def test_telegram_dispatch_success(self):
        """send_via_telegram sends Markdown message to Telegram API."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifications._SESSION, "post", return_value=mock_resp) as mock_post:
            ok = notifications.send_via_telegram(
                self.sample_job,
                bot_token="test_bot_token",
                chat_id="12345678",
            )
            self.assertTrue(ok)
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            self.assertIn("bottest_bot_token/sendMessage", call_url)
            payload = mock_post.call_args[1]["json"]
            self.assertEqual(payload["chat_id"], "12345678")
            self.assertEqual(payload["parse_mode"], "Markdown")
            self.assertIn("Software Engineer Intern", payload["text"])

    def test_discord_dispatch_success(self):
        """send_via_discord sends embed to Discord Webhook."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifications._SESSION, "post", return_value=mock_resp) as mock_post:
            ok = notifications.send_via_discord(
                self.sample_job,
                webhook_url="https://discord.com/api/webhooks/123/xyz",
            )
            self.assertTrue(ok)
            mock_post.assert_called_once()
            payload = mock_post.call_args[1]["json"]
            self.assertIn("embeds", payload)
            embed = payload["embeds"][0]
            self.assertIn("Software Engineer Intern", embed["title"])
            self.assertEqual(embed["url"], "https://example.com/jobs/123")

    # -------------------------------------------------------------------
    # 7. Backward Compatibility via job_search_agent.py
    # -------------------------------------------------------------------
    def test_job_search_agent_backward_compatibility(self):
        """All notification symbols imported from job_search_agent remain available and work."""
        # Constants
        self.assertIsNotNone(job_search_agent.ZAPIER_WEBHOOK_URL)
        self.assertIsNotNone(job_search_agent.GMAIL_ADDRESS)
        self.assertIsNotNone(job_search_agent.FORCE_DIRECT_GMAIL)
        self.assertIsNotNone(job_search_agent._SCORE_COLORS)

        # Functions
        self.assertTrue(callable(job_search_agent._score_color))
        self.assertTrue(callable(job_search_agent._score_bar))
        self.assertTrue(callable(job_search_agent.build_html_email))
        self.assertTrue(callable(job_search_agent.send_to_zapier))
        self.assertTrue(callable(job_search_agent.send_via_sendgrid))
        self.assertTrue(callable(job_search_agent.send_via_gmail))
        self.assertTrue(callable(job_search_agent.send_via_telegram))
        self.assertTrue(callable(job_search_agent.send_via_discord))
        self.assertTrue(callable(job_search_agent.notify))

        # Output equality
        self.assertEqual(
            job_search_agent.build_html_email(self.sample_job),
            notifications.build_html_email(self.sample_job)
        )
        self.assertEqual(
            job_search_agent._score_color(0.35),
            notifications._score_color(0.35)
        )
        self.assertEqual(
            job_search_agent._score_bar(0.35),
            notifications._score_bar(0.35)
        )

        # notify() call delegation
        with patch.object(notifications, "notify", return_value=True) as mock_notify:
            res = job_search_agent.notify(self.sample_job, to_email="sub@example.com")
            self.assertTrue(res)
            mock_notify.assert_called_once()
            self.assertEqual(mock_notify.call_args[1]["to_email"], "sub@example.com")


if __name__ == "__main__":
    unittest.main()
