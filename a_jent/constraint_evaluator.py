"""
Hard Constraint Evaluator Module
--------------------------------
Deterministically evaluates hard eligibility constraints between CandidateProfile
and JobProfile to produce a three-state decision: PASS, FAIL, or UNKNOWN.

Evaluated Constraints:
1. Seniority exclusion (e.g. Intern/Entry-Level vs Senior/Lead)
2. Work mode / location (e.g. Remote-only vs Onsite, Location compatibility)
3. Employment type (e.g. Internship preference vs Full-time role)
4. Graduation year (e.g. Batch/class year requirement compatibility)

Guarantees:
- Deterministic: same candidate + job -> identical ConstraintEvaluation
- Three-state logic: PASS, FAIL, UNKNOWN (UNKNOWN != FAIL, UNKNOWN != PASS)
- Conservative: Hard FAIL ONLY on explicit high-confidence contradiction
- Low-confidence protection: Ambiguous / LOW-confidence data returns UNKNOWN, never unjustified FAIL
- Non-mutating: preserves both CandidateProfile and JobProfile unchanged
- Non-scoring: produces NO match scores, rankings, or probabilities
- No skills evaluated: skill matching belongs to the soft matching layer
- Independent: completely detached from the live production pipeline
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from a_jent.candidate_profiler import CandidateProfile
from a_jent.job_normalizer import JobProfile


class ConstraintStatus(str, Enum):
    """Three-state evaluation status for hard eligibility constraints."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass
class ConstraintResult:
    """Individual constraint evaluation result with clear explainability."""

    constraint: str
    status: ConstraintStatus
    reason: str
    candidate_value: Any = None
    job_value: Any = None
    is_applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize constraint result to standard dictionary."""
        return {
            "constraint": self.constraint,
            "status": self.status.value,
            "reason": self.reason,
            "candidate_value": self.candidate_value,
            "job_value": self.job_value,
            "is_applicable": self.is_applicable,
        }


@dataclass
class ConstraintEvaluation:
    """Overall hard constraint evaluation combining all applicable checks."""

    status: ConstraintStatus
    results: list[ConstraintResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if overall evaluation passed."""
        return self.status == ConstraintStatus.PASS

    @property
    def failed(self) -> bool:
        """True if overall evaluation failed."""
        return self.status == ConstraintStatus.FAIL

    @property
    def unknown(self) -> bool:
        """True if overall evaluation is unresolved due to missing information."""
        return self.status == ConstraintStatus.UNKNOWN

    @property
    def failures(self) -> list[ConstraintResult]:
        """List of individual constraint failures."""
        return [r for r in self.results if r.status == ConstraintStatus.FAIL]

    @property
    def unresolved(self) -> list[ConstraintResult]:
        """List of unresolved applicable constraints."""
        return [r for r in self.results if r.is_applicable and r.status == ConstraintStatus.UNKNOWN]

    def to_dict(self) -> dict[str, Any]:
        """Serialize evaluation to standard dictionary."""
        return {
            "status": self.status.value,
            "results": [r.to_dict() for r in self.results],
            "reasons": list(self.reasons),
        }


# ---------------------------------------------------------------------------
# SENIORITY GROUPS & HIERARCHY
# ---------------------------------------------------------------------------
JUNIOR_SENIORITY_GROUP = {"student", "intern", "entry_level", "junior"}
SENIOR_SENIORITY_GROUP = {"senior", "lead", "principal", "staff"}


