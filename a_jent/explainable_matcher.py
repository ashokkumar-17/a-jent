"""
Explainable Matcher Module
--------------------------
Deterministic, explainable soft-matching engine for A-Jent.

Answers the question:
    "Assuming there is no hard constraint incompatibility,
     how well does this candidate match this job?"

Features:
- Deterministic weighted scoring:
  - Required skills coverage: 50%
  - Role/title affinity: 25%
  - Preferred skills coverage: 10%
  - Experience alignment: 15%
- Gated by Hard Constraint Evaluator:
  - FAIL -> score 0.0, tier INCOMPATIBLE
  - UNKNOWN -> soft score computed, UNKNOWN status and concerns preserved
  - PASS -> normal soft match score computed
- Explainable MatchResult containing matched/missing skills, component scores,
  concerns, role evidence, and a human-readable summary.
- Standard library only, no LLMs, no embeddings, no external APIs.
- Standalone: does not modify or replace the legacy TF-IDF pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Optional

from a_jent import skill_taxonomy
from a_jent.candidate_profiler import CandidateProfile
from a_jent.job_normalizer import JobProfile
from a_jent.constraint_evaluator import (
    ConstraintEvaluation,
    ConstraintStatus,
    evaluate_constraints,
)

# ---------------------------------------------------------------------------
# SCORING CONSTANTS & WEIGHTS
# ---------------------------------------------------------------------------
# Initial heuristic weights (not calibrated probabilities)
WEIGHT_REQUIRED_SKILLS: float = 0.50
WEIGHT_ROLE_AFFINITY: float = 0.25
WEIGHT_PREFERRED_SKILLS: float = 0.10
WEIGHT_EXPERIENCE: float = 0.15

# Match Tier thresholds
THRESHOLD_STRONG: float = 75.0
THRESHOLD_MODERATE: float = 50.0


class MatchTier(str, Enum):
    """Deterministic match tiers based on transparent score thresholds."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INCOMPATIBLE = "INCOMPATIBLE"


# ---------------------------------------------------------------------------
# ROLE TRACKS & UNRELATED ROLE DICTIONARIES
# ---------------------------------------------------------------------------
ROLE_TRACKS = {
    "data_science_ml": {
        "keywords": [
            "data scientist",
            "machine learning",
            "ml engineer",
            "ai engineer",
            "deep learning",
            "research scientist",
            "data science",
            "nlp engineer",
            "computer vision engineer",
            "ai/ml",
            "predictive modeler",
            "quantitative researcher",
        ],
        "skills": {
            "machine learning",
            "deep learning",
            "pytorch",
            "tensorflow",
            "scikit-learn",
            "data science",
            "nlp",
            "computer vision",
            "large language models",
            "python",
            "pandas",
            "numpy",
        },
        "family": "data",
    },
    "data_analytics": {
        "keywords": [
            "data analyst",
            "business analyst",
            "bi analyst",
            "data analytics",
            "analytics engineer",
            "bi developer",
            "tableau developer",
            "power bi developer",
            "analytics",
            "business intelligence analyst",
            "business intelligence",
            "product analyst",
            "product growth analyst",
        ],
        "skills": {
            "data analysis",
            "sql",
            "pandas",
            "tableau",
            "power bi",
            "statistics",
            "python",
        },
        "family": "data",
    },
    "software_backend": {
        "keywords": [
            "software engineer",
            "software developer",
            "backend developer",
            "backend engineer",
            "full stack developer",
            "full stack engineer",
            "fullstack developer",
            "fullstack engineer",
            "full stack",
            "fullstack",
            "python developer",
            "java developer",
            "golang developer",
            "c++ developer",
            "api developer",
        ],
        "skills": {
            "python",
            "java",
            "c++",
            "go",
            "rust",
            "fastapi",
            "django",
            "flask",
            "node.js",
            "postgresql",
            "mysql",
            "mongodb",
            "redis",
            "rest api",
            "microservices",
        },
        "family": "software",
    },
    "frontend": {
        "keywords": [
            "frontend developer",
            "frontend engineer",
            "ui developer",
            "web developer",
            "react developer",
            "javascript developer",
            "typescript developer",
        ],
        "skills": {
            "javascript",
            "typescript",
            "react",
            "next.js",
            "html",
            "css",
        },
        "family": "software",
    },
    "devops_cloud": {
        "keywords": [
            "devops engineer",
            "cloud engineer",
            "platform engineer",
            "site reliability engineer",
            "sre",
            "infrastructure engineer",
            "cloud architect",
        ],
        "skills": {
            "docker",
            "kubernetes",
            "aws",
            "gcp",
            "azure",
            "ci/cd",
            "linux",
            "bash",
        },
        "family": "infra",
    },
}

