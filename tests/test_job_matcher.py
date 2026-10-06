"""
Automated Tests for Task 8: Extracted Job Matching & Scoring (job_matcher.py)
----------------------------------------------------------------------------
Verifies:
1. expand_synonyms() correctly expands abbreviations, respects word boundaries, and is case-insensitive.
2. rank_by_similarity() handles empty job lists cleanly returning [].
3. rank_by_similarity() assigns 'score' to jobs, rounds to 4 decimal places, and caps at 1.0.
4. Results are sorted in descending order of score.
5. Similarity threshold filters out jobs below the cutoff.
6. Title boosting multiplies score by TITLE_BOOST_MULTIPLIER when top resume keywords appear in title.
7. Original job dictionaries are mutated with the 'score' key.
8. Default configuration values and explicit parameter overrides work as expected.
9. Backward compatibility: job_search_agent exports and delegation wrappers function identically.
10. Deterministic regression check: job_matcher and job_search_agent yield identical scoring and ordering.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent import job_matcher
import job_search_agent


class TestJobMatcher(unittest.TestCase):
    def setUp(self):
        self.sample_resume = (
            "Experienced Python backend developer skilled in FastAPI, Django, PostgreSQL, "
            "Docker, Kubernetes, and machine learning with PyTorch and Scikit-Learn. "
            "Built distributed microservices, REST APIs, and data pipelines on AWS."
        )

        self.sample_jobs = [
            {
                "id": "job_1",
                "title": "Senior Python Backend Engineer",
                "company": "DataCloud Corp",
                "description": "We are seeking a senior Python developer with strong experience in FastAPI, PostgreSQL, and AWS.",
            },
            {
                "id": "job_2",
                "title": "Machine Learning Engineer",
                "company": "AI Dynamics",
                "description": "Join our AI team to build models using PyTorch, Scikit-Learn, and Python for computer vision and ML.",
            },
            {
                "id": "job_3",
                "title": "Frontend React Developer",
                "company": "WebFlow Ltd",
                "description": "Looking for CSS, HTML, React, Next.js, and Tailwind UI developers for web applications.",
            },
            {
                "id": "job_4",
                "title": "Executive Pastry Chef",
                "company": "BakeHouse",
                "description": "Baking artisan sourdough breads, cakes, pastries, and managing morning kitchen staff.",
            },
        ]

    # -------------------------------------------------------------------
    # 1. Synonym Expansion
    # -------------------------------------------------------------------
    def test_expand_synonyms_abbreviations(self):
        """expand_synonyms() replaces defined abbreviations with full expressions."""
        text = "Looking for a swe with ml, sde, and api experience in aws and k8s."
        expanded = job_matcher.expand_synonyms(text)

        self.assertIn("software engineer", expanded)
        self.assertIn("machine learning", expanded)
        self.assertIn("software development engineer", expanded)
        self.assertIn("application programming interface", expanded)
        self.assertIn("amazon web services", expanded)
        self.assertIn("kubernetes", expanded)

    def test_expand_synonyms_case_insensitivity(self):
        """expand_synonyms() is case-insensitive and returns lowercased text."""
        text = "SWE with ML and NLP experience"
        expanded = job_matcher.expand_synonyms(text)

        self.assertIn("software engineer", expanded)
        self.assertIn("machine learning", expanded)
        self.assertIn("natural language processing", expanded)
        self.assertEqual(expanded, expanded.lower())

    def test_expand_synonyms_word_boundaries(self):
        """expand_synonyms() respects word boundaries and avoids replacing substrings."""
        text = "The rapid answers made him smile while grasping the helmet."
        expanded = job_matcher.expand_synonyms(text)

        # 'api' in 'rapid' should not expand
        self.assertIn("rapid", expanded)
        # 'swe' in 'answers' should not expand
        self.assertIn("answers", expanded)
        # 'ml' in 'smile' or 'helmet' should not expand
        self.assertIn("smile", expanded)
        self.assertIn("helmet", expanded)

    # -------------------------------------------------------------------
    # 2. Ranking Algorithm & Invariants
    # -------------------------------------------------------------------
    def test_rank_by_similarity_empty_jobs(self):
        """rank_by_similarity() with empty job list returns []."""
        self.assertEqual(job_matcher.rank_by_similarity(self.sample_resume, []), [])

    def test_rank_by_similarity_scoring_and_rounding(self):
        """Jobs receive a float 'score' rounded to 4 decimal places."""
        jobs_copy = [dict(j) for j in self.sample_jobs]
        ranked = job_matcher.rank_by_similarity(self.sample_resume, jobs_copy)

        self.assertGreater(len(ranked), 0)
        for job in ranked:
            self.assertIn("score", job)
            self.assertIsInstance(job["score"], float)
            # Verify rounded to at most 4 decimal places
            score_str = str(job["score"])
            if "." in score_str:
                decimals = len(score_str.split(".")[1])
                self.assertLessEqual(decimals, 4)

    def test_rank_by_similarity_descending_order(self):
        """Results are sorted strictly descending by score."""
        jobs_copy = [dict(j) for j in self.sample_jobs]
        ranked = job_matcher.rank_by_similarity(self.sample_resume, jobs_copy)

        scores = [j["score"] for j in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rank_by_similarity_threshold_filtering(self):
        """Jobs with score below the threshold are filtered out."""
        jobs_copy = [dict(j) for j in self.sample_jobs]
        # Pastry Chef should have near-zero similarity to Python backend resume
        ranked = job_matcher.rank_by_similarity(
            self.sample_resume,
            jobs_copy,
            similarity_threshold=0.12,
        )

        titles = [j["title"] for j in ranked]
        self.assertNotIn("Executive Pastry Chef", titles)
        for job in ranked:
            self.assertGreaterEqual(job["score"], 0.12)

    def test_rank_by_similarity_title_boost(self):
        """Title containing a top resume keyword receives a score boost."""
        resume = "python python python backend developer flask django"
        # Two jobs with identical descriptions, but one has 'python' in the title
        job_with_title_match = {
            "title": "Python Developer",
            "description": "Building web apps using databases and cloud infrastructure.",
        }
        job_without_title_match = {
            "title": "General Associate",
            "description": "Building web apps using databases and cloud infrastructure.",
        }

        # Run with title boost multiplier = 1.4
        res_boosted = job_matcher.rank_by_similarity(
            resume,
            [job_with_title_match],
            similarity_threshold=0.0,
            title_boost_multiplier=1.4,
        )
        # Run with title boost multiplier = 1.0 (no boost)
        res_unboosted = job_matcher.rank_by_similarity(
            resume,
            [job_without_title_match],
            similarity_threshold=0.0,
            title_boost_multiplier=1.0,
        )

        self.assertGreater(res_boosted[0]["score"], res_unboosted[0]["score"])

    def test_rank_by_similarity_score_capped_at_one(self):
        """Score does not exceed 1.0 even after large title boost."""
        resume = "python developer python developer"
        job = {
            "title": "Python Developer",
            "description": "python developer python developer",
        }
        ranked = job_matcher.rank_by_similarity(
            resume,
            [job],
            similarity_threshold=0.0,
            title_boost_multiplier=5.0,  # Unusually large multiplier
        )
        self.assertLessEqual(ranked[0]["score"], 1.0)

    def test_rank_by_similarity_mutates_original_dict(self):
        """rank_by_similarity() adds 'score' directly to the input job dicts."""
        job = {
            "title": "Python Engineer",
            "description": "Python, Django, FastAPI",
        }
        self.assertNotIn("score", job)
        ranked = job_matcher.rank_by_similarity(self.sample_resume, [job], similarity_threshold=0.0)
        self.assertIn("score", job)
        self.assertEqual(ranked[0]["score"], job["score"])

    # -------------------------------------------------------------------
    # 3. Configuration Dependencies & Defaults
    # -------------------------------------------------------------------
    def test_configuration_defaults(self):
        """Default configuration values match expected repository settings."""
        # Active runtime values match job_search_agent
        self.assertEqual(job_matcher.SIMILARITY_THRESHOLD, job_search_agent.SIMILARITY_THRESHOLD)
        self.assertEqual(job_matcher.TITLE_BOOST_MULTIPLIER, job_search_agent.TITLE_BOOST_MULTIPLIER)

        # Baseline fallback defaults when no config override exists
        with patch.dict("a_jent.job_matcher._cfg", {}, clear=True), patch.dict("os.environ", {}, clear=True):
            self.assertEqual(job_matcher._get("SIMILARITY_THRESHOLD", 0.12, float), 0.12)
            self.assertEqual(job_matcher._get("TITLE_BOOST_MULTIPLIER", 1.4, float), 1.4)

    def test_configuration_parameter_overrides(self):
        """Explicit threshold and multiplier parameters override defaults."""
        jobs_copy = [dict(j) for j in self.sample_jobs]

        # Very high threshold filters out all jobs
        ranked_none = job_matcher.rank_by_similarity(
            self.sample_resume,
            jobs_copy,
            similarity_threshold=0.99,
        )
        self.assertEqual(len(ranked_none), 0)

        # Zero threshold includes all non-zero jobs
        ranked_all = job_matcher.rank_by_similarity(
            self.sample_resume,
            jobs_copy,
            similarity_threshold=0.0,
        )
        self.assertGreater(len(ranked_all), len(ranked_none))

    # -------------------------------------------------------------------
    # 4. Backward Compatibility & Deterministic Equivalence
    # -------------------------------------------------------------------
    def test_job_search_agent_backward_compatibility(self):
        """job_search_agent re-exports all matching symbols and delegates properly."""
        # Constants
        self.assertEqual(job_search_agent.SIMILARITY_THRESHOLD, job_matcher.SIMILARITY_THRESHOLD)
        self.assertEqual(job_search_agent.TITLE_BOOST_MULTIPLIER, job_matcher.TITLE_BOOST_MULTIPLIER)
        self.assertEqual(job_search_agent.SYNONYM_MAP, job_matcher.SYNONYM_MAP)

        # Functions
        self.assertTrue(callable(job_search_agent.expand_synonyms))
        self.assertTrue(callable(job_search_agent.rank_by_similarity))

        # expand_synonyms equality
        test_str = "ML and SWE roles"
        self.assertEqual(
            job_search_agent.expand_synonyms(test_str),
            job_matcher.expand_synonyms(test_str),
        )

    def test_deterministic_equivalence_between_modules(self):
        """job_matcher and job_search_agent yield identical scores and order."""
        jobs_for_matcher = [dict(j) for j in self.sample_jobs]
        jobs_for_agent = [dict(j) for j in self.sample_jobs]

        res_matcher = job_matcher.rank_by_similarity(self.sample_resume, jobs_for_matcher)
        res_agent = job_search_agent.rank_by_similarity(self.sample_resume, jobs_for_agent)

        self.assertEqual(len(res_matcher), len(res_agent))
        for m_job, a_job in zip(res_matcher, res_agent):
            self.assertEqual(m_job["id"], a_job["id"])
            self.assertEqual(m_job["score"], a_job["score"])


if __name__ == "__main__":
    unittest.main()