def evaluate_seniority(candidate: CandidateProfile, job: JobProfile) -> ConstraintResult:
    """Evaluate explicit seniority incompatibility conservatively."""
    # If job does not specify a seniority requirement, constraint is not applicable
    if not job.seniority:
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason="Job does not specify a seniority requirement.",
            candidate_value=candidate.seniority,
            job_value=None,
            is_applicable=False,
        )

    # Job requires explicit seniority, but candidate seniority is unknown
    if not candidate.seniority:
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.UNKNOWN,
            reason=f"Job requires '{job.seniority}' seniority, but candidate seniority is not specified.",
            candidate_value=None,
            job_value=job.seniority,
            is_applicable=True,
        )

    cand_sen = candidate.seniority.lower().strip()
    job_sen = job.seniority.lower().strip()

    # Hard contradiction check: Junior candidate vs Senior/Lead job
    if job_sen in SENIOR_SENIORITY_GROUP and cand_sen in JUNIOR_SENIORITY_GROUP:
        # Check confidence: Low confidence prevents unjustified hard failure
        cand_conf = candidate.confidence.get("seniority", "HIGH")
        job_conf = job.confidence.get("seniority", "HIGH")
        if cand_conf == "LOW" or job_conf == "LOW":
            return ConstraintResult(
                constraint="seniority",
                status=ConstraintStatus.UNKNOWN,
                reason=(
                    f"Potential seniority contradiction ('{cand_sen}' vs '{job_sen}'), "
                    "but confidence is LOW. Hard rejection requires high-confidence evidence."
                ),
                candidate_value=cand_sen,
                job_value=job_sen,
                is_applicable=True,
            )
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.FAIL,
            reason=f"Candidate is '{cand_sen}' while job explicitly requires '{job_sen}'-level experience.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    # Compatible matching
    if cand_sen == job_sen:
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason=f"Candidate seniority '{cand_sen}' matches required job seniority '{job_sen}'.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    if cand_sen in SENIOR_SENIORITY_GROUP and job_sen in SENIOR_SENIORITY_GROUP:
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason=f"Candidate seniority '{cand_sen}' is compatible with required job seniority '{job_sen}'.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    if cand_sen in SENIOR_SENIORITY_GROUP and job_sen in ("mid_level", "junior", "entry_level"):
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason=f"Candidate seniority '{cand_sen}' exceeds required job seniority '{job_sen}'.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    if cand_sen in ("student", "intern") and job_sen in ("intern", "entry_level"):
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason=f"Candidate seniority '{cand_sen}' is compatible with job seniority '{job_sen}'.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    if cand_sen == "entry_level" and job_sen in ("entry_level", "junior"):
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason=f"Candidate seniority '{cand_sen}' is compatible with job seniority '{job_sen}'.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    if cand_sen == "mid_level" and job_sen in ("mid_level", "junior", "entry_level"):
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.PASS,
            reason=f"Candidate seniority '{cand_sen}' is compatible with job seniority '{job_sen}'.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    if cand_sen == "mid_level" and job_sen in SENIOR_SENIORITY_GROUP:
        return ConstraintResult(
            constraint="seniority",
            status=ConstraintStatus.UNKNOWN,
            reason=f"Candidate is mid_level applying for '{job_sen}' role; insufficient evidence of hard contradiction.",
            candidate_value=cand_sen,
            job_value=job_sen,
            is_applicable=True,
        )

    return ConstraintResult(
        constraint="seniority",
        status=ConstraintStatus.UNKNOWN,
        reason=f"Seniority compatibility between '{cand_sen}' and '{job_sen}' cannot be definitively determined.",
        candidate_value=cand_sen,
        job_value=job_sen,
        is_applicable=True,
    )


