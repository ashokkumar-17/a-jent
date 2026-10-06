"""
Automated Tests for Task 15: Job Normalizer (a_jent/job_normalizer.py)
----------------------------------------------------------------------
Verifies:
1. Basic job normalization (JobProfile structure, to_dict serialization).
2. Required skill extraction from explicit requirements sections.
3. Preferred skill extraction from explicit preferred/bonus sections.
4. Skill alias normalization through skill_taxonomy (py -> python, postgres -> postgresql, etc.).
5. Unknown skill handling in explicit skill sections.
6. Explicit seniority extraction (intern, entry_level, junior, mid_level, senior, lead).
7. Explicit experience requirement extraction (minimum, range, zero experience).
8. Explicit location extraction.
9. Explicit work mode extraction (remote, hybrid, onsite, UNKNOWN != REMOTE).
10. Explicit employment type extraction (full_time, internship, part_time, contract).
11. Explicit graduation requirement extraction (batch/year 2026, 2027).
12. Missing fields remain unknown (None / empty).
13. No false seniority matches (e.g., 'mentoring junior developers', 'senior director').
14. No false graduation-year matches (e.g., '2027 roadmap', 'founded in 2018').
15. No false required/preferred classification.
16. Original raw job is not unexpectedly mutated.
17. Deterministic output across multiple runs.
18. Realistic job posting snippet from Section 20.
19. Minimal job posting snippet leaves unsupported fields unknown.
20. Coexistence and clean imports across all modules.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent.job_normalizer import JobProfile, normalize_job, normalize_jobs
from a_jent import (
    candidate_profiler,
    job_filter,
    job_matcher,
    job_normalizer,
    job_sources,
    skill_taxonomy,
)


class TestJobNormalizer(unittest.TestCase):
    # -----------------------------------------------------------------------
    # 1. Basic job normalization
    # -----------------------------------------------------------------------
    def test_basic_job_normalization(self):
        """JobProfile correctly represents core metadata and serializes via to_dict."""
        raw_job = {
            "id": "job-101",
            "title": "Backend Software Engineer",
            "company": "Acme Corp",
            "location": "Hyderabad",
            "url": "https://example.com/job/101",
            "source": "indeed",
            "description": "We are seeking a developer with Python and SQL experience.",
        }
        profile = normalize_job(raw_job)

        self.assertIsInstance(profile, JobProfile)
        self.assertEqual(profile.job_id, "job-101")
        self.assertEqual(profile.title, "Backend Software Engineer")
        self.assertEqual(profile.company, "Acme Corp")
        self.assertEqual(profile.raw_location, "Hyderabad")
        self.assertEqual(profile.location, "hyderabad")
        self.assertEqual(profile.url, "https://example.com/job/101")
        self.assertEqual(profile.source, "indeed")
        self.assertIn("python", profile.required_skills)
        self.assertIn("sql", profile.required_skills)

        # Serialization to_dict()
        data = profile.to_dict()
        self.assertEqual(data["job_id"], "job-101")
        self.assertEqual(data["title"], "Backend Software Engineer")
        self.assertEqual(data["company"], "Acme Corp")
        self.assertIn("python", data["required_skills"])
        self.assertIsInstance(data["evidence"], dict)
        self.assertIsInstance(data["confidence"], dict)

    # -----------------------------------------------------------------------
    # 2. Required skill extraction
    # -----------------------------------------------------------------------
    def test_required_skill_extraction(self):
        """Skills in explicit Requirements / Must Have sections become required_skills."""
        raw_job = {
            "title": "Software Engineer",
            "description": (
                "About the role: Join our backend platform team.\n\n"
                "Requirements:\n"
                "- Python\n"
                "- PostgreSQL\n"
                "- Docker\n"
            ),
        }
        profile = normalize_job(raw_job)
        self.assertIn("python", profile.required_skills)
        self.assertIn("postgresql", profile.required_skills)
        self.assertIn("docker", profile.required_skills)
        self.assertEqual(profile.preferred_skills, [])

    # -----------------------------------------------------------------------
    # 3. Preferred skill extraction
    # -----------------------------------------------------------------------
    def test_preferred_skill_extraction(self):
        """Skills in explicit Preferred / Nice to have sections become preferred_skills."""
        raw_job = {
            "title": "Data Engineer",
            "description": (
                "Requirements:\n"
                "- Python\n"
                "- SQL\n\n"
                "Nice to have:\n"
                "- Kubernetes\n"
                "- AWS\n"
            ),
        }
        profile = normalize_job(raw_job)
        self.assertIn("python", profile.required_skills)
        self.assertIn("sql", profile.required_skills)
        self.assertIn("kubernetes", profile.preferred_skills)
        self.assertIn("aws", profile.preferred_skills)
        # Ensure preferred skills do not leak into required
        self.assertNotIn("kubernetes", profile.required_skills)
        self.assertNotIn("aws", profile.required_skills)

    # -----------------------------------------------------------------------
    # 4. Skill alias normalization through skill_taxonomy
    # -----------------------------------------------------------------------
    def test_skill_alias_normalization(self):
        """Skill aliases map to canonical names via skill_taxonomy."""
        raw_job = {
            "title": "Full Stack Engineer",
            "description": (
                "Requirements:\n"
                "- Experience with Py scripting\n"
                "- Database management using Postgres\n"
                "- Container orchestration with K8s\n"
                "- ML pipelines using Sklearn\n"
            ),
        }
        profile = normalize_job(raw_job)
        self.assertIn("python", profile.required_skills)
        self.assertIn("postgresql", profile.required_skills)
        self.assertIn("kubernetes", profile.required_skills)
        self.assertIn("scikit-learn", profile.required_skills)

    # -----------------------------------------------------------------------
    # 5. Unknown skill handling
    # -----------------------------------------------------------------------
    def test_unknown_skill_handling(self):
        """Unrecognized tokens in explicit skill sections land in unknown_skills."""
        raw_job = {
            "title": "BI Specialist",
            "description": (
                "Requirements:\n"
                "- Python\n"
                "- SQL\n"
                "- Power BI\n"
                "- Tableau\n"
            ),
        }
        profile = normalize_job(raw_job)
        self.assertIn("python", profile.required_skills)
        self.assertIn("sql", profile.required_skills)
        # Power BI and Tableau are not in canonical taxonomy -> land in unknown_skills
        self.assertIn("power bi", profile.unknown_skills)
        self.assertIn("tableau", profile.unknown_skills)

    # -----------------------------------------------------------------------
    # 6. Explicit seniority
    # -----------------------------------------------------------------------
    def test_explicit_seniority(self):
        """Explicit seniority is extracted from title and description markers."""
        cases = [
            ("Senior Software Engineer", "", "senior"),
            ("Tech Lead", "", "lead"),
            ("Lead Data Scientist", "", "lead"),
            ("Junior Python Developer", "", "junior"),
            ("Software Engineer Intern", "", "intern"),
            ("Entry Level Analyst", "", "entry_level"),
            ("Software Engineer", "Role Level: Senior\nExperience in backend.", "senior"),
            ("Software Engineer", "Fresh graduates welcome to apply.", "entry_level"),
            ("Software Engineer", "Internship opportunity for 2026 students.", "intern"),
        ]
        for title, desc, expected_seniority in cases:
            profile = normalize_job({"title": title, "description": desc})
            self.assertEqual(
                profile.seniority,
                expected_seniority,
                f"Failed seniority extraction for title='{title}', desc='{desc}'",
            )

    # -----------------------------------------------------------------------
    # 7. Explicit experience requirement
    # -----------------------------------------------------------------------
    def test_explicit_experience_requirement(self):
        """Minimum experience years extracted from range, minimum, and zero-experience markers."""
        cases = [
            ("Requirements: 2+ years of experience with Python.", 2.0),
            ("Minimum 3 years of relevant experience in software.", 3.0),
            ("Candidate must have 2-4 years of industry experience.", 2.0),
            ("Experience: 5 years in backend development.", 5.0),
            ("Fresh graduates welcome to apply. No prior experience required.", 0.0),
            ("Requires 0-2 years of experience in data analytics.", 0.0),
        ]
        for desc, expected_exp in cases:
            profile = normalize_job({"title": "Developer", "description": desc})
            self.assertEqual(
                profile.experience_years,
                expected_exp,
                f"Failed experience extraction for desc='{desc}'",
            )

    # -----------------------------------------------------------------------
    # 8. Explicit location
    # -----------------------------------------------------------------------
    def test_explicit_location(self):
        """Location extracted from raw_location and description headers."""
        p1 = normalize_job({"location": "Hyderabad", "description": "Backend dev."})
        self.assertEqual(p1.location, "hyderabad")

        p2 = normalize_job({"location": "Bangalore / Bengaluru", "description": "Backend dev."})
        self.assertIn(p2.location, ["bangalore", "bengaluru"])

        p3 = normalize_job({"location": "", "description": "Location: Pune\nWork on cloud."})
        self.assertEqual(p3.location, "pune")

    # -----------------------------------------------------------------------
    # 9. Explicit work mode (UNKNOWN != REMOTE)
    # -----------------------------------------------------------------------
    def test_explicit_work_mode(self):
        """Remote, hybrid, and onsite are extracted; empty location is NOT assumed remote."""
        p_remote = normalize_job({"location": "Remote", "description": "Full remote role."})
        self.assertEqual(p_remote.work_mode, "remote")

        p_hybrid = normalize_job({"location": "Hybrid - Hyderabad", "description": "2 days office."})
        self.assertEqual(p_hybrid.work_mode, "hybrid")
        self.assertEqual(p_hybrid.location, "hyderabad")

        p_onsite = normalize_job({"location": "On-site - Bangalore", "description": "Office based."})
        self.assertEqual(p_onsite.work_mode, "onsite")
        self.assertEqual(p_onsite.location, "bangalore")

        # UNKNOWN != REMOTE
        p_unknown = normalize_job({"location": "", "description": "Build web applications."})
        self.assertIsNone(p_unknown.work_mode)
        self.assertIsNone(p_unknown.location)

    # -----------------------------------------------------------------------
    # 10. Explicit employment type
    # -----------------------------------------------------------------------
    def test_explicit_employment_type(self):
        """Employment type extracted from direct fields and description headers without guessing from title."""
        p_field = normalize_job({"employment_type": "full-time", "description": "Join team."})
        self.assertEqual(p_field.employment_type, "full_time")

        p_desc = normalize_job({"description": "Employment Type: Internship\nDuration 6 months."})
        self.assertEqual(p_desc.employment_type, "internship")

        p_contract = normalize_job({"description": "Job Type: Contract\n6-month project."})
        self.assertEqual(p_contract.employment_type, "contract")

        # Not guessed solely from generic title
        p_title_only = normalize_job({"title": "Developer", "description": "Build web apps."})
        self.assertIsNone(p_title_only.employment_type)

    # -----------------------------------------------------------------------
    # 11. Explicit graduation requirement
    # -----------------------------------------------------------------------
    def test_explicit_graduation_requirement(self):
        """Graduation year extracted from explicit graduation/batch phrases."""
        cases = [
            ("Graduating in 2027 with a Bachelor's degree.", 2027),
            ("Open to Class of 2026 students.", 2026),
            ("Expected graduation: 2027.", 2027),
            ("Must graduate by 2026.", 2026),
            ("2026 batch only eligible.", 2026),
        ]
        for desc, expected_year in cases:
            profile = normalize_job({"title": "Intern", "description": desc})
            self.assertEqual(
                profile.graduation_year,
                expected_year,
                f"Failed graduation year extraction for desc='{desc}'",
            )

    # -----------------------------------------------------------------------
    # 12. Missing fields remain unknown
    # -----------------------------------------------------------------------
    def test_missing_fields_remain_unknown(self):
        """Unsupported or missing fields remain None / empty rather than guessing."""
        raw_job = {
            "title": "Software Engineer",
            "description": "General description without seniority, experience, or location.",
        }
        profile = normalize_job(raw_job)
        self.assertIsNone(profile.seniority)
        self.assertIsNone(profile.experience_years)
        self.assertIsNone(profile.location)
        self.assertIsNone(profile.work_mode)
        self.assertIsNone(profile.employment_type)
        self.assertIsNone(profile.graduation_year)

    # -----------------------------------------------------------------------
    # 13. No false seniority matches
    # -----------------------------------------------------------------------
    def test_no_false_seniority_matches(self):
        """Mentoring junior developers or reporting to directors does not mark role junior or senior."""
        raw_job = {
            "title": "Software Engineer",
            "description": (
                "Responsibilities include mentoring junior developers and interns. "
                "The candidate will report to the senior director."
            ),
        }
        profile = normalize_job(raw_job)
        self.assertIsNone(
            profile.seniority,
            f"Expected seniority to be None, got '{profile.seniority}'",
        )

    # -----------------------------------------------------------------------
    # 14. No false graduation-year matches
    # -----------------------------------------------------------------------
    def test_no_false_graduation_matches(self):
        """Roadmaps, founding dates, or copyright years do not become graduation requirements."""
        cases = [
            "Help us deliver on our 2027 roadmap and product strategy.",
            "Founded in 2018 in Bangalore, India.",
            "Copyright 2025 Acme Technologies.",
            "We have grown 200% since 2021.",
        ]
        for desc in cases:
            profile = normalize_job({"title": "Developer", "description": desc})
            self.assertIsNone(
                profile.graduation_year,
                f"Expected graduation_year to be None for desc='{desc}', got {profile.graduation_year}",
            )

    # -----------------------------------------------------------------------
    # 15. No false required/preferred classification
    # -----------------------------------------------------------------------
    def test_no_false_required_preferred_classification(self):
        """Skills marked 'is preferred' or in 'Nice to have' do not become required."""
        raw_job = {
            "title": "Backend Developer",
            "description": (
                "We build high-throughput APIs using Python and PostgreSQL.\n\n"
                "Docker is preferred and AWS knowledge is a plus."
            ),
        }
        profile = normalize_job(raw_job)
        self.assertIn("python", profile.required_skills)
        self.assertIn("postgresql", profile.required_skills)
        self.assertIn("docker", profile.preferred_skills)
        self.assertIn("aws", profile.preferred_skills)
        self.assertNotIn("docker", profile.required_skills)
        self.assertNotIn("aws", profile.required_skills)

    # -----------------------------------------------------------------------
    # 16. Original raw job is not unexpectedly mutated
    # -----------------------------------------------------------------------
    def test_original_raw_job_not_mutated(self):
        """Normalizer preserves original job dictionary without mutation."""
        raw_job = {
            "id": "123",
            "title": "Senior Data Analyst",
            "company": "DataCorp",
            "location": "Hyderabad",
            "description": "Requirements: Python, SQL. 2+ years of experience.",
        }
        snapshot = dict(raw_job)
        profile = normalize_job(raw_job)

        self.assertEqual(raw_job, snapshot)
        self.assertEqual(profile.raw_job, snapshot)

    # -----------------------------------------------------------------------
    # 17. Deterministic output
    # -----------------------------------------------------------------------
    def test_deterministic_output(self):
        """Repeated invocations on the same raw job yield identical profiles."""
        raw_job = {
            "id": "999",
            "title": "Senior Full Stack Engineer",
            "company": "TechInnovate",
            "location": "Hybrid - Bangalore",
            "description": (
                "Requirements:\n"
                "- Python\n"
                "- React\n"
                "- 3+ years of experience\n\n"
                "Preferred:\n"
                "- Docker\n"
                "- AWS\n\n"
                "Employment Type: Full-time\n"
            ),
        }
        p1 = normalize_job(raw_job)
        p2 = normalize_job(raw_job)

        self.assertEqual(p1.to_dict(), p2.to_dict())
        self.assertEqual(p1.required_skills, p2.required_skills)
        self.assertEqual(p1.preferred_skills, p2.preferred_skills)
        self.assertEqual(p1.seniority, p2.seniority)
        self.assertEqual(p1.experience_years, p2.experience_years)
        self.assertEqual(p1.work_mode, p2.work_mode)

    # -----------------------------------------------------------------------
    # 18. Realistic job posting snippet (Section 20 of specification)
    # -----------------------------------------------------------------------
    def test_realistic_job_posting_snippet(self):
        """Normalizes the exact realistic job posting snippet from Section 20."""
        snippet = """Senior Data Analyst

