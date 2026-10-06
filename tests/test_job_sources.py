"""
Automated Tests for Task 6: Extracted Job Source Discovery (job_sources.py)
---------------------------------------------------------------------------
Verifies:
1. fetch_all_sources() returns the expected contract: tuple(jobs: list, source_counts: dict).
2. Source fetchers normalize responses into the expected job dictionary fields:
   - id, title, company, url, location, description, source, posted_at.
3. Source configuration controls optional sources (Greenhouse, Lever).
4. Browser scrapers remain disabled when BROWSER_ENABLED=false.
5. job_search_agent backward-compatibility imports and delegation work properly.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent import job_sources
import job_search_agent


class TestJobSources(unittest.TestCase):
    def test_fetch_all_sources_return_contract_and_shape(self):
        """fetch_all_sources() returns a tuple of (jobs: list, source_counts: dict)."""
        sample_job = {
            "id": "mock_1",
            "title": "Software Engineer Intern",
            "company": "TestCorp",
            "url": "https://example.com/job/1",
            "location": "Remote",
            "description": "Building cool things",
            "source": "MockSource",
            "posted_at": "2026-10-01",
        }

        with patch("a_jent.job_sources.fetch_remoteok", return_value=[sample_job]), \
             patch("a_jent.job_sources.fetch_arbeitnow", return_value=[]), \
             patch("a_jent.job_sources.fetch_jobicy", return_value=[]), \
             patch("a_jent.job_sources.fetch_himalayas", return_value=[]), \
             patch("a_jent.job_sources.fetch_remotive", return_value=[]), \
             patch("a_jent.job_sources.fetch_hn_whoishiring", return_value=[]), \
             patch("a_jent.job_sources.fetch_wwr_rss", return_value=[]), \
             patch("a_jent.job_sources.fetch_linkedin_rss", return_value=[]), \
             patch("a_jent.job_sources.fetch_browser_sources", return_value=([], {})):

            res = job_sources.fetch_all_sources(
                greenhouse_slugs=[],
                lever_slugs=[],
                browser_enabled=False,
            )

            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 2)
            jobs, source_counts = res
            self.assertIsInstance(jobs, list)
            self.assertIsInstance(source_counts, dict)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Software Engineer Intern")
            self.assertEqual(source_counts.get("RemoteOK"), 1)

    def test_source_fetchers_produce_expected_job_fields(self):
        """Individual source fetchers parse and produce the standard job dictionary format."""
        expected_fields = {"id", "title", "company", "url", "location", "description", "source", "posted_at"}

        # 1. RemoteOK
        mock_resp_remoteok = MagicMock()
        mock_resp_remoteok.json.return_value = [{
            "id": 12345,
            "position": "Backend Developer Intern",
            "company": "Acme Inc",
            "url": "https://remoteok.com/job/12345",
            "description": "Python, Django backend work.",
            "date": "2026-10-01T12:00:00Z",
        }]
        with patch.object(job_sources, "_safe_get", return_value=mock_resp_remoteok):
            rok_jobs = job_sources.fetch_remoteok()
            self.assertEqual(len(rok_jobs), 1)
            self.assertTrue(expected_fields.issubset(rok_jobs[0].keys()))
            self.assertEqual(rok_jobs[0]["id"], "remoteok_12345")
            self.assertEqual(rok_jobs[0]["source"], "RemoteOK")

        # 2. Arbeitnow
        mock_resp_arbeitnow = MagicMock()
        mock_resp_arbeitnow.json.return_value = {
            "data": [{
                "slug": "arbeit-slug-99",
                "title": "Full Stack Intern",
                "company_name": "Berlin Tech",
                "url": "https://arbeitnow.com/jobs/99",
                "location": "Berlin, Germany",
                "description": "TypeScript & Node.js",
                "created_at": 1700000000,
            }]
        }
        with patch.object(job_sources, "_safe_get", return_value=mock_resp_arbeitnow):
            an_jobs = job_sources.fetch_arbeitnow()
            self.assertEqual(len(an_jobs), 1)
            self.assertTrue(expected_fields.issubset(an_jobs[0].keys()))
            self.assertEqual(an_jobs[0]["id"], "arbeitnow_arbeit-slug-99")
            self.assertEqual(an_jobs[0]["source"], "Arbeitnow")

        # 3. Jobicy
        mock_resp_jobicy = MagicMock()
        mock_resp_jobicy.json.return_value = {
            "jobs": [{
                "id": 456,
                "jobTitle": "Data Analyst Intern",
                "companyName": "Data Co",
                "url": "https://jobicy.com/jobs/456",
                "jobGeo": "Remote",
                "jobExcerpt": "SQL, Tableau",
                "pubDate": "2026-10-01",
            }]
        }
        with patch.object(job_sources, "_safe_get", return_value=mock_resp_jobicy):
            jobicy_jobs = job_sources.fetch_jobicy()
            self.assertEqual(len(jobicy_jobs), 1)
            self.assertTrue(expected_fields.issubset(jobicy_jobs[0].keys()))
            self.assertEqual(jobicy_jobs[0]["id"], "jobicy_456")
            self.assertEqual(jobicy_jobs[0]["source"], "Jobicy")

        # 4. Himalayas
        mock_resp_himalayas = MagicMock()
        mock_resp_himalayas.json.return_value = [{
            "guid": "him-789",
            "title": "Machine Learning Intern",
            "companyName": "AI Labs",
            "applicationLink": "https://himalayas.app/jobs/789",
            "location": "Worldwide",
            "description": "PyTorch, scikit-learn",
            "pubDate": "2026-10-02",
        }]
        with patch.object(job_sources, "_safe_get", return_value=mock_resp_himalayas):
            him_jobs = job_sources.fetch_himalayas()
            self.assertEqual(len(him_jobs), 1)
            self.assertTrue(expected_fields.issubset(him_jobs[0].keys()))
            self.assertEqual(him_jobs[0]["id"], "himalayas_him-789")
            self.assertEqual(him_jobs[0]["source"], "Himalayas")

        # 5. Greenhouse
        mock_resp_gh = MagicMock()
        mock_resp_gh.json.return_value = {
            "jobs": [{
                "id": 1001,
                "title": "SWE Intern - Summer 2026",
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1001",
                "location": {"name": "Remote, US"},
                "content": "<p>Write payment infrastructure.</p>",
                "updated_at": "2026-10-01T00:00:00Z",
            }]
        }
        with patch.object(job_sources, "_safe_get", return_value=mock_resp_gh):
            gh_jobs = job_sources.fetch_greenhouse(["stripe"])
            self.assertEqual(len(gh_jobs), 1)
            self.assertTrue(expected_fields.issubset(gh_jobs[0].keys()))
            self.assertEqual(gh_jobs[0]["id"], "greenhouse_1001")
            self.assertEqual(gh_jobs[0]["source"], "Greenhouse (stripe)")

        # 6. Lever
        mock_resp_lever = MagicMock()
        mock_resp_lever.json.return_value = [{
            "id": "lever-2002",
            "text": "Frontend Intern",
            "hostedUrl": "https://jobs.lever.co/netflix/lever-2002",
            "categories": {"location": "Los Gatos, CA"},
            "descriptionPlain": "Build streaming UI.",
        }]
        with patch.object(job_sources, "_safe_get", return_value=mock_resp_lever):
            lever_jobs = job_sources.fetch_lever(["netflix"])
            self.assertEqual(len(lever_jobs), 1)
            self.assertTrue(expected_fields.issubset(lever_jobs[0].keys()))
            self.assertEqual(lever_jobs[0]["id"], "lever_lever-2002")
            self.assertEqual(lever_jobs[0]["source"], "Lever (netflix)")

    def test_source_configuration_controls_optional_sources(self):
        """Greenhouse and Lever sources are fetched when slugs are provided and omitted when empty."""
        with patch("a_jent.job_sources.fetch_greenhouse", return_value=[{"id": "gh_1"}]) as mock_gh, \
             patch("a_jent.job_sources.fetch_lever", return_value=[{"id": "lev_1"}]) as mock_lev, \
             patch("a_jent.job_sources._safe_get", return_value=None):

            # Call with slugs
            jobs, counts = job_sources.fetch_all_sources(
                greenhouse_slugs=["company_a"],
                lever_slugs=["company_b"],
                browser_enabled=False,
            )
            mock_gh.assert_called_once_with(["company_a"])
            mock_lev.assert_called_once_with(["company_b"])
            self.assertIn("Greenhouse", counts)
            self.assertIn("Lever", counts)

            # Call without slugs
            mock_gh.reset_mock()
            mock_lev.reset_mock()
            jobs2, counts2 = job_sources.fetch_all_sources(
                greenhouse_slugs=[],
                lever_slugs=[],
                browser_enabled=False,
            )
            mock_gh.assert_not_called()
            mock_lev.assert_not_called()
            self.assertNotIn("Greenhouse", counts2)
            self.assertNotIn("Lever", counts2)

    def test_browser_sources_remain_disabled_when_browser_enabled_false(self):
        """When BROWSER_ENABLED=false, fetch_browser_sources() exits early without invoking Playwright."""
        jobs, counts = job_sources.fetch_browser_sources(enabled=False)
        self.assertEqual(jobs, [])
        self.assertEqual(counts, {})

    def test_job_search_agent_backward_compatibility(self):
        """job_search_agent delegates fetch_all_sources and preserves all public exports."""
        # 1. Functions and session exported from job_search_agent
        self.assertIs(job_search_agent._SESSION, job_sources._SESSION)
        self.assertIs(job_search_agent.fetch_remoteok, job_sources.fetch_remoteok)
        self.assertIs(job_search_agent.fetch_arbeitnow, job_sources.fetch_arbeitnow)
        self.assertIs(job_search_agent.fetch_jobicy, job_sources.fetch_jobicy)
        self.assertIs(job_search_agent.fetch_himalayas, job_sources.fetch_himalayas)
        self.assertIs(job_search_agent.fetch_remotive, job_sources.fetch_remotive)
        self.assertIs(job_search_agent.fetch_hn_whoishiring, job_sources.fetch_hn_whoishiring)
        self.assertIs(job_search_agent.fetch_wwr_rss, job_sources.fetch_wwr_rss)
        self.assertIs(job_search_agent.fetch_linkedin_rss, job_sources.fetch_linkedin_rss)
        self.assertIs(job_search_agent.fetch_greenhouse, job_sources.fetch_greenhouse)
        self.assertIs(job_search_agent.fetch_lever, job_sources.fetch_lever)
        self.assertIs(job_search_agent.fetch_browser_sources, job_sources.fetch_browser_sources)

        # 2. Delegation of fetch_all_sources from job_search_agent
        with patch("a_jent.job_sources.fetch_all_sources", return_value=(["mock_job"], {"Mock": 1})) as mock_fas:
            res = job_search_agent.fetch_all_sources(browser_enabled=False)
            mock_fas.assert_called_once()
            self.assertEqual(res, (["mock_job"], {"Mock": 1}))


if __name__ == "__main__":
    unittest.main()