# ---------------------------------------------------------------------------
# WORK MODE & LOCATION
# ---------------------------------------------------------------------------
def evaluate_work_mode_location(candidate: CandidateProfile, job: JobProfile) -> ConstraintResult:
    """Evaluate explicit work-mode and location incompatibility conservatively.

    Preserves UNKNOWN != REMOTE.
    """
    # If job specifies neither work mode nor location, constraint is not applicable
    if not job.work_mode and not job.location:
        return ConstraintResult(
            constraint="work_mode_location",
            status=ConstraintStatus.PASS,
            reason="Job does not specify work mode or location requirements.",
            candidate_value=candidate.work_mode,
            job_value=None,
            is_applicable=False,
        )

    cand_mode = candidate.work_mode.lower().strip() if candidate.work_mode else None
    job_mode = job.work_mode.lower().strip() if job.work_mode else None
    job_loc = job.location.lower().strip() if job.location else None

    # Collect candidate locations
    cand_locations: list[str] = []
    if candidate.current_location:
        cand_locations.append(candidate.current_location.lower().strip())
    for loc in candidate.preferred_locations:
        cleaned_loc = loc.lower().strip()
        if cleaned_loc not in cand_locations:
            cand_locations.append(cleaned_loc)

    # 1. Job is explicitly Remote
    if job_mode == "remote":
        return ConstraintResult(
            constraint="work_mode_location",
            status=ConstraintStatus.PASS,
            reason="Job explicitly specifies remote work, compatible with candidate.",
            candidate_value=cand_mode,
            job_value="remote",
            is_applicable=True,
        )

    # 2. Job requires Onsite or Hybrid presence
    if job_mode in ("onsite", "hybrid"):
        # Explicit contradiction: Candidate requires remote, job requires onsite or hybrid
        if cand_mode == "remote":
            cand_conf = candidate.confidence.get("work_mode", "HIGH")
            job_conf = job.confidence.get("location_work_mode", "HIGH")
            if cand_conf == "LOW" or job_conf == "LOW":
                return ConstraintResult(
                    constraint="work_mode_location",
                    status=ConstraintStatus.UNKNOWN,
                    reason=(
                        f"Potential work-mode contradiction (candidate prefers remote, job is {job_mode}), "
                        "but confidence is LOW. Hard rejection requires high-confidence evidence."
                    ),
                    candidate_value=cand_mode,
                    job_value=job_mode,
                    is_applicable=True,
                )
            return ConstraintResult(
                constraint="work_mode_location",
                status=ConstraintStatus.FAIL,
                reason=f"Candidate explicitly requires remote work, but the job explicitly requires {job_mode} presence.",
                candidate_value=cand_mode,
                job_value=job_mode,
                is_applicable=True,
            )

        # Candidate work mode is unknown
        if not cand_mode:
            # Check if location explicitly matches
            if job_loc and job_loc in cand_locations:
                return ConstraintResult(
                    constraint="work_mode_location",
                    status=ConstraintStatus.PASS,
                    reason=f"Job requires {job_mode} in '{job_loc}', which matches candidate location.",
                    candidate_value=f"Location: {cand_locations}",
                    job_value=f"{job_mode} in {job_loc}",
                    is_applicable=True,
                )
            return ConstraintResult(
                constraint="work_mode_location",
                status=ConstraintStatus.UNKNOWN,
                reason=f"Job explicitly requires {job_mode} work in '{job_loc or 'office'}', but candidate work-mode preference is not specified.",
                candidate_value=None,
                job_value=job_mode,
                is_applicable=True,
            )

        # Candidate is open to onsite/hybrid: evaluate location
        if job_loc:
            if cand_locations:
                if job_loc in cand_locations:
                    return ConstraintResult(
                        constraint="work_mode_location",
                        status=ConstraintStatus.PASS,
                        reason=f"Job location '{job_loc}' and work mode '{job_mode}' match candidate preferences.",
                        candidate_value=f"{cand_mode} ({', '.join(cand_locations)})",
                        job_value=f"{job_mode} ({job_loc})",
                        is_applicable=True,
                    )
                # Different location without explicit restriction: conservative UNKNOWN
                return ConstraintResult(
                    constraint="work_mode_location",
                    status=ConstraintStatus.UNKNOWN,
                    reason=f"Job requires {job_mode} in '{job_loc}', while candidate locations are {cand_locations}; relocation willingness is unknown.",
                    candidate_value=cand_locations,
                    job_value=job_loc,
                    is_applicable=True,
                )
            return ConstraintResult(
                constraint="work_mode_location",
                status=ConstraintStatus.PASS,
                reason=f"Job work mode '{job_mode}' matches candidate preference.",
                candidate_value=cand_mode,
                job_value=job_mode,
                is_applicable=True,
            )

        return ConstraintResult(
            constraint="work_mode_location",
            status=ConstraintStatus.PASS,
            reason=f"Both candidate and job specify {job_mode} work.",
            candidate_value=cand_mode,
            job_value=job_mode,
            is_applicable=True,
        )

    # 3. Job work mode is None, but job has explicit location (UNKNOWN != REMOTE)
    if not job_mode and job_loc:
        if not cand_locations:
            if cand_mode == "remote":
                return ConstraintResult(
                    constraint="work_mode_location",
                    status=ConstraintStatus.UNKNOWN,
                    reason=f"Candidate prefers remote, but job location is '{job_loc}' with unspecified work mode.",
                    candidate_value=cand_mode,
                    job_value=job_loc,
                    is_applicable=True,
                )
            return ConstraintResult(
                constraint="work_mode_location",
                status=ConstraintStatus.UNKNOWN,
                reason=f"Job is located in '{job_loc}', but candidate location preference is not specified.",
                candidate_value=None,
                job_value=job_loc,
                is_applicable=True,
            )
        if job_loc in cand_locations:
            return ConstraintResult(
                constraint="work_mode_location",
                status=ConstraintStatus.PASS,
                reason=f"Job location '{job_loc}' matches candidate location preference.",
                candidate_value=cand_locations,
                job_value=job_loc,
                is_applicable=True,
            )
        return ConstraintResult(
            constraint="work_mode_location",
            status=ConstraintStatus.UNKNOWN,
            reason=f"Job is located in '{job_loc}', while candidate location preference is {cand_locations}; relocation willingness is unknown.",
            candidate_value=cand_locations,
            job_value=job_loc,
            is_applicable=True,
        )

    return ConstraintResult(
        constraint="work_mode_location",
        status=ConstraintStatus.UNKNOWN,
        reason="Work mode and location requirements cannot be definitively determined.",
        candidate_value=cand_mode,
        job_value=job_mode or job_loc,
        is_applicable=True,
    )


