"""
Automated Tests for Task 14: Candidate Profiler (a_jent/candidate_profiler.py)
------------------------------------------------------------------------------
Verifies:
1. Python skill extraction.
2. Skill alias normalization through skill_taxonomy.
3. Multiple skills extraction.
4. Unknown skill handling.
5. Explicit student / entry-level evidence.
6. Explicit seniority evidence.
7. Explicit graduation year extraction.
8. Explicit location preference extraction (distinguishing college/city mentions).
9. Explicit remote / hybrid / onsite work-mode preference.
10. Explicit employment preference extraction (internship / full-time).
11. Missing information remains unknown (None / empty).
12. No false skill matches from substrings (e.g. Java in JavaScript, React Native).
13. Determinism: same input produces identical profile.
14. Candidate profiler does not modify legacy matcher behavior.
15. Realistic resume snippet extraction and absent-field handling.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent.candidate_profiler import CandidateProfile, profile_candidate
from a_jent import job_matcher


class TestCandidateProfiler(unittest.TestCase):
    # -----------------------------------------------------------------------
    # 1. Python skill extraction
    # -----------------------------------------------------------------------
    def test_python_skill_extraction(self):
        """Python skill is reliably detected and normalized."""
        text = "Software engineer working with Python to build data pipelines."
        profile = profile_candidate(text)
        self.assertIn("python", profile.normalized_skills)
        self.assertIn("python", [s.lower() for s in profile.raw_skills])

    # -----------------------------------------------------------------------
    # 2. Skill alias normalization through skill_taxonomy
    # -----------------------------------------------------------------------
    def test_skill_alias_normalization(self):
        """Aliases (py, k8s, postgres, sklearn, js) normalize to canonical skills."""
        text = (
            "Experience with Py scripting, container orchestration using k8s, "
            "database querying on Postgres, model training with Sklearn, and frontend in JS."
        )
        profile = profile_candidate(text)
        expected = ["python", "kubernetes", "postgresql", "scikit-learn", "javascript"]
        for exp in expected:
            self.assertIn(
                exp,
                profile.normalized_skills,
                f"Alias failed to normalize to canonical skill '{exp}'.",
            )

    # -----------------------------------------------------------------------
    # 3. Multiple skills extraction
    # -----------------------------------------------------------------------
    def test_multiple_skills_extraction(self):
        """Multiple skills across languages, databases, and frameworks are extracted."""
        text = "SKILLS: Python, SQL, PostgreSQL, Docker, AWS, FastAPI, React"
        profile = profile_candidate(text)
        self.assertIn("python", profile.normalized_skills)
        self.assertIn("sql", profile.normalized_skills)
        self.assertIn("postgresql", profile.normalized_skills)
        self.assertIn("docker", profile.normalized_skills)
        self.assertIn("aws", profile.normalized_skills)
        self.assertIn("fastapi", profile.normalized_skills)
        self.assertIn("react", profile.normalized_skills)

    # -----------------------------------------------------------------------
    # 4. Unknown skill handling
    # -----------------------------------------------------------------------
    def test_unknown_skill_handling(self):
        """Unknown skills in skills section are isolated without corrupting canonical skills."""
        text = "SKILLS: Python, SQL, CustomProprietaryToolXYZ, BrandNewLanguage2026"
        profile = profile_candidate(text)
        self.assertIn("python", profile.normalized_skills)
        self.assertIn("sql", profile.normalized_skills)
        # Unknown skills must NOT be mapped to unrelated canonical skills
        self.assertIn("customproprietarytoolxyz", profile.unknown_skills)
        self.assertIn("brandnewlanguage2026", profile.unknown_skills)
        # Known canonical skills must not include the unknown ones
        self.assertNotIn("customproprietarytoolxyz", profile.normalized_skills)
        self.assertNotIn("brandnewlanguage2026", profile.normalized_skills)

    # -----------------------------------------------------------------------
    # 5. Explicit student / entry-level evidence
    # -----------------------------------------------------------------------
    def test_student_and_entry_level_seniority(self):
        """Student or entry-level evidence extracts appropriate seniority."""
        student_text = "Final-year B.Tech student at Indian Institute of Technology."
        p_student = profile_candidate(student_text)
        self.assertEqual(p_student.seniority, "student")
        self.assertEqual(p_student.confidence.get("seniority"), "HIGH")
        self.assertIn("student", p_student.evidence.get("seniority", "").lower())

        entry_text = "Recent Computer Science fresher seeking entry-level software opportunities."
        p_entry = profile_candidate(entry_text)
        self.assertEqual(p_entry.seniority, "entry_level")

    # -----------------------------------------------------------------------
    # 6. Explicit seniority evidence
    # -----------------------------------------------------------------------
    def test_explicit_seniority_evidence(self):
        """Senior and intern levels are detected from explicit titles."""
        senior_text = "Senior Software Engineer with extensive distributed systems background."
        p_senior = profile_candidate(senior_text)
        self.assertEqual(p_senior.seniority, "senior")

        lead_text = "Tech Lead directing a squad of 6 backend developers."
        p_lead = profile_candidate(lead_text)
        self.assertEqual(p_lead.seniority, "lead")

        intern_text = "Working as a Machine Learning Intern on computer vision models."
        p_intern = profile_candidate(intern_text)
        self.assertEqual(p_intern.seniority, "intern")

    # -----------------------------------------------------------------------
    # 7. Explicit graduation year extraction
    # -----------------------------------------------------------------------
    def test_explicit_graduation_year(self):
        """Expected graduation year is extracted from various explicit formats."""
        t1 = "EDUCATION: B.Tech in CSE, Expected Graduation: 2027"
        self.assertEqual(profile_candidate(t1).graduation_year, 2027)

        t2 = "B.Tech in Information Technology, 2022-2026"
        self.assertEqual(profile_candidate(t2).graduation_year, 2026)

        t3 = "Undergraduate Degree, Graduating in 2025"
        self.assertEqual(profile_candidate(t3).graduation_year, 2025)

        # Random numbers should not be extracted as graduation year
        t4 = "Served 2018 clients in project alpha 2020."
        self.assertIsNone(profile_candidate(t4).graduation_year)

    # -----------------------------------------------------------------------
    # 8. Explicit location preference extraction
    # -----------------------------------------------------------------------
    def test_explicit_location_preference(self):
        """Locations are extracted only from explicit preferences, not college or city mentions."""
        # Mentions college city in education: must NOT be inferred as preference
        college_text = "Studied at Osmania University, Hyderabad. Completed schooling in Pune."
        p_college = profile_candidate(college_text)
        self.assertEqual(p_college.preferred_locations, [])

        # Explicit preference statement
        pref_text = "Preferred Locations: Bangalore, Hyderabad"
        p_pref = profile_candidate(pref_text)
        self.assertIn("bangalore", p_pref.preferred_locations)
        self.assertIn("hyderabad", p_pref.preferred_locations)
        self.assertNotIn("pune", p_pref.preferred_locations)

    # -----------------------------------------------------------------------
    # 9. Explicit remote / hybrid / onsite preference
    # -----------------------------------------------------------------------
    def test_explicit_work_mode_preference(self):
        """Work mode preference is extracted when stated and remains None when omitted."""
        remote_text = "Preferences: Open to remote opportunities worldwide."
        self.assertEqual(profile_candidate(remote_text).work_mode, "remote")

        hybrid_text = "Work Mode: Hybrid preferred."
        self.assertEqual(profile_candidate(hybrid_text).work_mode, "hybrid")

        onsite_text = "Workplace Preference: Onsite in Bangalore."
        self.assertEqual(profile_candidate(onsite_text).work_mode, "onsite")

        # Unknown != remote (absence of remote preference must be None)
        no_mode_text = "Software developer skilled in Python and Django."
        self.assertIsNone(profile_candidate(no_mode_text).work_mode)

    # -----------------------------------------------------------------------
    # 10. Explicit employment preference
    # -----------------------------------------------------------------------
    def test_explicit_employment_preference(self):
        """Internship or full-time preference is extracted only when explicitly stated."""
        intern_text = "Seeking Summer Internship in backend engineering."
        self.assertEqual(profile_candidate(intern_text).employment_preferences, ["internship"])

        fulltime_text = "Looking for full-time opportunities starting June 2025."
        self.assertEqual(profile_candidate(fulltime_text).employment_preferences, ["full_time"])

        # Student status alone must NOT imply internship preference
        student_only = "Final-year student studying Computer Science."
        self.assertEqual(profile_candidate(student_only).employment_preferences, [])

    # -----------------------------------------------------------------------
    # 11. Missing information remains unknown
    # -----------------------------------------------------------------------
    def test_missing_information_remains_unknown(self):
        """When fields are absent, they remain None / empty rather than fabricated."""
        empty_profile = profile_candidate("")
        self.assertEqual(empty_profile.normalized_skills, [])
        self.assertIsNone(empty_profile.seniority)
        self.assertIsNone(empty_profile.experience_years)
        self.assertIsNone(empty_profile.graduation_year)
        self.assertIsNone(empty_profile.current_location)
        self.assertEqual(empty_profile.preferred_locations, [])
        self.assertIsNone(empty_profile.work_mode)
        self.assertEqual(empty_profile.employment_preferences, [])

        none_profile = profile_candidate(None)
        self.assertEqual(none_profile.normalized_skills, [])

    # -----------------------------------------------------------------------
    # 12. No false skill matches from substrings
    # -----------------------------------------------------------------------
    def test_no_false_skill_substring_matches(self):
        """Substrings do not trigger false skill matches."""
        # 1. Java in JavaScript
        js_text = "Proficient in JavaScript development with Node.js."
        p_js = profile_candidate(js_text)
        self.assertIn("javascript", p_js.normalized_skills)
        self.assertNotIn("java", p_js.normalized_skills)

        # 2. React Native does not trigger React
        rn_text = "Built cross-platform mobile apps with React Native."
        p_rn = profile_candidate(rn_text)
        self.assertNotIn("react", p_rn.normalized_skills)

        # 3. Single-letter C in normal prose
        grade_text = "Achieved Grade C in Chemistry and Section C award."
        p_grade = profile_candidate(grade_text)
        self.assertNotIn("c", p_grade.normalized_skills)

        # 4. Word "go" in normal prose
        prose_go = "Willing to go the extra mile to deliver on schedule."
        p_go = profile_candidate(prose_go)
        self.assertNotIn("go", p_go.normalized_skills)

    # -----------------------------------------------------------------------
    # 13. Determinism
    # -----------------------------------------------------------------------
    def test_deterministic_profile_generation(self):
        """Identical inputs produce identical profile outputs."""
        sample = (
            "EDUCATION\n"
            "B.Tech in Computer Science\n"
            "Expected Graduation: 2027\n\n"
            "SKILLS\n"
            "Python, SQL, PostgreSQL, Machine Learning, Docker\n\n"
            "EXPERIENCE\n"
            "Data Science Intern\n"
            "2 years of experience\n\n"
            "PREFERENCES\n"
            "Preferred Locations: Bangalore, Pune\n"
            "Open to remote opportunities\n"
            "Seeking Summer Internship\n"
        )
        p1 = profile_candidate(sample)
        p2 = profile_candidate(sample)
        self.assertEqual(p1.to_dict(), p2.to_dict())

    # -----------------------------------------------------------------------
    # 14. Candidate profiler does not modify legacy matcher behavior
    # -----------------------------------------------------------------------
    def test_candidate_profiler_does_not_affect_legacy_matcher(self):
        """Legacy TF-IDF matcher functions identically before and after candidate profiler calls."""
        resume = "Python developer with machine learning experience."
        jobs = [
            {"id": "j1", "title": "Python ML Engineer", "description": "Python, ML, PyTorch"},
            {"id": "j2", "title": "Accountant", "description": "Accounting and finance"},
        ]
        # Run profiler
        _ = profile_candidate(resume)

        # Verify legacy matcher still scores and orders correctly
        ranked = job_matcher.rank_by_similarity(resume, jobs)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], "j1")
        self.assertGreater(ranked[0]["score"], 0.12)

    # -----------------------------------------------------------------------
    # 15. Realistic resume snippet test
    # -----------------------------------------------------------------------
    def test_realistic_resume_snippet(self):
        """Realistic candidate resume snippet extracts all supported fields accurately."""
        snippet = (
            "Alex Sharma\n"
            "Email: alex@example.com | Current Location: Bangalore\n\n"
            "EDUCATION\n"
            "B.Tech in Computer Science & Engineering\n"
            "Expected Graduation: 2027\n\n"
            "SKILLS & TOOLS\n"
            "Python, SQL, PostgreSQL, Docker, AWS, FastAPI, Machine Learning, CustomLib\n\n"
            "EXPERIENCE\n"
            "Data Science Intern at ThinkNovaa\n"
            "Worked with a team on time-series forecasting.\n\n"
            "PREFERENCES\n"
            "Preferred Locations: Bangalore, Hyderabad\n"
            "Open to remote opportunities\n"
            "Seeking: Summer Internship\n"
        )
        profile = profile_candidate(snippet)

        self.assertIn("python", profile.normalized_skills)
        self.assertIn("sql", profile.normalized_skills)
        self.assertIn("postgresql", profile.normalized_skills)
        self.assertIn("docker", profile.normalized_skills)
        self.assertIn("aws", profile.normalized_skills)
        self.assertIn("fastapi", profile.normalized_skills)
        self.assertIn("machine learning", profile.normalized_skills)
        self.assertIn("customlib", profile.unknown_skills)

        self.assertEqual(profile.graduation_year, 2027)
        self.assertEqual(profile.seniority, "intern")
        self.assertEqual(profile.current_location, "bangalore")
        self.assertIn("bangalore", profile.preferred_locations)
        self.assertIn("hyderabad", profile.preferred_locations)
        self.assertEqual(profile.work_mode, "remote")
        self.assertEqual(profile.employment_preferences, ["internship"])


if __name__ == "__main__":
    unittest.main()
