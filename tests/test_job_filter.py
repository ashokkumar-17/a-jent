"""
Automated Tests for Task 10: Extracted Job Filtering (job_filter.py)
-------------------------------------------------------------------
Verifies:
1. passes_level_filter() evaluates seniority levels across title and description.
2. Empty LEVEL_FILTERS allows all jobs to pass.
3. Case-insensitivity, missing fields, and no-match scenarios for level filtering.
4. passes_location_filter() handles remote preference, empty location pass-through, and preferred locations.
5. Location filtering behaves correctly when both remote preference and preferred locations are disabled.
6. Case-insensitivity, missing location, and multiple preferred locations.
7. Configuration precedence: environment variables, config.yaml, defaults, and comma-separated string handling.
8. Backward compatibility: job_search_agent re-exports and delegation wrappers work seamlessly.
9. Deterministic regression check: job_filter and job_search_agent yield identical filtering decisions.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent import job_filter
import job_search_agent


class TestJobFilter(unittest.TestCase):
    # -------------------------------------------------------------------
    # 1. Level Filtering Tests
    # -------------------------------------------------------------------
    def test_level_filter_empty_list_allows_all(self):
        """When LEVEL_FILTERS is empty, all jobs pass regardless of seniority."""
        job = {"title": "Principal Architect", "description": "15+ years experience required."}
        self.assertTrue(job_filter.passes_level_filter(job, level_filters=[]))

    def test_level_filter_matches_in_title(self):
        """Job passes when level keyword appears in the title."""
        job = {"title": "Software Engineer Intern", "description": "Building web APIs."}
        self.assertTrue(job_filter.passes_level_filter(job, level_filters=["intern"]))

    def test_level_filter_matches_in_description(self):
        """Job passes when level keyword appears in the description."""
        job = {"title": "Software Engineer", "description": "This is an entry level role for freshers."}
        self.assertTrue(job_filter.passes_level_filter(job, level_filters=["entry level"]))

    def test_level_filter_case_insensitivity(self):
        """Level filtering is case-insensitive."""
        job = {"title": "JUNIOR DEVELOPER", "description": "Python developer."}
        self.assertTrue(job_filter.passes_level_filter(job, level_filters=["junior"]))

    def test_level_filter_multiple_configured_levels(self):
        """Job passes if any configured level keyword matches."""
        filters = ["intern", "junior", "entry level", "new grad"]
        job_intern = {"title": "Python Intern", "description": "Summer internship"}
        job_grad = {"title": "New Grad Engineer", "description": "Graduating 2026"}
        job_senior = {"title": "Senior Staff Engineer", "description": "Leading architecture"}

        self.assertTrue(job_filter.passes_level_filter(job_intern, level_filters=filters))
        self.assertTrue(job_filter.passes_level_filter(job_grad, level_filters=filters))
        self.assertFalse(job_filter.passes_level_filter(job_senior, level_filters=filters))

    def test_level_filter_missing_title_or_description(self):
        """Job handles missing 'title' or 'description' fields safely."""
        job_missing_desc = {"title": "Frontend Intern"}
        job_missing_title = {"description": "Looking for entry level engineers"}
        job_empty = {}

        self.assertTrue(job_filter.passes_level_filter(job_missing_desc, level_filters=["intern"]))
        self.assertTrue(job_filter.passes_level_filter(job_missing_title, level_filters=["entry level"]))
        self.assertFalse(job_filter.passes_level_filter(job_empty, level_filters=["intern"]))

    # -------------------------------------------------------------------
    # 2. Location Filtering Tests
    # -------------------------------------------------------------------
    def test_location_filter_both_disabled_allows_all(self):
        """When PREFER_REMOTE=False and PREFERRED_LOCATIONS=[], all jobs pass."""
        job = {"location": "London, UK"}
        self.assertTrue(job_filter.passes_location_filter(job, prefer_remote=False, preferred_locations=[]))

    def test_location_filter_remote_job_passes(self):
        """Job with 'remote' in location passes when PREFER_REMOTE=True."""
        job = {"location": "Remote - US/Worldwide"}
        self.assertTrue(job_filter.passes_location_filter(job, prefer_remote=True, preferred_locations=[]))

    def test_location_filter_empty_location_passes_when_prefer_remote(self):
        """Preserves legacy behavior: empty or unknown location passes when PREFER_REMOTE=True."""
        job_empty_loc = {"location": ""}
        job_none_loc = {"location": None}
        job_missing_loc = {}

        self.assertTrue(job_filter.passes_location_filter(job_empty_loc, prefer_remote=True, preferred_locations=[]))
        self.assertTrue(job_filter.passes_location_filter(job_none_loc, prefer_remote=True, preferred_locations=[]))
        self.assertTrue(job_filter.passes_location_filter(job_missing_loc, prefer_remote=True, preferred_locations=[]))

    def test_location_filter_matching_preferred_location(self):
        """Non-remote job passes if location matches any preferred location."""
        job = {"location": "Bangalore, India"}
        self.assertTrue(job_filter.passes_location_filter(
            job,
            prefer_remote=False,
            preferred_locations=["Bangalore", "Pune"],
        ))

    def test_location_filter_unmatched_preferred_location_fails(self):
        """Non-remote job fails if location does not match any preferred location."""
        job = {"location": "Austin, Texas"}
        self.assertFalse(job_filter.passes_location_filter(
            job,
            prefer_remote=False,
            preferred_locations=["Bangalore", "Hyderabad"],
        ))

    def test_location_filter_case_insensitivity(self):
        """Location matching is case-insensitive."""
        job = {"location": "mumbai, maharashtra"}
        self.assertTrue(job_filter.passes_location_filter(
            job,
            prefer_remote=False,
            preferred_locations=["Mumbai"],
        ))

    def test_location_filter_prefer_remote_and_preferred_locations_combination(self):
        """When PREFER_REMOTE=True and PREFERRED_LOCATIONS set, remote, empty, or preferred pass."""
        locs = ["Bangalore", "Delhi"]
        job_remote = {"location": "Remote"}
        job_bangalore = {"location": "Bangalore, Karnataka"}
        job_empty = {"location": ""}
        job_chicago = {"location": "Chicago, IL"}

        self.assertTrue(job_filter.passes_location_filter(job_remote, prefer_remote=True, preferred_locations=locs))
        self.assertTrue(job_filter.passes_location_filter(job_bangalore, prefer_remote=True, preferred_locations=locs))
        self.assertTrue(job_filter.passes_location_filter(job_empty, prefer_remote=True, preferred_locations=locs))
        self.assertFalse(job_filter.passes_location_filter(job_chicago, prefer_remote=True, preferred_locations=locs))

    # -------------------------------------------------------------------
    # 3. Configuration & Comma-Separated String Handling
    # -------------------------------------------------------------------
    def test_comma_separated_level_filters(self):
        """passes_level_filter() accepts comma-separated string for level_filters."""
        job = {"title": "Software Engineer Intern"}
        self.assertTrue(job_filter.passes_level_filter(job, level_filters="intern, junior, new grad"))

    def test_comma_separated_preferred_locations(self):
        """passes_location_filter() accepts comma-separated string for preferred_locations."""
        job = {"location": "Hyderabad, Telangana"}
        self.assertTrue(job_filter.passes_location_filter(
            job,
            prefer_remote=False,
            preferred_locations="Bangalore, Hyderabad, Pune",
        ))

    def test_configuration_environment_overrides(self):
        """_get() properly resolves filter settings from environment variables."""
        with patch.dict("os.environ", {
            "LEVEL_FILTERS": "fresher, trainee",
            "PREFER_REMOTE": "false",
            "PREFERRED_LOCATIONS": "Noida, Gurgaon",
        }):
            levels = job_filter._get("LEVEL_FILTERS", [])
            if isinstance(levels, str):
                levels = [x.strip() for x in levels.split(",") if x.strip()]
            self.assertEqual(levels, ["fresher", "trainee"])

            prefer_rem = str(job_filter._get("PREFER_REMOTE", "true")).lower() == "true"
            self.assertFalse(prefer_rem)

            locs = job_filter._get("PREFERRED_LOCATIONS", [])
            if isinstance(locs, str):
                locs = [x.strip() for x in locs.split(",") if x.strip()]
            self.assertEqual(locs, ["Noida", "Gurgaon"])

    # -------------------------------------------------------------------
    # 4. Backward Compatibility & Deterministic Equivalence
    # -------------------------------------------------------------------
    def test_job_search_agent_backward_compatibility(self):
        """job_search_agent re-exports filter symbols and delegates seamlessly."""
        self.assertEqual(job_search_agent.LEVEL_FILTERS, job_filter.LEVEL_FILTERS)
        self.assertEqual(job_search_agent.PREFER_REMOTE, job_filter.PREFER_REMOTE)
        self.assertEqual(job_search_agent.PREFERRED_LOCATIONS, job_filter.PREFERRED_LOCATIONS)
        self.assertTrue(callable(job_search_agent.passes_level_filter))
        self.assertTrue(callable(job_search_agent.passes_location_filter))

    def test_deterministic_equivalence_between_modules(self):
        """job_filter and job_search_agent produce identical decisions on test jobs."""
        test_jobs = [
            {"title": "Junior Python Dev", "description": "Entry level backend", "location": "Bangalore"},
            {"title": "Staff Architect", "description": "Cloud infra", "location": "Remote"},
            {"title": "Intern", "description": "", "location": "Paris, France"},
            {"title": "Data Scientist", "description": "Machine learning", "location": ""},
        ]

        for job in test_jobs:
            self.assertEqual(
                job_search_agent.passes_level_filter(job),
                job_filter.passes_level_filter(job),
            )
            self.assertEqual(
                job_search_agent.passes_location_filter(job),
                job_filter.passes_location_filter(job),
            )


if __name__ == "__main__":
    unittest.main()