# ---------------------------------------------------------------------------
# EMPLOYMENT TYPE
# ---------------------------------------------------------------------------
def evaluate_employment_type(candidate: CandidateProfile, job: JobProfile) -> ConstraintResult:
    """Evaluate explicit employment type incompatibility conservatively."""
    # If job does not specify an employment type, constraint is not applicable
    if not job.employment_type:
        return ConstraintResult(
            constraint="employment_type",
            status=ConstraintStatus.PASS,
            reason="Job does not specify an employment type requirement.",
            candidate_value=candidate.employment_preferences,
            job_value=None,
            is_applicable=False,
        )

    job_type = job.employment_type.lower().strip()

    # Job employment type is unstated / unknown: cannot definitively determine compatibility
    if job_type in ("unknown", "none"):
        return ConstraintResult(
            constraint="employment_type",
            status=ConstraintStatus.UNKNOWN,
            reason=f"Job employment type is not specified (recorded as '{job_type}'); compatibility cannot be definitively determined.",
            candidate_value=candidate.employment_preferences,
            job_value=job_type,
            is_applicable=True,
        )

    # Candidate has no employment preferences specified
    if not candidate.employment_preferences:
        return ConstraintResult(
            constraint="employment_type",
            status=ConstraintStatus.UNKNOWN,
            reason=f"Job is '{job_type}', but candidate has not specified employment preferences.",
            candidate_value=[],
            job_value=job_type,
            is_applicable=True,
        )

    cand_prefs = [p.lower().strip() for p in candidate.employment_preferences]
    cand_display = ", ".join(p.replace("_", "-") for p in cand_prefs)
    job_display = job_type.replace("_", "-")

    # Explicit match
    if job_type in cand_prefs:
        return ConstraintResult(
            constraint="employment_type",
            status=ConstraintStatus.PASS,
            reason=f"Candidate employment preferences include '{job_display}', matching the job.",
            candidate_value=cand_prefs,
            job_value=job_type,
            is_applicable=True,
        )

    # Explicit contradiction: Candidate preferences do not include job employment type
    cand_conf = candidate.confidence.get("employment", "HIGH")
    job_conf = job.confidence.get("employment_type", "HIGH")
    if cand_conf == "LOW" or job_conf == "LOW":
        return ConstraintResult(
            constraint="employment_type",
            status=ConstraintStatus.UNKNOWN,
            reason=(
                f"Potential employment type contradiction (candidate seeks {cand_display}, job is '{job_display}'), "
                "but confidence is LOW. Hard rejection requires high-confidence evidence."
            ),
            candidate_value=cand_prefs,
            job_value=job_type,
            is_applicable=True,
        )

    return ConstraintResult(
        constraint="employment_type",
        status=ConstraintStatus.FAIL,
        reason=f"Candidate explicitly seeks {cand_display}, which is incompatible with required job employment type '{job_display}'.",
        candidate_value=cand_prefs,
        job_value=job_type,
        is_applicable=True,
    )