Location: Hyderabad
Work Mode: Hybrid

Requirements:
- Python
- SQL
- Power BI
- 2+ years of experience

Preferred:
- Tableau
- AWS

Employment Type: Full-time
"""
        raw_job = {
            "id": "job-sec-20",
            "title": "Senior Data Analyst",
            "company": "AnalyticsCo",
            "location": "Hyderabad",
            "description": snippet,
        }
        profile = normalize_job(raw_job)

        self.assertEqual(profile.seniority, "senior")
        self.assertEqual(profile.experience_years, 2.0)
        self.assertEqual(profile.location, "hyderabad")
        self.assertEqual(profile.work_mode, "hybrid")
        self.assertEqual(profile.employment_type, "full_time")

        self.assertIn("python", profile.required_skills)
        self.assertIn("sql", profile.required_skills)
        self.assertIn("aws", profile.preferred_skills)

        # Power BI and Tableau land in unknown_skills as expected
        self.assertIn("power bi", profile.unknown_skills)
        self.assertIn("tableau", profile.unknown_skills)

        # Verify evidence was recorded
        self.assertIn("seniority", profile.evidence)
        self.assertIn("experience_years", profile.evidence)
        self.assertIn("location_work_mode", profile.evidence)
        self.assertIn("employment_type", profile.evidence)

    # -----------------------------------------------------------------------
    # 19. Minimal job posting snippet leaves unsupported fields unknown
    # -----------------------------------------------------------------------
    def test_minimal_job_posting_snippet(self):
        """Minimal posting leaves unsupported fields unknown rather than guessing."""
        raw_job = {
            "title": "Junior Developer",
            "description": "Build web applications using modern technologies.",
        }
        profile = normalize_job(raw_job)
        self.assertEqual(profile.seniority, "junior")
        self.assertIsNone(profile.experience_years)
        self.assertIsNone(profile.location)
        self.assertIsNone(profile.work_mode)
        self.assertIsNone(profile.employment_type)
        self.assertIsNone(profile.graduation_year)
        self.assertEqual(profile.required_skills, [])
        self.assertEqual(profile.preferred_skills, [])

    # -----------------------------------------------------------------------
    # 20. Batch normalize_jobs and cross-module coexistence
    # -----------------------------------------------------------------------
    def test_batch_normalization_and_coexistence(self):
        """normalize_jobs handles list of jobs and all modules import cleanly without circularity."""
        jobs = [
            {"title": "Dev 1", "description": "Requirements: Python"},
            {"title": "Dev 2", "description": "Requirements: Go"},
        ]
        profiles = normalize_jobs(jobs)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0].required_skills, ["python"])
        self.assertEqual(profiles[1].required_skills, ["go"])

        # Empty list handling
        self.assertEqual(normalize_jobs([]), [])
        # None / empty job handling
        empty_profile = normalize_job(None)
        self.assertEqual(empty_profile.title, "")


if __name__ == "__main__":
    unittest.main()
