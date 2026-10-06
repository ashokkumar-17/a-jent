"""
Automated Tests for Task 17: Explainable Matcher (a_jent/explainable_matcher.py)
--------------------------------------------------------------------------------
Verifies:
Required skills:
1. All required skills matched -> 100% required skill component score.
2. Partial required skill match -> proportional component score.
3. No required skills in job -> neutral 50% baseline coverage, not positive 100%.
4. No candidate skills -> 0% required skill coverage when job has requirements.
5. Missing required skills are correctly reported in missing_required_skills.

Preferred skills:
6. All preferred skills matched -> 100% preferred skill component score.
7. Partial preferred match -> proportional component score.
8. No preferred skills in job -> neutral 50% baseline coverage, not positive 100%.
9. Preferred skills do not dominate required skills (50% vs 10% weighting).

Hard constraints:
10. Hard constraint PASS allows normal soft matching.
11. Hard constraint FAIL produces score = 0.0 and tier = INCOMPATIBLE.
12. Hard constraint UNKNOWN computes soft score without automatic rejection.

Role affinity:
13. Clearly aligned roles -> role affinity score = 100%.
14. Related roles (e.g. Data Scientist <-> ML Engineer, Backend <-> Fullstack) -> high affinity.
15. Unrelated roles (e.g. Software Engineer <-> Graphic Designer, HR Recruiter) -> low affinity <= 10%.
16. Missing candidate role information -> neutral 50% baseline affinity.

Experience alignment:
17. Candidate meets requirement -> experience score = 100%.
18. Candidate exceeds requirement -> experience score = 100%.
19. Candidate below requirement -> proportional experience score with concern.
20. Missing candidate experience -> neutral 50% baseline with concern.
21. Missing job experience requirement -> 100% score, no penalty.

Explainability & Structure:
22. Matched and missing skills are accurately reported.
23. Component scores are broken down and available in result.
24. Concerns list concrete issues (missing skills, experience gap, unresolved constraints).
25. Human-readable explanation traces to actual component values.

Determinism & Immutability:
26. Repeated execution produces identical MatchResult objects.
27. CandidateProfile and JobProfile are not mutated during matching.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent.candidate_profiler import CandidateProfile
from a_jent.job_normalizer import JobProfile
from a_jent.explainable_matcher import (
    MatchResult,
    MatchTier,
    match_candidate_to_job,
    match_job,
)


class TestExplainableMatcher(unittest.TestCase):
    # =======================================================================
    # REQUIRED SKILLS TESTS (1-5)
    # =======================================================================

    def test_1_all_required_skills_matched(self):
        """All required skills present in candidate profile yields 100% required coverage."""
        candidate = CandidateProfile(
            normalized_skills=["python", "sql", "pandas"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Python Developer",
            required_skills=["python", "sql", "pandas"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["required_skills"], 100.0)
        self.assertEqual(set(result.matched_required_skills), {"python", "sql", "pandas"})
        self.assertEqual(result.missing_required_skills, [])

    def test_2_partial_required_skill_match(self):
        """Partial required skills matched yields proportional coverage (e.g. 2/4 = 50%)."""
        candidate = CandidateProfile(
            normalized_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Data Analyst",
            required_skills=["python", "sql", "pandas", "tableau"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["required_skills"], 50.0)
        self.assertEqual(set(result.matched_required_skills), {"python", "sql"})
        self.assertEqual(set(result.missing_required_skills), {"pandas", "tableau"})

    def test_3_no_required_skills_in_job(self):
        """Job with no explicit required skills assigns neutral 50% baseline rather than positive 100%."""
        candidate = CandidateProfile(
            normalized_skills=["python"],
            seniority="junior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Junior Software Engineer",
            required_skills=[],
            seniority="junior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["required_skills"], 50.0)
        self.assertEqual(result.matched_required_skills, [])
        self.assertEqual(result.missing_required_skills, [])

    def test_4_no_candidate_skills(self):
        """Candidate with no skills gets 0% required skill coverage when job has requirements."""
        candidate = CandidateProfile(
            normalized_skills=[],
            seniority="junior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Junior Developer",
            required_skills=["python", "sql"],
            seniority="junior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["required_skills"], 0.0)
        self.assertEqual(result.matched_required_skills, [])
        self.assertEqual(set(result.missing_required_skills), {"python", "sql"})

    def test_5_missing_required_skills_reported(self):
        """Missing required skills are listed in missing_required_skills and concerns."""
        candidate = CandidateProfile(
            normalized_skills=["python"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Engineer",
            required_skills=["python", "docker", "kubernetes"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(set(result.missing_required_skills), {"docker", "kubernetes"})
        self.assertTrue(any("docker" in c and "kubernetes" in c for c in result.concerns))

    # =======================================================================
    # PREFERRED SKILLS TESTS (6-9)
    # =======================================================================

    def test_6_all_preferred_skills_matched(self):
        """All preferred skills matched yields 100% preferred coverage."""
        candidate = CandidateProfile(
            normalized_skills=["python", "aws", "docker"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Developer",
            required_skills=["python"],
            preferred_skills=["aws", "docker"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["preferred_skills"], 100.0)
        self.assertEqual(set(result.matched_preferred_skills), {"aws", "docker"})
        self.assertEqual(result.missing_preferred_skills, [])

    def test_7_partial_preferred_match(self):
        """Partial preferred match yields proportional coverage (1/2 = 50%)."""
        candidate = CandidateProfile(
            normalized_skills=["python", "aws"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Developer",
            required_skills=["python"],
            preferred_skills=["aws", "docker"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["preferred_skills"], 50.0)
        self.assertEqual(result.matched_preferred_skills, ["aws"])
        self.assertEqual(result.missing_preferred_skills, ["docker"])

    def test_8_no_preferred_skills_in_job(self):
        """Job with no preferred skills assigns neutral 50% baseline rather than positive 100%."""
        candidate = CandidateProfile(
            normalized_skills=["python"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Developer",
            required_skills=["python"],
            preferred_skills=[],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["preferred_skills"], 50.0)
        self.assertEqual(result.matched_preferred_skills, [])

    def test_9_preferred_skills_do_not_dominate_required(self):
        """Candidate with 100% preferred but 0% required scores lower than candidate with 100% required but 0% preferred."""
        # Candidate A: has all required (weight 50%), 0 preferred
        candidate_a = CandidateProfile(
            normalized_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        # Candidate B: has all preferred (weight 10%), 0 required
        candidate_b = CandidateProfile(
            normalized_skills=["aws", "docker"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Software Engineer",
            required_skills=["python", "sql"],
            preferred_skills=["aws", "docker"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )

        res_a = match_candidate_to_job(candidate_a, job)
        res_b = match_candidate_to_job(candidate_b, job)

        self.assertGreater(res_a.score, res_b.score)
        self.assertGreaterEqual(res_a.score - res_b.score, 30.0)

    # =======================================================================
    # HARD CONSTRAINTS GATING TESTS (10-12)
    # =======================================================================

    def test_10_hard_constraint_pass_calculates_soft_score(self):
        """When hard constraints PASS, normal positive soft match score is calculated."""
        candidate = CandidateProfile(
            normalized_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Software Engineer",
            required_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.hard_constraint_status, "PASS")
        self.assertGreaterEqual(result.score, 75.0)
        self.assertEqual(result.tier, MatchTier.STRONG.value)

    def test_11_hard_constraint_fail_produces_zero_and_incompatible(self):
        """Hard constraint failure gates score to 0.0 and tier to INCOMPATIBLE."""
        # Entry-level candidate applying to senior role (hard constraint failure)
        candidate = CandidateProfile(
            normalized_skills=["python", "sql", "aws", "docker"],  # strong skills
            seniority="entry_level",
            work_mode="remote",
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Software Engineer",
            required_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.tier, MatchTier.INCOMPATIBLE.value)
        self.assertEqual(result.hard_constraint_status, "FAIL")
        self.assertTrue(len(result.hard_constraint_reasons) > 0)
        self.assertTrue(len(result.concerns) > 0)

    def test_12_hard_constraint_unknown_does_not_reject_candidate(self):
        """Hard constraint UNKNOWN computes soft-match score while preserving UNKNOWN status and concerns."""
        # Candidate work mode is unknown, job is onsite
        candidate = CandidateProfile(
            normalized_skills=["python", "sql"],
            seniority="senior",
            work_mode=None,  # unstated
            employment_preferences=["full_time"],
        )
        job = JobProfile(
            title="Senior Software Engineer",
            required_skills=["python", "sql"],
            seniority="senior",
            work_mode="onsite",
            location="bangalore",
            employment_type="full_time",
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.hard_constraint_status, "UNKNOWN")
        # Must NOT be score 0 or INCOMPATIBLE
        self.assertGreater(result.score, 0.0)
        self.assertNotEqual(result.tier, MatchTier.INCOMPATIBLE.value)
        # Unresolved constraint must be in concerns and explanation
        self.assertTrue(any("unresolved" in c.lower() for c in result.concerns))
        self.assertIn("unresolved", result.explanation.lower())

    # =======================================================================
    # ROLE AFFINITY TESTS (13-16)
    # =======================================================================

    def test_13_clearly_aligned_roles(self):
        """Clearly aligned role (Data Scientist vs Data Scientist) yields 100% role affinity."""
        candidate = CandidateProfile(
            normalized_skills=["python", "machine learning", "pytorch", "pandas"],
            evidence={"seniority": "Senior Data Scientist at TechCorp"},
        )
        job = JobProfile(
            title="Senior Data Scientist",
            required_skills=["python", "machine learning"],
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.component_scores["role_affinity"], 100.0)
        self.assertIn("clearly aligned", result.role_evidence.lower())

    def test_14_related_roles(self):
        """Related roles (Data Scientist <-> Machine Learning Engineer or Backend <-> Software Engineer) receive high affinity."""
        candidate = CandidateProfile(
            normalized_skills=["python", "machine learning", "pytorch"],
            evidence={"seniority": "Data Scientist"},
        )
        job = JobProfile(
            title="Machine Learning Engineer",
            required_skills=["python", "machine learning"],
        )
        result = match_candidate_to_job(candidate, job)

        # Related role affinity is high (>= 85%)
        self.assertGreaterEqual(result.component_scores["role_affinity"], 85.0)

    def test_15_unrelated_roles(self):
        """Clearly unrelated roles (e.g. Software Engineer vs Graphic Designer or HR Recruiter) receive low affinity."""
        candidate = CandidateProfile(
            normalized_skills=["python", "fastapi", "postgresql"],
            evidence={"seniority": "Backend Developer"},
        )
        job_designer = JobProfile(
            title="Graphic Designer",
            required_skills=[],
        )
        job_hr = JobProfile(
            title="HR Recruiter",
            required_skills=[],
        )

        res_des = match_candidate_to_job(candidate, job_designer)
        res_hr = match_candidate_to_job(candidate, job_hr)

        self.assertLessEqual(res_des.component_scores["role_affinity"], 10.0)
        self.assertLessEqual(res_hr.component_scores["role_affinity"], 10.0)
        self.assertTrue(any("unrelated" in c.lower() for c in res_des.concerns))

    def test_16_missing_candidate_role_information(self):
        """Missing candidate role indicators assign a neutral 50% baseline affinity."""
        blank_candidate = CandidateProfile(normalized_skills=[], evidence={})
        job = JobProfile(title="Software Engineer")

        result = match_candidate_to_job(blank_candidate, job)
        self.assertEqual(result.component_scores["role_affinity"], 50.0)
        self.assertIn("neutral", result.role_evidence.lower())

    # =======================================================================
    # EXPERIENCE ALIGNMENT TESTS (17-21)
    # =======================================================================

    def test_17_candidate_meets_experience_requirement(self):
        """Candidate meeting exact required experience gets 100% experience alignment score."""
        candidate = CandidateProfile(experience_years=2.0)
        job = JobProfile(title="Developer", experience_years=2.0)

        result = match_candidate_to_job(candidate, job)
        self.assertEqual(result.component_scores["experience_alignment"], 100.0)

    def test_18_candidate_exceeds_experience_requirement(self):
        """Candidate exceeding required experience gets 100% experience alignment score."""
        candidate = CandidateProfile(experience_years=5.0)
        job = JobProfile(title="Developer", experience_years=2.0)

        result = match_candidate_to_job(candidate, job)
        self.assertEqual(result.component_scores["experience_alignment"], 100.0)

    def test_19_candidate_below_experience_requirement(self):
        """Candidate below required experience receives proportional score and concern."""
        candidate = CandidateProfile(experience_years=1.0)
        job = JobProfile(title="Senior Developer", experience_years=4.0)

        result = match_candidate_to_job(candidate, job)
        self.assertLess(result.component_scores["experience_alignment"], 100.0)
        self.assertTrue(any("below" in c.lower() and "experience" in c.lower() for c in result.concerns))

    def test_20_missing_candidate_experience(self):
        """Missing candidate experience produces neutral 50% baseline and concern."""
        candidate = CandidateProfile(experience_years=None)
        job = JobProfile(title="Developer", experience_years=3.0)

        result = match_candidate_to_job(candidate, job)
        self.assertEqual(result.component_scores["experience_alignment"], 50.0)
        self.assertTrue(any("duration is not specified" in c.lower() for c in result.concerns))

    def test_21_missing_job_experience_requirement(self):
        """Job with no experience requirement awards 100% alignment without penalty."""
        candidate = CandidateProfile(experience_years=None)
        job = JobProfile(title="Developer", experience_years=None)

        result = match_candidate_to_job(candidate, job)
        self.assertEqual(result.component_scores["experience_alignment"], 100.0)

    # =======================================================================
    # EXPLAINABILITY & STRUCTURE TESTS (22-25)
    # =======================================================================

    def test_22_matched_and_missing_skills_accurately_reported(self):
        """Matched and missing skills are explicitly and cleanly partitioned."""
        candidate = CandidateProfile(normalized_skills=["python", "sql", "docker"])
        job = JobProfile(
            title="Software Developer",
            required_skills=["python", "postgresql", "fastapi"],
            preferred_skills=["docker", "aws"],
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.matched_required_skills, ["python"])
        self.assertEqual(set(result.missing_required_skills), {"postgresql", "fastapi"})
        self.assertEqual(result.matched_preferred_skills, ["docker"])
        self.assertEqual(result.missing_preferred_skills, ["aws"])

    def test_23_component_scores_breakdown_available(self):
        """Component scores dictionary contains all 4 components (0-100)."""
        candidate = CandidateProfile(
            normalized_skills=["python"],
            experience_years=2.0,
            seniority="junior",
        )
        job = JobProfile(
            title="Junior Python Developer",
            required_skills=["python"],
            seniority="junior",
            experience_years=1.0,
        )
        result = match_candidate_to_job(candidate, job)

        self.assertIn("required_skills", result.component_scores)
        self.assertIn("role_affinity", result.component_scores)
        self.assertIn("preferred_skills", result.component_scores)
        self.assertIn("experience_alignment", result.component_scores)
        for val in result.component_scores.values():
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 100.0)

    def test_24_concerns_list_concrete_issues(self):
        """Concerns list includes concrete missing items and gaps."""
        candidate = CandidateProfile(
            normalized_skills=["python"],
            experience_years=1.0,
            seniority="junior",
        )
        job = JobProfile(
            title="Senior Developer",
            required_skills=["python", "sql"],
            seniority="senior",
            experience_years=3.0,
        )
        # Note: seniority difference causes hard failure
        result = match_candidate_to_job(candidate, job)
        self.assertTrue(len(result.concerns) > 0)
        self.assertTrue(any("junior" in c.lower() or "senior" in c.lower() for c in result.concerns))

    def test_25_human_readable_explanation_traces_to_evidence(self):
        """Explanation explicitly incorporates score, tier, skills, role, and experience."""
        candidate = CandidateProfile(
            normalized_skills=["python", "pandas", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
            experience_years=4.0,
        )
        job = JobProfile(
            title="Senior Data Analyst",
            required_skills=["python", "pandas", "sql", "tableau"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
            experience_years=3.0,
        )
        result = match_candidate_to_job(candidate, job)

        explanation = result.explanation
        self.assertIn("Match score:", explanation)
        self.assertIn("Required skills:", explanation)
        self.assertIn("tableau", explanation)
        self.assertIn("Role affinity:", explanation)
        self.assertIn("Experience:", explanation)

    # =======================================================================
    # DETERMINISM & IMMUTABILITY (26-27)
    # =======================================================================

    def test_26_deterministic_repeated_matching(self):
        """Repeated matching on the same candidate and job yields identical results."""
        candidate = CandidateProfile(
            normalized_skills=["python", "sql", "aws"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
            experience_years=3.0,
        )
        job = JobProfile(
            title="Senior Software Engineer",
            required_skills=["python", "sql"],
            preferred_skills=["aws"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
            experience_years=2.0,
        )

        res1 = match_candidate_to_job(candidate, job)
        res2 = match_candidate_to_job(candidate, job)

        self.assertEqual(res1.score, res2.score)
        self.assertEqual(res1.tier, res2.tier)
        self.assertEqual(res1.to_dict(), res2.to_dict())

    def test_27_candidate_and_job_profiles_not_mutated(self):
        """CandidateProfile and JobProfile remain unchanged after matching."""
        candidate = CandidateProfile(
            normalized_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            experience_years=4.0,
        )
        job = JobProfile(
            title="Senior Software Engineer",
            required_skills=["python", "sql"],
            preferred_skills=["docker"],
            seniority="senior",
            work_mode="remote",
            experience_years=3.0,
        )

        cand_snapshot = candidate.to_dict()
        job_snapshot = job.to_dict()

        match_candidate_to_job(candidate, job)

        self.assertEqual(candidate.to_dict(), cand_snapshot)
        self.assertEqual(job.to_dict(), job_snapshot)


    # =======================================================================
    # CALIBRATION & ROLE SPECIFICITY TESTS (28-31)
    # =======================================================================

    def test_28_account_executive_and_b2b_sales_recognized_as_unrelated(self):
        """Account Executive and B2B sales roles are recognized as unrelated to tech profiles."""
        candidate = CandidateProfile(
            normalized_skills=["python", "fastapi", "docker"],
            evidence={"role_target": "Backend Engineer"},
        )
        job_ae = JobProfile(
            title="Enterprise Account Executive - SaaS Sales",
            required_skills=["b2b sales", "crm"],
        )
        result = match_candidate_to_job(candidate, job_ae)
        self.assertLessEqual(result.component_scores["role_affinity"], 10.0)
        self.assertTrue(any("unrelated" in c.lower() for c in result.concerns))

    def test_29_business_intelligence_and_product_analyst_role_tracks(self):
        """Unabbreviated Business Intelligence and Product Analyst match data_analytics track."""
        candidate = CandidateProfile(
            normalized_skills=["sql", "tableau", "power bi", "data analysis"],
            evidence={"role_target": "Data Analyst"},
        )
        job_bi = JobProfile(
            title="Business Intelligence Analyst",
            required_skills=["sql", "power bi"],
        )
        job_prod = JobProfile(
            title="Product Growth Analyst",
            required_skills=["sql"],
        )
        res_bi = match_candidate_to_job(candidate, job_bi)
        res_prod = match_candidate_to_job(candidate, job_prod)
        self.assertEqual(res_bi.component_scores["role_affinity"], 100.0)
        self.assertEqual(res_prod.component_scores["role_affinity"], 100.0)

    def test_30_predictive_modeler_and_quantitative_researcher_role_tracks(self):
        """Predictive modeler and quantitative researcher match data_science_ml track."""
        candidate = CandidateProfile(
            normalized_skills=["python", "machine learning", "pytorch"],
            evidence={"role_target": "Data Scientist"},
        )
        job_quant = JobProfile(
            title="Predictive Modeler & Quantitative Researcher",
            required_skills=["python", "sql"],
        )
        result = match_candidate_to_job(candidate, job_quant)
        self.assertEqual(result.component_scores["role_affinity"], 100.0)

    def test_31_longest_keyword_matching_prevents_subphrase_masking(self):
        """Frontend and DevOps titles are not prematurely masked by software_backend keywords."""
        candidate_fe = CandidateProfile(
            normalized_skills=["javascript", "typescript", "react"],
            evidence={"role_target": "Frontend Developer"},
        )
        candidate_be = CandidateProfile(
            normalized_skills=["python", "fastapi"],
            evidence={"role_target": "Backend Engineer"},
        )
        job_fe = JobProfile(
            title="Senior Frontend Developer",
            required_skills=["react", "typescript"],
        )
        # Frontend candidate matching Frontend job must yield 100%
        res_fe = match_candidate_to_job(candidate_fe, job_fe)
        self.assertEqual(res_fe.component_scores["role_affinity"], 100.0)
        self.assertIn("frontend", res_fe.role_evidence.lower())

        # Backend candidate evaluating Frontend job should get related family (85%), NOT exact software_backend match (100%)
        res_be = match_candidate_to_job(candidate_be, job_fe)
        self.assertEqual(res_be.component_scores["role_affinity"], 85.0)

    # =======================================================================
    # TASK 20B: SPARSE & UNDERSPECIFIED JOB SCORING TESTS (32-34)
    # =======================================================================

    def test_32_sparse_job_scoring_calibration(self):
        """Sparse job with no skills specified does not receive inflated STRONG score."""
        candidate = CandidateProfile(
            normalized_skills=["python", "sql", "machine learning"],
            evidence={"role_target": "Data Analyst"},
        )
        job = JobProfile(
            title="Data Analyst",
            required_skills=[],
            preferred_skills=[],
            experience_years=None,
        )
        result = match_candidate_to_job(candidate, job)

        # Missing required and preferred skills receive neutral 50.0 baseline
        self.assertEqual(result.component_scores["required_skills"], 50.0)
        self.assertEqual(result.component_scores["preferred_skills"], 50.0)
        self.assertEqual(result.component_scores["role_affinity"], 100.0)
        self.assertEqual(result.component_scores["experience_alignment"], 100.0)

        # Raw score = 0.50*0.50 + 0.25*1.0 + 0.10*0.50 + 0.15*1.0 = 0.25 + 0.25 + 0.05 + 0.15 = 0.70
        self.assertEqual(result.score, 70.0)
        self.assertEqual(result.tier, MatchTier.MODERATE.value)
        # Verify score is not inflated into STRONG tier (>= 75.0)
        self.assertLess(result.score, 75.0)

    def test_33_sparse_job_missing_skills_does_not_fail_candidate(self):
        """Missing job skills remain neutral and do not produce candidate failure or false missing-skill concerns."""
        candidate = CandidateProfile(
            normalized_skills=["python", "fastapi"],
            experience_years=3.0,
        )
        job = JobProfile(
            title="Software Developer",
            required_skills=[],
            preferred_skills=[],
            experience_years=None,
        )
        result = match_candidate_to_job(candidate, job)

        self.assertEqual(result.missing_required_skills, [])
        self.assertEqual(result.missing_preferred_skills, [])
        self.assertFalse(any("missing required skill" in c.lower() for c in result.concerns))
        # Unknown skills must not become candidate failure (0.0)
        self.assertGreater(result.component_scores["required_skills"], 0.0)
        self.assertGreater(result.score, 50.0)

    def test_34_missing_job_skills_explanation_indicates_neutral_baseline(self):
        """Explanation explicitly clarifies that neutral baseline was assigned for absent skills."""
        candidate = CandidateProfile(normalized_skills=["python"])
        job = JobProfile(
            title="Junior Python Developer",
            required_skills=[],
            preferred_skills=[],
        )
        result = match_candidate_to_job(candidate, job)

        self.assertIn("neutral baseline", result.explanation.lower())


if __name__ == "__main__":
    unittest.main()

