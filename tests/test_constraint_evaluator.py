"""
Automated Tests for Task 16: Hard Constraint Evaluator (a_jent/constraint_evaluator.py)
----------------------------------------------------------------------------------------
Verifies:
Seniority:
1. Entry-level candidate vs senior job -> FAIL.
2. Unknown candidate seniority vs senior job -> UNKNOWN.
3. Compatible explicit seniority -> PASS.
4. Seniority mention in unrelated job description does not trigger false FAIL.

Work mode / location:
5. Remote-only candidate vs explicit onsite job -> FAIL.
6. Remote candidate vs remote job -> PASS.
7. Unknown candidate work mode vs onsite job -> UNKNOWN.
8. Explicit compatible location -> PASS.
9. Ambiguous location information -> UNKNOWN.
10. Empty location is NOT treated as remote.

Employment:
11. Internship preference vs explicit full-time job -> FAIL.
12. Full-time preference vs explicit internship job -> FAIL.
13. Missing candidate preference -> UNKNOWN.

Graduation:
14. Explicit incompatible graduation requirement -> FAIL.
15. Missing candidate graduation year -> UNKNOWN when job requirement exists.
16. Compatible graduation requirement -> PASS.
17. No job graduation requirement does not create an artificial failure.

Overall evaluation:
18. Any FAIL causes overall FAIL.
19. All applicable constraints PASS causes overall PASS.
20. No FAIL but unresolved applicable constraint produces UNKNOWN.

Safety:
21. Missing fields never become automatic FAIL.
22. Low-confidence/ambiguous information does not create unjustified hard FAIL.
23. No skill-based hard failures.
24. Deterministic repeated evaluation.
25. CandidateProfile and JobProfile are not mutated.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent.candidate_profiler import CandidateProfile
from a_jent.job_normalizer import JobProfile, normalize_job
from a_jent.constraint_evaluator import (
    ConstraintEvaluation,
    ConstraintResult,
    ConstraintStatus,
    evaluate_constraints,
    evaluate_employment_type,
    evaluate_graduation_year,
    evaluate_seniority,
    evaluate_work_mode_location,
)


class TestConstraintEvaluator(unittest.TestCase):
    # =======================================================================
    # SENIORITY TESTS (1-4)
    # =======================================================================

    def test_1_entry_level_candidate_vs_senior_job_fails(self):
        """Entry-level candidate vs senior job results in hard FAIL."""
        candidate = CandidateProfile(seniority="entry_level")
        job = JobProfile(title="Senior Data Scientist", seniority="senior")

        res = evaluate_seniority(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.FAIL)
        self.assertIn("entry_level", res.reason)
        self.assertIn("senior", res.reason)

        overall = evaluate_constraints(candidate, job)
        self.assertEqual(overall.status, ConstraintStatus.FAIL)
        self.assertTrue(overall.failed)

    def test_2_unknown_candidate_seniority_vs_senior_job_unknown(self):
        """Unknown candidate seniority vs senior job results in UNKNOWN."""
        candidate = CandidateProfile(seniority=None)
        job = JobProfile(title="Senior Data Scientist", seniority="senior")

        res = evaluate_seniority(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(res.is_applicable)

        overall = evaluate_constraints(candidate, job)
        self.assertEqual(overall.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(overall.unknown)

    def test_3_compatible_explicit_seniority_passes(self):
        """Explicitly compatible seniority (e.g. senior vs senior) results in PASS."""
        cases = [
            ("senior", "senior"),
            ("lead", "senior"),
            ("entry_level", "entry_level"),
            ("entry_level", "junior"),
            ("intern", "intern"),
            ("student", "intern"),
            ("mid_level", "mid_level"),
        ]
        for cand_sen, job_sen in cases:
            candidate = CandidateProfile(seniority=cand_sen)
            job = JobProfile(seniority=job_sen)
            res = evaluate_seniority(candidate, job)
            self.assertEqual(
                res.status,
                ConstraintStatus.PASS,
                f"Expected PASS for cand={cand_sen} vs job={job_sen}",
            )

    def test_4_seniority_in_unrelated_job_desc_does_not_trigger_false_fail(self):
        """Unrelated seniority mentions (e.g. mentoring junior developers) do not trigger false failure."""
        # Raw job where description has 'mentoring junior developers', but job itself is general
        raw_job = {
            "title": "Software Engineer",
            "description": "Responsibilities include mentoring junior developers and interns.",
        }
        job = normalize_job(raw_job)
        # Normalizer should leave seniority None
        self.assertIsNone(job.seniority)

        candidate = CandidateProfile(seniority="senior")
        res = evaluate_seniority(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.PASS)
        self.assertFalse(res.is_applicable)

    # =======================================================================
    # WORK MODE & LOCATION TESTS (5-10)
    # =======================================================================

    def test_5_remote_only_candidate_vs_explicit_onsite_job_fails(self):
        """Remote-only candidate vs explicit onsite/hybrid job results in hard FAIL."""
        candidate = CandidateProfile(work_mode="remote")
        job = JobProfile(work_mode="onsite", location="bangalore")

        res = evaluate_work_mode_location(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.FAIL)
        self.assertIn("remote", res.reason.lower())
        self.assertIn("onsite", res.reason.lower())

        # Also test hybrid job
        job_hybrid = JobProfile(work_mode="hybrid", location="hyderabad")
        res_hybrid = evaluate_work_mode_location(candidate, job_hybrid)
        self.assertEqual(res_hybrid.status, ConstraintStatus.FAIL)

    def test_6_remote_candidate_vs_remote_job_passes(self):
        """Remote candidate vs remote job results in PASS."""
        candidate = CandidateProfile(work_mode="remote")
        job = JobProfile(work_mode="remote")

        res = evaluate_work_mode_location(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.PASS)
        self.assertTrue(res.is_applicable)

    def test_7_unknown_candidate_work_mode_vs_onsite_job_unknown(self):
        """Unknown candidate work mode vs onsite job results in UNKNOWN."""
        candidate = CandidateProfile(work_mode=None, current_location=None)
        job = JobProfile(work_mode="onsite", location="bangalore")

        res = evaluate_work_mode_location(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(res.is_applicable)

    def test_8_explicit_compatible_location_passes(self):
        """Explicit compatible location and work mode results in PASS."""
        candidate = CandidateProfile(
            work_mode="hybrid",
            current_location="hyderabad",
            preferred_locations=["hyderabad"],
        )
        job = JobProfile(work_mode="hybrid", location="hyderabad")

        res = evaluate_work_mode_location(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.PASS)
        self.assertIn("hyderabad", res.reason.lower())

    def test_9_ambiguous_location_information_unknown(self):
        """Candidate in Delhi vs onsite job in Bangalore without relocation info produces UNKNOWN."""
        candidate = CandidateProfile(
            work_mode="onsite",
            current_location="delhi",
            preferred_locations=["delhi"],
        )
        job = JobProfile(work_mode="onsite", location="bangalore")

        res = evaluate_work_mode_location(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.UNKNOWN)
        self.assertIn("relocation", res.reason.lower())

    def test_10_empty_location_not_treated_as_remote(self):
        """Empty job location/work-mode is NOT treated as remote (UNKNOWN != REMOTE)."""
        candidate = CandidateProfile(work_mode="remote")
        # Job has empty location and empty work_mode
        job = JobProfile(location=None, work_mode=None)

        res = evaluate_work_mode_location(candidate, job)
        # Should be not applicable (PASS) rather than matching or failing
        self.assertEqual(res.status, ConstraintStatus.PASS)
        self.assertFalse(res.is_applicable)

        # Job has city location but work_mode is None
        job_city_only = JobProfile(location="pune", work_mode=None)
        res_city = evaluate_work_mode_location(candidate, job_city_only)
        # Cannot assume Pune is remote! Must be UNKNOWN
        self.assertEqual(res_city.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(res_city.is_applicable)

    # =======================================================================
    # EMPLOYMENT TYPE TESTS (11-13)
    # =======================================================================

    def test_11_internship_preference_vs_explicit_full_time_job_fails(self):
        """Candidate seeking internship only vs explicit full-time job results in FAIL."""
        candidate = CandidateProfile(employment_preferences=["internship"])
        job = JobProfile(employment_type="full_time")

        res = evaluate_employment_type(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.FAIL)
        self.assertIn("internship", res.reason.lower())
        self.assertIn("full-time", res.reason.lower())

    def test_12_full_time_preference_vs_explicit_internship_job_fails(self):
        """Candidate seeking full-time only vs explicit internship job results in FAIL."""
        candidate = CandidateProfile(employment_preferences=["full_time"])
        job = JobProfile(employment_type="internship")

        res = evaluate_employment_type(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.FAIL)
        self.assertIn("full-time", res.reason.lower())
        self.assertIn("internship", res.reason.lower())

    def test_13_missing_candidate_preference_unknown(self):
        """Missing candidate employment preference vs explicit job employment type results in UNKNOWN."""
        candidate = CandidateProfile(employment_preferences=[])
        job = JobProfile(employment_type="full_time")

        res = evaluate_employment_type(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(res.is_applicable)

        # Student status must not automatically infer internship preference
        student_candidate = CandidateProfile(seniority="student", employment_preferences=[])
        res_student = evaluate_employment_type(student_candidate, job)
        self.assertEqual(res_student.status, ConstraintStatus.UNKNOWN)

    # =======================================================================
    # GRADUATION YEAR TESTS (14-17)
    # =======================================================================

    def test_14_explicit_incompatible_graduation_requirement_fails(self):
        """Explicit incompatible graduation requirement results in FAIL."""
        candidate = CandidateProfile(graduation_year=2028)
        job = JobProfile(graduation_year=2027)

        res = evaluate_graduation_year(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.FAIL)
        self.assertIn("2028", res.reason)
        self.assertIn("2027", res.reason)

    def test_15_missing_candidate_graduation_year_unknown(self):
        """Missing candidate graduation year when job specifies requirement results in UNKNOWN."""
        candidate = CandidateProfile(graduation_year=None)
        job = JobProfile(graduation_year=2027)

        res = evaluate_graduation_year(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(res.is_applicable)

    def test_16_compatible_graduation_requirement_passes(self):
        """Matching graduation requirement results in PASS."""
        candidate = CandidateProfile(graduation_year=2026)
        job = JobProfile(graduation_year=2026)

        res = evaluate_graduation_year(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.PASS)
        self.assertIn("2026", res.reason)

    def test_17_no_job_graduation_requirement_not_failure(self):
        """Job with no graduation requirement does not create an artificial failure or UNKNOWN."""
        candidate = CandidateProfile(graduation_year=None)
        job = JobProfile(graduation_year=None)

        res = evaluate_graduation_year(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.PASS)
        self.assertFalse(res.is_applicable)

    # =======================================================================
    # OVERALL EVALUATION TESTS (18-20)
    # =======================================================================

    def test_18_any_fail_causes_overall_fail(self):
        """Any single hard constraint failure causes overall evaluation to FAIL."""
        # Seniority passes, but work mode fails
        candidate = CandidateProfile(
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            seniority="senior",
            work_mode="onsite",
            employment_type="full_time",
        )
        overall = evaluate_constraints(candidate, job)
        self.assertEqual(overall.status, ConstraintStatus.FAIL)
        self.assertTrue(overall.failed)
        self.assertFalse(overall.passed)
        self.assertEqual(len(overall.failures), 1)
        self.assertEqual(overall.failures[0].constraint, "work_mode_location")

    def test_19_all_applicable_constraints_pass_causes_overall_pass(self):
        """When all applicable constraints pass, overall evaluation is PASS."""
        candidate = CandidateProfile(
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
            graduation_year=None,
        )
        job = JobProfile(
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
            graduation_year=None,  # Not applicable
        )
        overall = evaluate_constraints(candidate, job)
        self.assertEqual(overall.status, ConstraintStatus.PASS)
        self.assertTrue(overall.passed)
        self.assertFalse(overall.failed)
        self.assertFalse(overall.unknown)

    def test_20_no_fail_but_unresolved_applicable_produces_unknown(self):
        """No failures, but an unresolved applicable constraint produces overall UNKNOWN."""
        candidate = CandidateProfile(
            seniority="senior",
            work_mode=None,  # Unresolved for onsite job
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            seniority="senior",
            work_mode="onsite",
            employment_type="full_time",
        )
        overall = evaluate_constraints(candidate, job)
        self.assertEqual(overall.status, ConstraintStatus.UNKNOWN)
        self.assertTrue(overall.unknown)
        self.assertFalse(overall.failed)
        self.assertEqual(len(overall.unresolved), 1)
        self.assertEqual(overall.unresolved[0].constraint, "work_mode_location")

    # =======================================================================
    # SAFETY TESTS (21-25)
    # =======================================================================

    def test_21_missing_fields_never_become_automatic_fail(self):
        """Completely blank candidate profile never receives a hard FAIL."""
        blank_candidate = CandidateProfile()
        constrained_job = JobProfile(
            seniority="senior",
            work_mode="onsite",
            employment_type="full_time",
            graduation_year=2026,
        )
        overall = evaluate_constraints(blank_candidate, constrained_job)
        # Must be UNKNOWN, never FAIL
        self.assertEqual(overall.status, ConstraintStatus.UNKNOWN)
        self.assertFalse(overall.failed)
        self.assertEqual(len(overall.failures), 0)

    def test_22_low_confidence_does_not_create_unjustified_hard_fail(self):
        """LOW-confidence information turns potential contradictions into UNKNOWN, not FAIL."""
        # Low confidence seniority on candidate
        candidate = CandidateProfile(
            seniority="entry_level",
            confidence={"seniority": "LOW"},
        )
        job = JobProfile(seniority="senior")
        res = evaluate_seniority(candidate, job)
        self.assertEqual(res.status, ConstraintStatus.UNKNOWN)
        self.assertIn("confidence is low", res.reason.lower())

        # Low confidence employment preference
        candidate_emp = CandidateProfile(
            employment_preferences=["internship"],
            confidence={"employment": "LOW"},
        )
        job_emp = JobProfile(employment_type="full_time")
        res_emp = evaluate_employment_type(candidate_emp, job_emp)
        self.assertEqual(res_emp.status, ConstraintStatus.UNKNOWN)

    def test_23_no_skill_based_hard_failures(self):
        """Missing skills do NOT cause hard constraint failures."""
        candidate = CandidateProfile(
            normalized_skills=["python"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        # Job requires skills that candidate completely lacks
        job = JobProfile(
            required_skills=["rust", "c++", "kubernetes"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        overall = evaluate_constraints(candidate, job)
        # Overall must PASS hard constraints; skill matching belongs to soft matcher
        self.assertEqual(overall.status, ConstraintStatus.PASS)

    def test_24_deterministic_repeated_evaluation(self):
        """Multiple runs on the same profiles produce identical results."""
        candidate = CandidateProfile(
            seniority="junior",
            work_mode="hybrid",
            current_location="hyderabad",
            employment_preferences=["full_time"],
            graduation_year=2025,
        )
        job = JobProfile(
            seniority="junior",
            work_mode="hybrid",
            location="hyderabad",
            employment_type="full_time",
            graduation_year=2025,
        )
        eval1 = evaluate_constraints(candidate, job)
        eval2 = evaluate_constraints(candidate, job)

        self.assertEqual(eval1.status, eval2.status)
        self.assertEqual(eval1.to_dict(), eval2.to_dict())
        self.assertEqual(len(eval1.results), len(eval2.results))
        for r1, r2 in zip(eval1.results, eval2.results):
            self.assertEqual(r1.to_dict(), r2.to_dict())

    def test_25_candidate_and_job_profiles_not_mutated(self):
        """Profiles remain strictly immutable during evaluation."""
        candidate = CandidateProfile(
            seniority="entry_level",
            work_mode="remote",
            employment_preferences=["internship"],
            graduation_year=2027,
            normalized_skills=["python", "sql"],
        )
        job = JobProfile(
            title="Senior Data Analyst",
            seniority="senior",
            work_mode="onsite",
            employment_type="full_time",
            graduation_year=2026,
            required_skills=["python"],
        )

        cand_snap = candidate.to_dict()
        job_snap = job.to_dict()

        evaluate_constraints(candidate, job)

        self.assertEqual(candidate.to_dict(), cand_snap)
        self.assertEqual(job.to_dict(), job_snap)


    def test_26_unknown_job_employment_type_returns_unknown(self):
        """Unknown or unstated job employment type produces UNKNOWN status, not a hard FAIL."""
        candidate = CandidateProfile(
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Data Specialist",
            employment_type="unknown",
        )
        result = evaluate_employment_type(candidate, job)
        self.assertEqual(result.status, ConstraintStatus.UNKNOWN)
        self.assertFalse(result.status == ConstraintStatus.FAIL)
        self.assertIn("not specified", result.reason.lower())


if __name__ == "__main__":
    unittest.main()