UNRELATED_KEYWORDS = [
    "graphic designer",
    "ui/ux designer",
    "product designer",
    "art director",
    "illustrator",
    "hr recruiter",
    "human resources",
    "recruiter",
    "talent acquisition",
    "marketing manager",
    "marketing executive",
    "digital marketer",
    "sales executive",
    "sales manager",
    "account executive",
    "b2b sales",
    "accountant",
    "financial analyst",
    "legal counsel",
    "content writer",
    "copywriter",
    "office administrator",
    "receptionist",
    "customer support",
    "nurse",
    "teacher",
]


# ---------------------------------------------------------------------------
# STRUCTURED MATCH RESULT
# ---------------------------------------------------------------------------
@dataclass
class MatchResult:
    """Detailed, explainable matching result between candidate and job profile."""

    score: float
    tier: str
    hard_constraint_status: str
    hard_constraint_reasons: list[str] = field(default_factory=list)
    component_scores: dict[str, float] = field(default_factory=dict)
    matched_required_skills: list[str] = field(default_factory=list)
    missing_required_skills: list[str] = field(default_factory=list)
    matched_preferred_skills: list[str] = field(default_factory=list)
    missing_preferred_skills: list[str] = field(default_factory=list)
    role_evidence: str = ""
    concerns: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize match result to standard dictionary representation."""
        return {
            "score": self.score,
            "tier": self.tier,
            "hard_constraint_status": self.hard_constraint_status,
            "hard_constraint_reasons": list(self.hard_constraint_reasons),
            "component_scores": dict(self.component_scores),
            "matched_required_skills": list(self.matched_required_skills),
            "missing_required_skills": list(self.missing_required_skills),
            "matched_preferred_skills": list(self.matched_preferred_skills),
            "missing_preferred_skills": list(self.missing_preferred_skills),
            "role_evidence": self.role_evidence,
            "concerns": list(self.concerns),
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# INTERNAL EVALUATION HELPERS
# ---------------------------------------------------------------------------
def _evaluate_skills(
    candidate_skills: list[str],
    required_skills: list[str],
    preferred_skills: list[str],
) -> tuple[float, list[str], list[str], float, list[str], list[str]]:
    """Calculate required and preferred skill coverage deterministically.

    Returns:
        (req_coverage, matched_req, missing_req, pref_coverage, matched_pref, missing_pref)
    """
    cand_set = {s.lower().strip() for s in candidate_skills}

    # 1. Required skills coverage
    if not required_skills:
        # Missing/unspecified required skills: neutral baseline (0.50), not positive (1.0)
        req_cov = 0.50
        matched_req = []
        missing_req = []
    else:
        matched_req = [s for s in required_skills if s.lower().strip() in cand_set]
        missing_req = [s for s in required_skills if s.lower().strip() not in cand_set]
        req_cov = len(matched_req) / len(required_skills)

    # 2. Preferred skills coverage
    if not preferred_skills:
        # Missing/unspecified preferred skills: neutral baseline (0.50), not positive (1.0)
        pref_cov = 0.50
        matched_pref = []
        missing_pref = []
    else:
        matched_pref = [s for s in preferred_skills if s.lower().strip() in cand_set]
        missing_pref = [s for s in preferred_skills if s.lower().strip() not in cand_set]
        pref_cov = len(matched_pref) / len(preferred_skills)

    return req_cov, matched_req, missing_req, pref_cov, matched_pref, missing_pref


def _evaluate_role_affinity(
    candidate: CandidateProfile,
    job: JobProfile,
) -> tuple[float, str]:
    """Deterministically compare candidate role background with job title.

    Returns:
        (affinity_score [0.0 - 1.0], explanation_evidence)
    """
    job_title = job.title or ""
    t_lower = job_title.lower()

    # 1. Check for clearly unrelated roles
    for uk in UNRELATED_KEYWORDS:
        if uk in t_lower:
            return 0.05, f"Job title '{job_title}' represents an unrelated functional domain ({uk}) to candidate profile."

    # 2. Check if candidate profile is completely blank
    cand_skills = candidate.normalized_skills or []
    cand_evidence = candidate.evidence or {}
    if not cand_skills and not cand_evidence:
        return 0.50, "Candidate profile contains no role or skill indicators; neutral affinity assigned."

    # Collect all role keywords sorted by length descending (longest match wins)
    all_role_keywords = sorted(
        [
            (kw, track_name)
            for track_name, track_data in ROLE_TRACKS.items()
            for kw in track_data["keywords"]
        ],
        key=lambda x: len(x[0]),
        reverse=True,
    )

    # 3. Detect job role track (longest matching keyword wins)
    job_track: Optional[str] = None
    for kw, track_name in all_role_keywords:
        if kw in t_lower:
            job_track = track_name
            break

    # 4. Detect candidate role track from evidence (longest matching keyword wins)
    cand_track_from_ev: Optional[str] = None
    combined_ev = " ".join(str(v).lower() for v in cand_evidence.values())
    for kw, track_name in all_role_keywords:
        if kw in combined_ev:
            cand_track_from_ev = track_name
            break

    # 5. Detect candidate role track from skill concentrations
    skill_counts: dict[str, int] = {}
    for track_name, track_data in ROLE_TRACKS.items():
        count = sum(1 for s in cand_skills if s.lower().strip() in track_data["skills"])
        if count > 0:
            skill_counts[track_name] = count

    cand_skill_track = max(skill_counts, key=skill_counts.get) if skill_counts else None

    # 6. Compute deterministic affinity score
    if job_track:
        # A. Clearly aligned: exact role track match
        if cand_track_from_ev == job_track or cand_skill_track == job_track:
            return 1.0, f"Clearly aligned role: candidate profile directly aligns with '{job_track}' role domain for '{job_title}'."

        # B. Related role family (e.g. Data Science <-> Data Analytics, Backend <-> Frontend)
        job_family = ROLE_TRACKS[job_track]["family"]
        cand_family = (
            ROLE_TRACKS[cand_skill_track]["family"]
            if cand_skill_track
            else (ROLE_TRACKS[cand_track_from_ev]["family"] if cand_track_from_ev else None)
        )
        if cand_family and cand_family == job_family:
            return 0.85, f"Related role alignment: candidate '{cand_skill_track or cand_track_from_ev}' domain is closely related to job '{job_track}'."

        # C. Adjacent engineering / data domains
        if cand_skill_track and job_track in ("data_science_ml", "software_backend"):
            return 0.75, f"Cross-domain technical alignment: candidate skills provide relevant foundation for '{job_track}'."

        return 0.60, f"Moderate technical alignment with '{job_track}'."

    # If job title is a non-standard or broad tech title (e.g. 'Platform Specialist', 'Lead Technologist')
    if cand_skill_track:
        return 0.70, f"Candidate technical profile provides positive general alignment for '{job_title}'."

    return 0.50, f"Neutral role alignment for '{job_title}'."


def _evaluate_experience_alignment(
    candidate: CandidateProfile,
    job: JobProfile,
) -> tuple[float, str, Optional[str]]:
    """Evaluate soft alignment between candidate and job experience requirements.

    Returns:
        (experience_score [0.0 - 1.0], evidence_message, optional_concern)
    """
    job_exp = job.experience_years
    cand_exp = candidate.experience_years

    # 1. Job specifies no experience requirement: no penalty
    if job_exp is None:
        return 1.0, "Job specifies no minimum experience requirement.", None

    # 2. Candidate experience is unknown: neutral baseline, not a failure
    if cand_exp is None:
        return (
            0.50,
            f"Job specifies minimum {job_exp} yrs experience, but candidate experience is unknown.",
            f"Candidate experience duration is not specified (job requires {job_exp} yrs).",
        )

    # 3. Candidate meets or exceeds requirement
    if cand_exp >= job_exp:
        return (
            1.0,
            f"Candidate experience ({cand_exp} yrs) meets or exceeds job requirement ({job_exp} yrs).",
            None,
        )

    # 4. Candidate appears below explicit minimum requirement
    # ponytail: Linear ratio floor at 0.20 is an initial heuristic for the soft experience signal.
    ratio = (cand_exp / job_exp) if job_exp > 0 else 1.0
    score = max(0.20, min(0.90, ratio))
    concern = f"Candidate experience ({cand_exp} yrs) is below stated job requirement ({job_exp} yrs)."
    evidence = f"Candidate experience ({cand_exp} yrs) is below job requirement ({job_exp} yrs)."
    return score, evidence, concern


def _determine_tier(score: float, hard_constraint_status: str) -> str:
    """Determine match tier from score and hard constraint status."""
    if hard_constraint_status == ConstraintStatus.FAIL.value:
        return MatchTier.INCOMPATIBLE.value
    if score >= THRESHOLD_STRONG:
        return MatchTier.STRONG.value
    if score >= THRESHOLD_MODERATE:
        return MatchTier.MODERATE.value
    return MatchTier.WEAK.value


def _build_explanation(
    score: float,
    tier: str,
    hard_status: str,
    hard_reasons: list[str],
    matched_req: list[str],
    missing_req: list[str],
    matched_pref: list[str],
    missing_pref: list[str],
    req_total: int,
    pref_total: int,
    role_evidence: str,
    exp_evidence: str,
) -> str:
    """Assemble a clear, evidence-based human-readable explanation."""
    parts = []

    if hard_status == ConstraintStatus.FAIL.value:
        reasons_text = "; ".join(hard_reasons)
        return f"Match score: 0.0/100 (Tier: INCOMPATIBLE). Candidate is incompatible due to hard constraint failure: {reasons_text}."

    parts.append(f"Match score: {score:.1f}/100 (Tier: {tier})")

    if hard_status == ConstraintStatus.UNKNOWN.value:
        reasons_text = "; ".join(hard_reasons)
        parts.append(f"Unresolved constraints: {reasons_text}")

    # Required skills
    if req_total == 0:
        parts.append("Required skills: job specifies no explicit required skills (neutral baseline assigned).")
    else:
        req_summary = f"Required skills: {len(matched_req)} of {req_total} matched"
        if matched_req:
            req_summary += f" ({', '.join(matched_req)})"
        if missing_req:
            req_summary += f"; missing: {', '.join(missing_req)}"
        parts.append(req_summary + ".")

    # Role alignment
    parts.append(f"Role affinity: {role_evidence}")

    # Preferred skills
    if pref_total == 0:
        parts.append("Preferred skills: job specifies no preferred skills (neutral baseline assigned).")
    else:
        pref_summary = f"Preferred skills: {len(matched_pref)} of {pref_total} matched"
        if matched_pref:
            pref_summary += f" ({', '.join(matched_pref)})"
        if missing_pref:
            pref_summary += f"; missing: {', '.join(missing_pref)}"
        parts.append(pref_summary + ".")

    # Experience alignment
    parts.append(f"Experience: {exp_evidence}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# PUBLIC MATCHING API
# ---------------------------------------------------------------------------
def match_candidate_to_job(
    candidate: CandidateProfile,
    job: JobProfile,
) -> MatchResult:
    """Calculate deterministic, explainable match between candidate and job profile.

    Args:
        candidate: CandidateProfile representing extracted resume capabilities.
        job: JobProfile representing structured job requirements.

    Returns:
        MatchResult with score (0-100), tier, components, concerns, and explanation.
    """
    concerns: list[str] = []

    # 1. Hard Constraints Gate
    constraint_eval = evaluate_constraints(candidate, job)
    hard_status = constraint_eval.status.value
    hard_reasons = list(constraint_eval.reasons)

    if constraint_eval.status == ConstraintStatus.FAIL:
        concerns.extend(hard_reasons)
        explanation = _build_explanation(
            score=0.0,
            tier=MatchTier.INCOMPATIBLE.value,
            hard_status=hard_status,
            hard_reasons=hard_reasons,
            matched_req=[],
            missing_req=list(job.required_skills),
            matched_pref=[],
            missing_pref=list(job.preferred_skills),
            req_total=len(job.required_skills),
            pref_total=len(job.preferred_skills),
            role_evidence="Hard constraint incompatibility.",
            exp_evidence="Evaluation blocked by hard constraint failure.",
        )
        return MatchResult(
            score=0.0,
            tier=MatchTier.INCOMPATIBLE.value,
            hard_constraint_status=hard_status,
            hard_constraint_reasons=hard_reasons,
            component_scores={
                "required_skills": 0.0,
                "role_affinity": 0.0,
                "preferred_skills": 0.0,
                "experience_alignment": 0.0,
            },
            matched_required_skills=[],
            missing_required_skills=list(job.required_skills),
            matched_preferred_skills=[],
            missing_preferred_skills=list(job.preferred_skills),
            role_evidence="Hard constraint incompatibility.",
            concerns=concerns,
            explanation=explanation,
        )

    if constraint_eval.status == ConstraintStatus.UNKNOWN:
        for r in hard_reasons:
            concerns.append(f"Unresolved constraint: {r}")

    # 2. Required and Preferred Skills Coverage
    req_cov, matched_req, missing_req, pref_cov, matched_pref, missing_pref = _evaluate_skills(
        candidate_skills=candidate.normalized_skills,
        required_skills=job.required_skills,
        preferred_skills=job.preferred_skills,
    )
    if missing_req:
        concerns.append(f"Missing required skill(s): {', '.join(missing_req)}")

    # 3. Role/Title Affinity
    role_aff, role_evidence = _evaluate_role_affinity(candidate, job)
    if role_aff < 0.50:
        concerns.append(f"Low role affinity ({round(role_aff * 100)}%): {role_evidence}")

    # 4. Experience Alignment
    exp_align, exp_evidence, exp_concern = _evaluate_experience_alignment(candidate, job)
    if exp_concern:
        concerns.append(exp_concern)

    # 5. Weighted Soft-Match Score Calculation (0 - 100)
    # ponytail: Fixed heuristic weights (50/25/10/15) establish deterministic baseline.
    raw_score = (
        WEIGHT_REQUIRED_SKILLS * req_cov
        + WEIGHT_ROLE_AFFINITY * role_aff
        + WEIGHT_PREFERRED_SKILLS * pref_cov
        + WEIGHT_EXPERIENCE * exp_align
    )
    score = round(raw_score * 100.0, 1)

    # 6. Determine Match Tier
    tier = _determine_tier(score, hard_status)

    # 7. Component Scores Dict (normalized 0-100 for explainability)
    component_scores = {
        "required_skills": round(req_cov * 100.0, 1),
        "role_affinity": round(role_aff * 100.0, 1),
        "preferred_skills": round(pref_cov * 100.0, 1),
        "experience_alignment": round(exp_align * 100.0, 1),
    }

    # 8. Assemble Full Explanation
    explanation = _build_explanation(
        score=score,
        tier=tier,
        hard_status=hard_status,
        hard_reasons=hard_reasons,
        matched_req=matched_req,
        missing_req=missing_req,
        matched_pref=matched_pref,
        missing_pref=missing_pref,
        req_total=len(job.required_skills),
        pref_total=len(job.preferred_skills),
        role_evidence=role_evidence,
        exp_evidence=exp_evidence,
    )

    return MatchResult(
        score=score,
        tier=tier,
        hard_constraint_status=hard_status,
        hard_constraint_reasons=hard_reasons,
        component_scores=component_scores,
        matched_required_skills=matched_req,
        missing_required_skills=missing_req,
        matched_preferred_skills=matched_pref,
        missing_preferred_skills=missing_pref,
        role_evidence=role_evidence,
        concerns=concerns,
        explanation=explanation,
    )


# Clean alias
match_job = match_candidate_to_job
