"""
Automated Tests for Task 12: Package Consolidation (a_jent)
-----------------------------------------------------------
Verifies:
1. `a_jent` package imports successfully.
2. All 5 consolidated modules import successfully from `a_jent`:
   - a_jent.job_sources
   - a_jent.resume_parser
   - a_jent.job_filter
   - a_jent.job_matcher
   - a_jent.notifications
3. Module BASE_DIR resolves correctly to repository root.
4. job_search_agent imports all required modules and re-exports compatibility symbols.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestPackageStructure(unittest.TestCase):
    def test_a_jent_package_imports(self):
        """Top-level a_jent package imports successfully."""
        import a_jent
        self.assertIsNotNone(a_jent)

    def test_all_five_modules_import(self):
        """All five extracted modules import successfully from a_jent."""
        import a_jent.job_sources
        import a_jent.resume_parser
        import a_jent.job_filter
        import a_jent.job_matcher
        import a_jent.notifications

        self.assertIsNotNone(a_jent.job_sources)
        self.assertIsNotNone(a_jent.resume_parser)
        self.assertIsNotNone(a_jent.job_filter)
        self.assertIsNotNone(a_jent.job_matcher)
        self.assertIsNotNone(a_jent.notifications)

    def test_module_base_dir_resolves_to_project_root(self):
        """Modules in a_jent resolve BASE_DIR to the repository root directory."""
        from a_jent import job_sources, resume_parser, job_filter, job_matcher, notifications

        expected_root = PROJECT_ROOT.resolve()
        for mod in (job_sources, resume_parser, job_filter, job_matcher, notifications):
            self.assertEqual(
                mod.BASE_DIR.resolve(),
                expected_root,
                f"{mod.__name__}.BASE_DIR did not resolve to project root",
            )
            self.assertEqual(
                mod.CONFIG_FILE.resolve(),
                (expected_root / "config.yaml").resolve(),
                f"{mod.__name__}.CONFIG_FILE did not resolve to project root config.yaml",
            )

    def test_job_search_agent_preserves_public_exports(self):
        """job_search_agent imports from a_jent and preserves all public exports."""
        import job_search_agent
        from a_jent import job_sources, resume_parser, job_filter, job_matcher, notifications

        # Module references
        self.assertIs(job_search_agent.job_sources, job_sources)
        self.assertIs(job_search_agent.resume_parser, resume_parser)
        self.assertIs(job_search_agent.job_filter, job_filter)
        self.assertIs(job_search_agent.job_matcher, job_matcher)
        self.assertIs(job_search_agent.notifications, notifications)

        # Public functions and aliases
        self.assertTrue(callable(job_search_agent.fetch_all_sources))
        self.assertTrue(callable(job_search_agent.rank_by_similarity))
        self.assertTrue(callable(job_search_agent.get_resume_text))
        self.assertTrue(callable(job_search_agent.extract_resume_text))
        self.assertTrue(callable(job_search_agent.passes_level_filter))
        self.assertTrue(callable(job_search_agent.passes_location_filter))
        self.assertTrue(callable(job_search_agent.notify))
        self.assertTrue(callable(job_search_agent.expand_synonyms))
        self.assertIs(job_search_agent._SESSION, job_sources._SESSION)


if __name__ == "__main__":
    unittest.main()