# ---------------------------------------------------------------------------
# GRADUATION YEAR
# ---------------------------------------------------------------------------
def evaluate_graduation_year(candidate: CandidateProfile, job: JobProfile) -> ConstraintResult:
    """Evaluate explicit graduation year incompatibility only when job specifies requirement."""
    # If job does not specify a graduation year requirement, constraint is not applicable
    if job.graduation_year is None:
        return ConstraintResult(
            constraint="graduation_year",
            status=ConstraintStatus.PASS,
            reason="Job does not specify a graduation year requirement.",
            candidate_value=candidate.graduation_year,
            job_value=None,
            is_applicable=False,
        )

    # Job requires explicit graduation year, but candidate graduation year is not specified
    if candidate.graduation_year is None:
        return ConstraintResult(
            constraint="graduation_year",
            status=ConstraintStatus.UNKNOWN,
            reason=f"Job requires graduation year {job.graduation_year}, but candidate graduation year is not specified.",
            candidate_value=None,
            job_value=job.graduation_year,
            is_applicable=True,
        )

    # Compatible match
    if candidate.graduation_year == job.graduation_year:
        return ConstraintResult(
            constraint="graduation_year",
            status=ConstraintStatus.PASS,
            reason=f"Candidate graduation year {candidate.graduation_year} matches required job graduation year {job.graduation_year}.",
            candidate_value=candidate.graduation_year,
            job_value=job.graduation_year,
            is_applicable=True,
        )

    # Incompatible mismatch
    cand_conf = candidate.confidence.get("graduation_year", "HIGH")
    job_conf = job.confidence.get("graduation_year", "HIGH")
    if cand_conf == "LOW" or job_conf == "LOW":
        return ConstraintResult(
            constraint="graduation_year",
            status=ConstraintStatus.UNKNOWN,
            reason=(
                f"Potential graduation year mismatch (candidate: {candidate.graduation_year}, job: {job.graduation_year}), "
                "but confidence is LOW. Hard rejection requires high-confidence evidence."
            ),
            candidate_value=candidate.graduation_year,
            job_value=job.graduation_year,
            is_applicable=True,
        )

    return ConstraintResult(
        constraint="graduation_year",
        status=ConstraintStatus.FAIL,
        reason=f"Candidate graduation year ({candidate.graduation_year}) does not match required job graduation year ({job.graduation_year}).",
        candidate_value=candidate.graduation_year,
        job_value=job.graduation_year,
        is_applicable=True,
    )


# ---------------------------------------------------------------------------
# OVERALL CONSTRAINT EVALUATION
# ---------------------------------------------------------------------------
def evaluate_constraints(
    candidate: Optional[CandidateProfile],
    job: Optional[JobProfile],
) -> ConstraintEvaluation:
    """Evaluate all hard constraints between a candidate profile and a job profile.

    Rules:
    - If ANY applicable hard constraint = FAIL -> overall = FAIL
    - Else if ALL applicable constraints = PASS (or none applicable) -> overall = PASS
    - Else (no FAIL, but at least one unresolved applicable constraint) -> overall = UNKNOWN

    Args:
        candidate: CandidateProfile extracted from resume.
        job: JobProfile extracted from raw job listing.

    Returns:
        ConstraintEvaluation containing overall status, detailed results, and explanations.
    """
    if candidate is None or job is None:
        return ConstraintEvaluation(
            status=ConstraintStatus.UNKNOWN,
            results=[],
            reasons=["Candidate profile or job profile is missing."],
        )

    results = [
        evaluate_seniority(candidate, job),
        evaluate_work_mode_location(candidate, job),
        evaluate_employment_type(candidate, job),
        evaluate_graduation_year(candidate, job),
    ]

    applicable_results = [r for r in results if r.is_applicable]

    # 1. Any FAIL causes overall FAIL
    failures = [r for r in applicable_results if r.status == ConstraintStatus.FAIL]
    if failures:
        return ConstraintEvaluation(
            status=ConstraintStatus.FAIL,
            results=results,
            reasons=[r.reason for r in failures],
        )

    # 2. All applicable constraints PASS causes overall PASS
    unresolved = [r for r in applicable_results if r.status == ConstraintStatus.UNKNOWN]
    if not unresolved:
        pass_reasons = [r.reason for r in applicable_results if r.status == ConstraintStatus.PASS]
        if not pass_reasons:
            pass_reasons = ["No hard constraints specified by job."]
        return ConstraintEvaluation(
            status=ConstraintStatus.PASS,
            results=results,
            reasons=pass_reasons,
        )

    # 3. No FAIL, but unresolved applicable constraint produces UNKNOWN
    return ConstraintEvaluation(
        status=ConstraintStatus.UNKNOWN,
        results=results,
        reasons=[r.reason for r in unresolved],
    )
