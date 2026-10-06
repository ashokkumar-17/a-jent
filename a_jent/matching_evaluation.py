"""
Matching Evaluation & Shadow Matching Module
--------------------------------------------
Provides deterministic evaluation infrastructure to compare:
1. Legacy TF-IDF matcher (a_jent.job_matcher)
2. Deterministic explainable matcher (a_jent.explainable_matcher)

Features:
- Versioned evaluation schema ("1.0")
- EvaluationRecord data model preserving comparison metrics without raw resume text
- Human relevance labels: HIGH_RELEVANCE, BORDERLINE, IRRELEVANT
- Precision@K and Recall@K calculation for labeled pairs
- Top-K overlap, Jaccard similarity, and rank disagreement analysis
- Offline JSONL evaluation dataset loader, validator, and serializer
- Deterministic, non-mutating, zero-dependency (Python standard library only)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Optional, Union

from a_jent.candidate_profiler import CandidateProfile
from a_jent.job_normalizer import JobProfile
from a_jent.job_matcher import rank_by_similarity
from a_jent.explainable_matcher import match_candidate_to_job, MatchResult

# Current evaluation schema version
SCHEMA_VERSION: str = "1.0"


class HumanLabel(str, Enum):
    """Supported human relevance labels for evaluation datasets."""

    HIGH_RELEVANCE = "HIGH_RELEVANCE"
    BORDERLINE = "BORDERLINE"
    IRRELEVANT = "IRRELEVANT"


VALID_HUMAN_LABELS = {
    HumanLabel.HIGH_RELEVANCE.value,
    HumanLabel.BORDERLINE.value,
    HumanLabel.IRRELEVANT.value,
}


class SemanticGapCategory(str, Enum):
    """Classification categories for analyzing semantic gaps and matcher failure modes."""

    KEYWORD_OVERLAP_SUFFICIENT = "KEYWORD_OVERLAP_SUFFICIENT"
    TAXONOMY_NORMALIZATION = "TAXONOMY_NORMALIZATION"
    ROLE_AFFINITY = "ROLE_AFFINITY"
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    SEMANTIC_LANGUAGE_GAP = "SEMANTIC_LANGUAGE_GAP"
    OTHER = "OTHER"


VALID_SEMANTIC_GAP_CATEGORIES = {c.value for c in SemanticGapCategory}


class BenchmarkIntegrityError(ValueError):
    """Raised when benchmark dataset integrity checks fail (e.g. duplicate pairs, conflicting labels)."""

    pass


# ---------------------------------------------------------------------------
# EVALUATION RECORD DATA MODEL
# ---------------------------------------------------------------------------
@dataclass
class EvaluationRecord:
    """Structured comparison record for a single candidate/job pair.

    Never stores raw resume text or sensitive candidate PII.
    """

    candidate_id: str
    job_id: str
    job_title: str
    schema_version: str = SCHEMA_VERSION
    company: str = ""
    source: str = ""
    legacy_score: float = 0.0
    explainable_score: float = 0.0
    legacy_rank: int = 0
    explainable_rank: int = 0
    rank_delta: int = 0
    in_legacy_top_k: bool = False
    in_explainable_top_k: bool = False
    hard_constraint_status: str = "UNKNOWN"
    explainable_tier: str = "WEAK"
    matched_required_skills: list[str] = field(default_factory=list)
    missing_required_skills: list[str] = field(default_factory=list)
    human_label: Optional[str] = None
    notes: Optional[str] = None
    timestamp: Optional[str] = None
    reviewer_id: Optional[str] = None
    semantic_gap_category: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize record to dictionary."""
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "company": self.company,
            "source": self.source,
            "legacy_score": self.legacy_score,
            "explainable_score": self.explainable_score,
            "legacy_rank": self.legacy_rank,
            "explainable_rank": self.explainable_rank,
            "rank_delta": self.rank_delta,
            "in_legacy_top_k": self.in_legacy_top_k,
            "in_explainable_top_k": self.in_explainable_top_k,
            "hard_constraint_status": self.hard_constraint_status,
            "explainable_tier": self.explainable_tier,
            "matched_required_skills": list(self.matched_required_skills),
            "missing_required_skills": list(self.missing_required_skills),
            "human_label": self.human_label,
            "notes": self.notes,
            "timestamp": self.timestamp,
            "reviewer_id": self.reviewer_id,
            "semantic_gap_category": self.semantic_gap_category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationRecord":
        """Deserialize dictionary into an EvaluationRecord, validating schema."""
        validate_evaluation_record(data)
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            candidate_id=str(data["candidate_id"]),
            job_id=str(data["job_id"]),
            job_title=str(data.get("job_title", "")),
            company=str(data.get("company", "")),
            source=str(data.get("source", "")),
            legacy_score=float(data.get("legacy_score", 0.0)),
            explainable_score=float(data.get("explainable_score", 0.0)),
            legacy_rank=int(data.get("legacy_rank", 0)),
            explainable_rank=int(data.get("explainable_rank", 0)),
            rank_delta=int(data.get("rank_delta", 0)),
            in_legacy_top_k=bool(data.get("in_legacy_top_k", False)),
            in_explainable_top_k=bool(data.get("in_explainable_top_k", False)),
            hard_constraint_status=str(data.get("hard_constraint_status", "UNKNOWN")),
            explainable_tier=str(data.get("explainable_tier", "WEAK")),
            matched_required_skills=list(data.get("matched_required_skills", [])),
            missing_required_skills=list(data.get("missing_required_skills", [])),
            human_label=data.get("human_label"),
            notes=data.get("notes"),
            timestamp=data.get("timestamp"),
            reviewer_id=data.get("reviewer_id"),
            semantic_gap_category=data.get("semantic_gap_category"),
        )


# ---------------------------------------------------------------------------
# METRICS & COMPARISON SUMMARY DATA MODELS
# ---------------------------------------------------------------------------
@dataclass
class MetricResult:
    """Ranking metric results for a specific matcher."""

    status: str  # 'calculated' or 'insufficient_labeled_data'
    k: int
    actual_k: int
    precision_at_k: Optional[float] = None
    recall_at_k: Optional[float] = None
    total_high_relevance: int = 0
    high_relevance_in_top_k: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize metric result to dictionary."""
        return {
            "status": self.status,
            "k": self.k,
            "actual_k": self.actual_k,
            "precision_at_k": self.precision_at_k,
            "recall_at_k": self.recall_at_k,
            "total_high_relevance": self.total_high_relevance,
            "high_relevance_in_top_k": self.high_relevance_in_top_k,
        }


@dataclass
class ComparisonSummary:
    """Comprehensive comparison summary between legacy and explainable matchers."""

    candidate_id: str
    total_jobs: int
    k: int
    actual_k: int
    records: list[EvaluationRecord]
    legacy_metrics: MetricResult
    explainable_metrics: MetricResult
    top_k_overlap_count: int
    top_k_jaccard_similarity: float
    legacy_only_top_k: list[str]
    explainable_only_top_k: list[str]
    hard_constraint_rejections_count: int
    hard_constraint_rejections_in_legacy_top_k: list[str]
    large_rank_disagreements: list[dict[str, Any]]
    schema_version: str = SCHEMA_VERSION
    timestamp: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize comparison summary to dictionary."""
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "candidate_id": self.candidate_id,
            "total_jobs": self.total_jobs,
            "k": self.k,
            "actual_k": self.actual_k,
            "top_k_overlap_count": self.top_k_overlap_count,
            "top_k_jaccard_similarity": self.top_k_jaccard_similarity,
            "legacy_only_top_k": list(self.legacy_only_top_k),
            "explainable_only_top_k": list(self.explainable_only_top_k),
            "hard_constraint_rejections_count": self.hard_constraint_rejections_count,
            "hard_constraint_rejections_in_legacy_top_k": list(
                self.hard_constraint_rejections_in_legacy_top_k
            ),
            "large_rank_disagreements": list(self.large_rank_disagreements),
            "legacy_metrics": self.legacy_metrics.to_dict(),
            "explainable_metrics": self.explainable_metrics.to_dict(),
            "records": [r.to_dict() for r in self.records],
        }


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------
def validate_evaluation_record(record: dict[str, Any]) -> None:
    """Validate that an evaluation dictionary adheres to the versioned schema.

    Raises:
        ValueError: If required fields are missing, schema_version is unsupported,
                    or human_label is invalid.
    """
    if not isinstance(record, dict):
        raise ValueError("Evaluation record must be a dictionary.")

    # Check required identifiers
    if "candidate_id" not in record or not str(record["candidate_id"]).strip():
        raise ValueError("Evaluation record missing required field 'candidate_id'.")
    if "job_id" not in record or not str(record["job_id"]).strip():
        raise ValueError("Evaluation record missing required field 'job_id'.")

    # Check schema version if specified
    if "schema_version" in record:
        ver = str(record["schema_version"]).strip()
        if ver != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version '{ver}'. Expected '{SCHEMA_VERSION}'."
            )

    # Validate human label if provided
    label = record.get("human_label")
    if label is not None and label not in VALID_HUMAN_LABELS:
        raise ValueError(
            f"Invalid human_label '{label}'. Must be one of {sorted(VALID_HUMAN_LABELS)} or null."
        )

    # Validate semantic gap category if provided
    gap_cat = record.get("semantic_gap_category")
    if gap_cat is not None and gap_cat not in VALID_SEMANTIC_GAP_CATEGORIES:
        raise ValueError(
            f"Invalid semantic_gap_category '{gap_cat}'. Must be one of {sorted(VALID_SEMANTIC_GAP_CATEGORIES)} or null."
        )


# ---------------------------------------------------------------------------
# METRICS CALCULATION
# ---------------------------------------------------------------------------
def calculate_ranking_metrics(
    records: list[EvaluationRecord],
    rank_attr: str,
    k: int,
) -> MetricResult:
    """Calculate Precision@K and Recall@K for labeled HIGH_RELEVANCE records.

    Rules:
    - HIGH_RELEVANCE is counted as relevant.
    - BORDERLINE is NOT counted as relevant.
    - IRRELEVANT is NOT counted as relevant.
    - Unlabeled records are excluded from labeled metrics.
    - If total HIGH_RELEVANCE == 0 or no labeled records exist, returns
      status='insufficient_labeled_data' rather than misleading zeros.

    Args:
        records: List of evaluated EvaluationRecord instances.
        rank_attr: Attribute name indicating rank ('legacy_rank' or 'explainable_rank').
        k: Top-K cutoff.

    Returns:
        MetricResult dataclass.
    """
    if not records:
        return MetricResult(
            status="insufficient_labeled_data",
            k=k,
            actual_k=0,
            precision_at_k=None,
            recall_at_k=None,
            total_high_relevance=0,
            high_relevance_in_top_k=0,
        )

    actual_k = min(k, len(records))

    # Total HIGH_RELEVANCE in complete evaluation dataset
    total_high_relevance = sum(
        1 for r in records if r.human_label == HumanLabel.HIGH_RELEVANCE.value
    )

    if total_high_relevance == 0:
        return MetricResult(
            status="insufficient_labeled_data",
            k=k,
            actual_k=actual_k,
            precision_at_k=None,
            recall_at_k=None,
            total_high_relevance=0,
            high_relevance_in_top_k=0,
        )

    # Count HIGH_RELEVANCE within top K
    top_k_records = [r for r in records if getattr(r, rank_attr) <= actual_k]
    high_rel_in_top_k = sum(
        1 for r in top_k_records if r.human_label == HumanLabel.HIGH_RELEVANCE.value
    )

    precision_at_k = round(high_rel_in_top_k / actual_k, 4) if actual_k > 0 else 0.0
    recall_at_k = (
        round(high_rel_in_top_k / total_high_relevance, 4)
        if total_high_relevance > 0
        else 0.0
    )

    return MetricResult(
        status="calculated",
        k=k,
        actual_k=actual_k,
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        total_high_relevance=total_high_relevance,
        high_relevance_in_top_k=high_rel_in_top_k,
    )


# ---------------------------------------------------------------------------
# MATCHER COMPARISON CORE
# ---------------------------------------------------------------------------
def _synthesize_resume_text(candidate: CandidateProfile) -> str:
    """Synthesize clean text representation from candidate profile if raw text is unavailable."""
    parts = []
    if candidate.seniority:
        parts.append(candidate.seniority)
    if candidate.normalized_skills:
        parts.append(" ".join(candidate.normalized_skills))
    if candidate.raw_skills:
        parts.append(" ".join(candidate.raw_skills))
    if candidate.evidence:
        for val in candidate.evidence.values():
            if val:
                parts.append(str(val))
    return " ".join(parts).strip()


def compare_matchers(
    candidate: CandidateProfile,
    jobs: list[JobProfile],
    raw_resume_text: Optional[str] = None,
    candidate_id: str = "candidate_001",
    k: int = 10,
    human_labels: Optional[dict[str, str]] = None,
    notes: Optional[dict[str, str]] = None,
    large_rank_delta_threshold: int = 5,
    timestamp: Optional[str] = None,
    reviewer_ids: Optional[dict[str, str]] = None,
    semantic_gap_categories: Optional[dict[str, str]] = None,
) -> ComparisonSummary:
    """Compare legacy TF-IDF matcher and explainable matcher on the same candidate/job pairs.

    Guarantees:
    - Zero mutation of CandidateProfile and JobProfile instances.
    - Preserves existing legacy TF-IDF ranking behavior.
    - Produces independent rankings, disagreement analysis, and optional labeled metrics.

    Args:
        candidate: CandidateProfile instance.
        jobs: List of JobProfile instances to evaluate.
        raw_resume_text: Optional original resume text for legacy matcher.
        candidate_id: Stable identifier or label for candidate.
        k: Cutoff for Top-K rankings and metrics (default 10).
        human_labels: Optional mapping of job_id -> HumanLabel string.
        notes: Optional mapping of job_id -> note string.
        large_rank_delta_threshold: Threshold to flag large rank disagreements.

    Returns:
        ComparisonSummary containing row-level EvaluationRecords and aggregate metrics.
    """
    if not jobs:
        empty_metrics = MetricResult(
            status="insufficient_labeled_data",
            k=k,
            actual_k=0,
            precision_at_k=None,
            recall_at_k=None,
            total_high_relevance=0,
            high_relevance_in_top_k=0,
        )
        return ComparisonSummary(
            candidate_id=candidate_id,
            total_jobs=0,
            k=k,
            actual_k=0,
            records=[],
            legacy_metrics=empty_metrics,
            explainable_metrics=empty_metrics,
            top_k_overlap_count=0,
            top_k_jaccard_similarity=1.0,
            legacy_only_top_k=[],
            explainable_only_top_k=[],
            hard_constraint_rejections_count=0,
            hard_constraint_rejections_in_legacy_top_k=[],
            large_rank_disagreements=[],
        )

    actual_k = min(k, len(jobs))
    labels_map = human_labels or {}
    notes_map = notes or {}

    # Validate human labels if provided
    for jid, lbl in labels_map.items():
        if lbl not in VALID_HUMAN_LABELS:
            raise ValueError(
                f"Invalid human label '{lbl}' for job '{jid}'. Must be one of {sorted(VALID_HUMAN_LABELS)}."
            )

    # 1. Evaluate Explainable Matcher on all jobs
    explainable_results: dict[str, MatchResult] = {}
    for job in jobs:
        jid = job.job_id or str(id(job))
        res = match_candidate_to_job(candidate, job)
        explainable_results[jid] = res

    # 2. Evaluate Legacy TF-IDF Matcher on all jobs
    # Prepare non-mutating raw job dictionaries
    raw_job_copies: list[dict[str, Any]] = []
    job_id_lookup: dict[int, str] = {}
    for i, job in enumerate(jobs):
        jid = job.job_id or str(id(job))
        base_dict = (
            dict(job.raw_job)
            if job.raw_job
            else {
                "id": jid,
                "title": job.title,
                "description": job.description,
                "company": job.company,
                "source": job.source,
                "location": job.raw_location or job.location or "",
            }
        )
        copy_dict = dict(base_dict)
        copy_dict["_orig_jid"] = jid
        raw_job_copies.append(copy_dict)
        job_id_lookup[i] = jid

    resume_text = raw_resume_text if raw_resume_text else _synthesize_resume_text(candidate)
    legacy_ranked_jobs = rank_by_similarity(
        resume_text=resume_text,
        jobs=raw_job_copies,
        similarity_threshold=0.0,  # Rank all jobs across dataset for comparison
    )

    # Map legacy scores and ranks
    legacy_scores: dict[str, float] = {}
    legacy_ranks: dict[str, int] = {}
    for rank_idx, rj in enumerate(legacy_ranked_jobs, start=1):
        jid = rj.get("_orig_jid") or rj.get("id") or rj.get("job_id") or ""
        legacy_scores[jid] = float(rj.get("score", 0.0))
        legacy_ranks[jid] = rank_idx

    # If any job was omitted by legacy ranker, assign minimum score and tail rank
    for job in jobs:
        jid = job.job_id or str(id(job))
        if jid not in legacy_scores:
            legacy_scores[jid] = 0.0
            legacy_ranks[jid] = len(jobs)

    # 3. Sort Explainable Ranks (1-indexed descending by score, deterministic tie-breaking)
    sorted_explainable = sorted(
        jobs,
        key=lambda j: (
            -explainable_results[j.job_id or str(id(j))].score,
            j.job_id or str(id(j)),
        ),
    )
    explainable_ranks: dict[str, int] = {
        (j.job_id or str(id(j))): r_idx for r_idx, j in enumerate(sorted_explainable, start=1)
    }

    # 4. Construct Evaluation Records
    records: list[EvaluationRecord] = []
    hard_constraint_rejections = 0
    large_disagreements: list[dict[str, Any]] = []

    for job in jobs:
        jid = job.job_id or str(id(job))
        exp_res = explainable_results[jid]
        leg_rank = legacy_ranks.get(jid, len(jobs))
        exp_rank = explainable_ranks.get(jid, len(jobs))
        rank_delta = leg_rank - exp_rank

        in_leg_k = leg_rank <= actual_k
        in_exp_k = exp_rank <= actual_k

        if exp_res.hard_constraint_status == "FAIL":
            hard_constraint_rejections += 1

        rec = EvaluationRecord(
            schema_version=SCHEMA_VERSION,
            candidate_id=candidate_id,
            job_id=jid,
            job_title=job.title,
            company=job.company,
            source=job.source,
            legacy_score=legacy_scores.get(jid, 0.0),
            explainable_score=exp_res.score,
            legacy_rank=leg_rank,
            explainable_rank=exp_rank,
            rank_delta=rank_delta,
            in_legacy_top_k=in_leg_k,
            in_explainable_top_k=in_exp_k,
            hard_constraint_status=exp_res.hard_constraint_status,
            explainable_tier=exp_res.tier,
            matched_required_skills=list(exp_res.matched_required_skills),
            missing_required_skills=list(exp_res.missing_required_skills),
            human_label=labels_map.get(jid),
            notes=notes_map.get(jid),
            timestamp=timestamp,
            reviewer_id=(reviewer_ids or {}).get(jid),
            semantic_gap_category=(semantic_gap_categories or {}).get(jid),
        )
        records.append(rec)

        if abs(rank_delta) >= large_rank_delta_threshold:
            large_disagreements.append(
                {
                    "job_id": jid,
                    "job_title": job.title,
                    "legacy_rank": leg_rank,
                    "explainable_rank": exp_rank,
                    "rank_delta": rank_delta,
                    "legacy_score": rec.legacy_score,
                    "explainable_score": rec.explainable_score,
                    "hard_constraint_status": rec.hard_constraint_status,
                }
            )

    # 5. Top-K Overlap Analysis
    top_k_legacy_ids = {r.job_id for r in records if r.in_legacy_top_k}
    top_k_explainable_ids = {r.job_id for r in records if r.in_explainable_top_k}

    top_k_overlap = top_k_legacy_ids & top_k_explainable_ids
    top_k_union = top_k_legacy_ids | top_k_explainable_ids
    jaccard = round(len(top_k_overlap) / len(top_k_union), 4) if top_k_union else 1.0

    legacy_only_top_k = sorted(top_k_legacy_ids - top_k_explainable_ids)
    explainable_only_top_k = sorted(top_k_explainable_ids - top_k_legacy_ids)

    # Check for hard constraint rejections that appeared in legacy top-K
    rejected_in_legacy_top_k = [
        r.job_id
        for r in records
        if r.in_legacy_top_k and r.hard_constraint_status == "FAIL"
    ]

    # 6. Calculate Metrics (Precision@K & Recall@K)
    legacy_metrics = calculate_ranking_metrics(records, rank_attr="legacy_rank", k=k)
    explainable_metrics = calculate_ranking_metrics(
        records, rank_attr="explainable_rank", k=k
    )

    return ComparisonSummary(
        schema_version=SCHEMA_VERSION,
        candidate_id=candidate_id,
        total_jobs=len(jobs),
        k=k,
        actual_k=actual_k,
        records=records,
        legacy_metrics=legacy_metrics,
        explainable_metrics=explainable_metrics,
        top_k_overlap_count=len(top_k_overlap),
        top_k_jaccard_similarity=jaccard,
        legacy_only_top_k=legacy_only_top_k,
        explainable_only_top_k=explainable_only_top_k,
        hard_constraint_rejections_count=hard_constraint_rejections,
        hard_constraint_rejections_in_legacy_top_k=rejected_in_legacy_top_k,
        large_rank_disagreements=large_disagreements,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# SERIALIZATION & FILE UTILITIES
# ---------------------------------------------------------------------------
def save_evaluation_records(
    records: Union[list[EvaluationRecord], list[dict[str, Any]]],
    filepath: Union[str, Path],
) -> None:
    """Save evaluation records to a JSONL file."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            data = r.to_dict() if isinstance(r, EvaluationRecord) else r
            validate_evaluation_record(data)
            f.write(json.dumps(data) + "\n")


def load_evaluation_records(
    filepath: Union[str, Path],
    validate: bool = True,
) -> list[EvaluationRecord]:
    """Load and validate evaluation records from a JSONL file."""
    path = Path(filepath)
    if not path.exists():
        return []

    records: list[EvaluationRecord] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if validate:
                validate_evaluation_record(data)
            records.append(EvaluationRecord.from_dict(data))
    return records


# ---------------------------------------------------------------------------
# BENCHMARK INTEGRITY VALIDATION & LOADER
# ---------------------------------------------------------------------------
def validate_benchmark_integrity(
    records: Union[list[EvaluationRecord], list[dict[str, Any]], str, Path],
) -> dict[str, Any]:
    """Validate integrity across an entire benchmark dataset.

    Checks:
    - Malformed JSONL lines (if path provided)
    - Valid schema version on each record
    - Non-empty candidate_id and job_id
    - Valid human_label (HIGH_RELEVANCE, BORDERLINE, IRRELEVANT, or None)
    - Valid semantic_gap_category if provided
    - Duplicate (candidate_id, job_id) pairs
    - Conflicting human_labels for duplicate (candidate_id, job_id) pairs

    Raises:
        BenchmarkIntegrityError: If duplicate pairs, conflicting labels, or invalid records found.

    Returns:
        Summary statistics dictionary of the validated benchmark dataset.
    """
    raw_list: list[dict[str, Any]] = []

    if isinstance(records, (str, Path)):
        path = Path(records)
        if not path.exists():
            raise FileNotFoundError(f"Benchmark file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as e:
                    raise BenchmarkIntegrityError(
                        f"Malformed JSONL at line {line_no}: {e}"
                    ) from e
                raw_list.append(data)
    elif isinstance(records, list):
        for item in records:
            if isinstance(item, EvaluationRecord):
                raw_list.append(item.to_dict())
            elif isinstance(item, dict):
                raw_list.append(dict(item))
            else:
                raise BenchmarkIntegrityError(
                    f"Unsupported record item type: {type(item)}. Expected EvaluationRecord or dict."
                )
    else:
        raise BenchmarkIntegrityError(
            f"Unsupported records input type: {type(records)}. Expected list, str, or Path."
        )

    seen_pairs: dict[tuple[str, str], dict[str, Any]] = {}
    unique_candidates: set[str] = set()
    unique_jobs: set[str] = set()
    labeled_count = 0
    high_relevance_count = 0
    borderline_count = 0
    irrelevant_count = 0
    unlabeled_count = 0
    gap_dist: dict[str, int] = {}

    for idx, rec in enumerate(raw_list, start=1):
        if not isinstance(rec, dict):
            raise BenchmarkIntegrityError(f"Record {idx} is not a valid dictionary object.")
        try:
            validate_evaluation_record(rec)
        except ValueError as e:
            raise BenchmarkIntegrityError(f"Record {idx} validation failed: {e}") from e

        cand_id = str(rec["candidate_id"]).strip()
        job_id = str(rec["job_id"]).strip()
        pair_key = (cand_id, job_id)
        label = rec.get("human_label")

        if pair_key in seen_pairs:
            prev_label = seen_pairs[pair_key].get("human_label")
            if prev_label != label:
                raise BenchmarkIntegrityError(
                    f"Conflicting labels for duplicate pair ({cand_id}, {job_id}): '{prev_label}' vs '{label}'."
                )
            raise BenchmarkIntegrityError(
                f"Duplicate candidate/job pair found: ({cand_id}, {job_id})."
            )

        seen_pairs[pair_key] = rec
        unique_candidates.add(cand_id)
        unique_jobs.add(job_id)

        if label is None:
            unlabeled_count += 1
        elif label == HumanLabel.HIGH_RELEVANCE.value:
            labeled_count += 1
            high_relevance_count += 1
        elif label == HumanLabel.BORDERLINE.value:
            labeled_count += 1
            borderline_count += 1
        elif label == HumanLabel.IRRELEVANT.value:
            labeled_count += 1
            irrelevant_count += 1

        gap_cat = rec.get("semantic_gap_category")
        if gap_cat:
            gap_dist[gap_cat] = gap_dist.get(gap_cat, 0) + 1

    return {
        "total_records": len(raw_list),
        "unique_pairs": len(seen_pairs),
        "unique_candidates": len(unique_candidates),
        "unique_jobs": len(unique_jobs),
        "labeled_count": labeled_count,
        "high_relevance_count": high_relevance_count,
        "borderline_count": borderline_count,
        "irrelevant_count": irrelevant_count,
        "unlabeled_count": unlabeled_count,
        "semantic_gap_distribution": gap_dist,
    }


def load_benchmark_dataset(
    filepath: Union[str, Path],
) -> tuple[list[EvaluationRecord], dict[str, Any]]:
    """Load, validate, and integrity-check a benchmark dataset from a JSONL file."""
    stats = validate_benchmark_integrity(filepath)
    records = load_evaluation_records(filepath, validate=True)
    return records, stats


# ---------------------------------------------------------------------------
# BENCHMARK RUNNER & REPORT DATA MODEL
# ---------------------------------------------------------------------------
@dataclass
class BenchmarkReport:
    """Comprehensive benchmark execution report comparing Legacy TF-IDF and Explainable Matcher."""

    schema_version: str = SCHEMA_VERSION
    timestamp: Optional[str] = None
    total_candidates: int = 0
    total_jobs: int = 0
    total_pairs: int = 0
    labeled_pairs_count: int = 0
    high_relevance_count: int = 0
    borderline_count: int = 0
    irrelevant_count: int = 0
    unlabeled_count: int = 0

    # Aggregate ranking metrics at K=5
    legacy_metrics_at_5: MetricResult = field(
        default_factory=lambda: MetricResult(status="insufficient_labeled_data", k=5, actual_k=0)
    )
    explainable_metrics_at_5: MetricResult = field(
        default_factory=lambda: MetricResult(status="insufficient_labeled_data", k=5, actual_k=0)
    )
    top_k_overlap_at_5: int = 0
    top_k_jaccard_at_5: float = 1.0

    # Aggregate ranking metrics at K=10
    legacy_metrics_at_10: MetricResult = field(
        default_factory=lambda: MetricResult(status="insufficient_labeled_data", k=10, actual_k=0)
    )
    explainable_metrics_at_10: MetricResult = field(
        default_factory=lambda: MetricResult(status="insufficient_labeled_data", k=10, actual_k=0)
    )
    top_k_overlap_at_10: int = 0
    top_k_jaccard_at_10: float = 1.0

    # Disagreement & Failure cases (at default K=10)
    legacy_only_top_10: list[dict[str, Any]] = field(default_factory=list)
    explainable_only_top_10: list[dict[str, Any]] = field(default_factory=list)
    high_relevance_missed_legacy: list[dict[str, Any]] = field(default_factory=list)
    high_relevance_missed_explainable: list[dict[str, Any]] = field(default_factory=list)
    irrelevant_in_top_k_legacy: list[dict[str, Any]] = field(default_factory=list)
    irrelevant_in_top_k_explainable: list[dict[str, Any]] = field(default_factory=list)
    borderline_disagreements: list[dict[str, Any]] = field(default_factory=list)
    hard_constraint_fails_in_legacy_top_k: list[dict[str, Any]] = field(default_factory=list)
    semantic_language_gap_cases: list[dict[str, Any]] = field(default_factory=list)
    large_rank_disagreements: list[dict[str, Any]] = field(default_factory=list)

    # Candidate summaries and row-level records
    candidate_summaries: list[dict[str, Any]] = field(default_factory=list)
    records: list[EvaluationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize benchmark report to dictionary."""
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "total_candidates": self.total_candidates,
            "total_jobs": self.total_jobs,
            "total_pairs": self.total_pairs,
            "labeled_pairs_count": self.labeled_pairs_count,
            "high_relevance_count": self.high_relevance_count,
            "borderline_count": self.borderline_count,
            "irrelevant_count": self.irrelevant_count,
            "unlabeled_count": self.unlabeled_count,
            "legacy_metrics_at_5": self.legacy_metrics_at_5.to_dict(),
            "legacy_metrics_at_10": self.legacy_metrics_at_10.to_dict(),
            "explainable_metrics_at_5": self.explainable_metrics_at_5.to_dict(),
            "explainable_metrics_at_10": self.explainable_metrics_at_10.to_dict(),
            "top_k_overlap_at_5": self.top_k_overlap_at_5,
            "top_k_jaccard_at_5": self.top_k_jaccard_at_5,
            "top_k_overlap_at_10": self.top_k_overlap_at_10,
            "top_k_jaccard_at_10": self.top_k_jaccard_at_10,
            "legacy_only_top_10": list(self.legacy_only_top_10),
            "explainable_only_top_10": list(self.explainable_only_top_10),
            "high_relevance_missed_legacy": list(self.high_relevance_missed_legacy),
            "high_relevance_missed_explainable": list(self.high_relevance_missed_explainable),
            "irrelevant_in_top_k_legacy": list(self.irrelevant_in_top_k_legacy),
            "irrelevant_in_top_k_explainable": list(self.irrelevant_in_top_k_explainable),
            "borderline_disagreements": list(self.borderline_disagreements),
            "hard_constraint_fails_in_legacy_top_k": list(
                self.hard_constraint_fails_in_legacy_top_k
            ),
            "semantic_language_gap_cases": list(self.semantic_language_gap_cases),
            "large_rank_disagreements": list(self.large_rank_disagreements),
            "candidate_summaries": list(self.candidate_summaries),
            "records": [r.to_dict() for r in self.records],
        }

    def format_markdown_report(self) -> str:
        """Format an objective, descriptive markdown report of benchmark results."""
        lines = [
            "# A-Jent Matching Benchmark Report",
            f"**Schema Version:** {self.schema_version} | **Timestamp:** {self.timestamp or 'N/A'}",
            f"**Evaluated Candidates:** {self.total_candidates} | **Total Evaluated Jobs:** {self.total_jobs} | **Total Pairs:** {self.total_pairs}",
            f"**Label Distribution:** HIGH_RELEVANCE: {self.high_relevance_count}, BORDERLINE: {self.borderline_count}, IRRELEVANT: {self.irrelevant_count}, Unlabeled: {self.unlabeled_count}",
            "",
            "## 1. System Ranking Metrics (Independent Measurement)",
            "| Metric | Legacy TF-IDF | Explainable Matcher | Agreement / Overlap |",
            "| :--- | :--- | :--- | :--- |",
            f"| Precision@5 | {self.legacy_metrics_at_5.precision_at_k} | {self.explainable_metrics_at_5.precision_at_k} | Top-5 Jaccard: {self.top_k_jaccard_at_5} (Overlap: {self.top_k_overlap_at_5}) |",
            f"| Precision@10 | {self.legacy_metrics_at_10.precision_at_k} | {self.explainable_metrics_at_10.precision_at_k} | Top-10 Jaccard: {self.top_k_jaccard_at_10} (Overlap: {self.top_k_overlap_at_10}) |",
            f"| Recall@5 | {self.legacy_metrics_at_5.recall_at_k} | {self.explainable_metrics_at_5.recall_at_k} | - |",
            f"| Recall@10 | {self.legacy_metrics_at_10.recall_at_k} | {self.explainable_metrics_at_10.recall_at_k} | - |",
            "",
            "## 2. Disagreement & Failure-Case Analysis",
            f"- Jobs appearing ONLY in Legacy Top-10: {len(self.legacy_only_top_10)}",
            f"- Jobs appearing ONLY in Explainable Top-10: {len(self.explainable_only_top_10)}",
            f"- HIGH_RELEVANCE jobs missed by Legacy Top-10: {len(self.high_relevance_missed_legacy)}",
            f"- HIGH_RELEVANCE jobs missed by Explainable Top-10: {len(self.high_relevance_missed_explainable)}",
            f"- IRRELEVANT jobs ranked in Legacy Top-10: {len(self.irrelevant_in_top_k_legacy)}",
            f"- IRRELEVANT jobs ranked in Explainable Top-10: {len(self.irrelevant_in_top_k_explainable)}",
            f"- Hard Constraint FAIL jobs ranked in Legacy Top-10: {len(self.hard_constraint_fails_in_legacy_top_k)}",
            f"- Semantic Language Gap cases: {len(self.semantic_language_gap_cases)}",
            f"- Large Rank Disagreements (|rank_delta| >= 5): {len(self.large_rank_disagreements)}",
        ]
        return "\n".join(lines)


def run_benchmark(
    benchmark_pairs: Union[list[EvaluationRecord], list[dict[str, Any]], str, Path],
    candidates: dict[str, CandidateProfile],
    jobs: dict[str, JobProfile],
    raw_resumes: Optional[dict[str, str]] = None,
    k_values: tuple[int, ...] = (5, 10),
    large_rank_delta_threshold: int = 5,
    timestamp: Optional[str] = None,
) -> BenchmarkReport:
    """Run deterministic benchmark evaluation comparing Legacy TF-IDF and Explainable Matcher.

    Args:
        benchmark_pairs: JSONL filepath, list of EvaluationRecords, or list of pair dictionaries.
        candidates: Dictionary mapping candidate_id to CandidateProfile.
        jobs: Dictionary mapping job_id to JobProfile.
        raw_resumes: Optional dictionary mapping candidate_id to raw resume text string.
        k_values: Ranking cutoffs for Precision@K and Recall@K (default (5, 10)).
        large_rank_delta_threshold: Threshold to flag large rank disagreements.
        timestamp: Optional fixed timestamp string for determinism.

    Returns:
        BenchmarkReport dataclass.
    """
    integrity_stats = validate_benchmark_integrity(benchmark_pairs)

    raw_pairs: list[dict[str, Any]] = []
    if isinstance(benchmark_pairs, (str, Path)):
        records = load_evaluation_records(benchmark_pairs, validate=True)
        raw_pairs = [r.to_dict() for r in records]
    elif isinstance(benchmark_pairs, list):
        for item in benchmark_pairs:
            raw_pairs.append(
                item.to_dict() if isinstance(item, EvaluationRecord) else dict(item)
            )

    # Group pairs by candidate_id
    pairs_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for p in raw_pairs:
        cid = str(p["candidate_id"]).strip()
        pairs_by_candidate.setdefault(cid, []).append(p)

    all_records: list[EvaluationRecord] = []
    candidate_summaries: list[dict[str, Any]] = []

    legacy_only_top_10: list[dict[str, Any]] = []
    explainable_only_top_10: list[dict[str, Any]] = []
    high_rel_missed_leg: list[dict[str, Any]] = []
    high_rel_missed_exp: list[dict[str, Any]] = []
    irrelevant_top_leg: list[dict[str, Any]] = []
    irrelevant_top_exp: list[dict[str, Any]] = []
    borderline_disagree: list[dict[str, Any]] = []
    hard_fail_in_leg_k: list[dict[str, Any]] = []
    semantic_gap_cases: list[dict[str, Any]] = []
    large_disagreements: list[dict[str, Any]] = []

    unique_evaluated_jobs: set[str] = set()

    for cand_id, c_pairs in pairs_by_candidate.items():
        if cand_id not in candidates:
            raise ValueError(
                f"Candidate '{cand_id}' from benchmark pair not found in provided candidates dictionary."
            )
        cand_profile = candidates[cand_id]

        c_jobs: list[JobProfile] = []
        c_labels: dict[str, str] = {}
        c_notes: dict[str, str] = {}
        c_reviewers: dict[str, str] = {}
        c_gap_categories: dict[str, str] = {}

        for p in c_pairs:
            jid = str(p["job_id"]).strip()
            if jid not in jobs:
                raise ValueError(
                    f"Job '{jid}' from benchmark pair for candidate '{cand_id}' not found in provided jobs dictionary."
                )
            c_jobs.append(jobs[jid])
            unique_evaluated_jobs.add(jid)
            if p.get("human_label"):
                c_labels[jid] = p["human_label"]
            if p.get("notes"):
                c_notes[jid] = p["notes"]
            if p.get("reviewer_id"):
                c_reviewers[jid] = p["reviewer_id"]
            if p.get("semantic_gap_category"):
                c_gap_categories[jid] = p["semantic_gap_category"]

        summary_10 = compare_matchers(
            candidate=cand_profile,
            jobs=c_jobs,
            raw_resume_text=raw_resumes.get(cand_id) if raw_resumes else None,
            candidate_id=cand_id,
            k=10,
            human_labels=c_labels,
            notes=c_notes,
            large_rank_delta_threshold=large_rank_delta_threshold,
            timestamp=timestamp,
            reviewer_ids=c_reviewers,
            semantic_gap_categories=c_gap_categories,
        )

        leg_m_5 = calculate_ranking_metrics(
            summary_10.records, rank_attr="legacy_rank", k=5
        )
        exp_m_5 = calculate_ranking_metrics(
            summary_10.records, rank_attr="explainable_rank", k=5
        )

        actual_5 = min(5, len(summary_10.records))
        top5_leg = {r.job_id for r in summary_10.records if r.legacy_rank <= actual_5}
        top5_exp = {
            r.job_id for r in summary_10.records if r.explainable_rank <= actual_5
        }
        top5_overlap = len(top5_leg & top5_exp)
        top5_union = len(top5_leg | top5_exp)
        top5_jaccard = round(top5_overlap / top5_union, 4) if top5_union else 1.0

        candidate_summaries.append(
            {
                "candidate_id": cand_id,
                "total_jobs": len(c_jobs),
                "legacy_metrics_at_5": leg_m_5.to_dict(),
                "legacy_metrics_at_10": summary_10.legacy_metrics.to_dict(),
                "explainable_metrics_at_5": exp_m_5.to_dict(),
                "explainable_metrics_at_10": summary_10.explainable_metrics.to_dict(),
                "top_k_overlap_at_5": top5_overlap,
                "top_k_jaccard_at_5": top5_jaccard,
                "top_k_overlap_at_10": summary_10.top_k_overlap_count,
                "top_k_jaccard_at_10": summary_10.top_k_jaccard_similarity,
            }
        )

        all_records.extend(summary_10.records)

        for r in summary_10.records:
            rd = r.to_dict()
            if r.in_legacy_top_k and not r.in_explainable_top_k:
                legacy_only_top_10.append(rd)
            if r.in_explainable_top_k and not r.in_legacy_top_k:
                explainable_only_top_10.append(rd)
            if r.human_label == HumanLabel.HIGH_RELEVANCE.value:
                if not r.in_legacy_top_k:
                    high_rel_missed_leg.append(rd)
                if not r.in_explainable_top_k:
                    high_rel_missed_exp.append(rd)
            elif r.human_label == HumanLabel.IRRELEVANT.value:
                if r.in_legacy_top_k:
                    irrelevant_top_leg.append(rd)
                if r.in_explainable_top_k:
                    irrelevant_top_exp.append(rd)
            elif r.human_label == HumanLabel.BORDERLINE.value:
                if abs(r.rank_delta) >= large_rank_delta_threshold:
                    borderline_disagree.append(rd)

            if r.hard_constraint_status == "FAIL" and r.in_legacy_top_k:
                hard_fail_in_leg_k.append(rd)

            if (
                r.semantic_gap_category == SemanticGapCategory.SEMANTIC_LANGUAGE_GAP.value
                or (
                    r.human_label == HumanLabel.HIGH_RELEVANCE.value
                    and r.legacy_score < 0.15
                )
            ):
                semantic_gap_cases.append(rd)

            if abs(r.rank_delta) >= large_rank_delta_threshold:
                large_disagreements.append(rd)

    # Multi-candidate micro-averaging for aggregate metrics
    def _micro_average_metric(metric_key: str, k: int) -> MetricResult:
        total_eval_k = sum(
            cs[metric_key]["actual_k"] for cs in candidate_summaries
        )
        total_high_rel = sum(
            cs[metric_key]["total_high_relevance"] for cs in candidate_summaries
        )
        high_rel_in_top_k = sum(
            cs[metric_key]["high_relevance_in_top_k"] for cs in candidate_summaries
        )
        if total_high_rel == 0 or total_eval_k == 0:
            return MetricResult(
                status="insufficient_labeled_data",
                k=k,
                actual_k=total_eval_k,
                precision_at_k=None,
                recall_at_k=None,
                total_high_relevance=total_high_rel,
                high_relevance_in_top_k=high_rel_in_top_k,
            )
        prec = round(high_rel_in_top_k / total_eval_k, 4)
        rec = round(high_rel_in_top_k / total_high_rel, 4)
        return MetricResult(
            status="calculated",
            k=k,
            actual_k=total_eval_k,
            precision_at_k=prec,
            recall_at_k=rec,
            total_high_relevance=total_high_rel,
            high_relevance_in_top_k=high_rel_in_top_k,
        )

    agg_leg_5 = _micro_average_metric("legacy_metrics_at_5", 5)
    agg_leg_10 = _micro_average_metric("legacy_metrics_at_10", 10)
    agg_exp_5 = _micro_average_metric("explainable_metrics_at_5", 5)
    agg_exp_10 = _micro_average_metric("explainable_metrics_at_10", 10)

    num_cands = len(candidate_summaries)
    mean_jaccard_5 = (
        round(sum(cs["top_k_jaccard_at_5"] for cs in candidate_summaries) / num_cands, 4)
        if num_cands
        else 1.0
    )
    mean_jaccard_10 = (
        round(sum(cs["top_k_jaccard_at_10"] for cs in candidate_summaries) / num_cands, 4)
        if num_cands
        else 1.0
    )
    tot_overlap_5 = sum(cs["top_k_overlap_at_5"] for cs in candidate_summaries)
    tot_overlap_10 = sum(cs["top_k_overlap_at_10"] for cs in candidate_summaries)

    return BenchmarkReport(
        schema_version=SCHEMA_VERSION,
        timestamp=timestamp,
        total_candidates=len(pairs_by_candidate),
        total_jobs=len(unique_evaluated_jobs),
        total_pairs=len(raw_pairs),
        labeled_pairs_count=integrity_stats["labeled_count"],
        high_relevance_count=integrity_stats["high_relevance_count"],
        borderline_count=integrity_stats["borderline_count"],
        irrelevant_count=integrity_stats["irrelevant_count"],
        unlabeled_count=integrity_stats["unlabeled_count"],
        legacy_metrics_at_5=agg_leg_5,
        legacy_metrics_at_10=agg_leg_10,
        explainable_metrics_at_5=agg_exp_5,
        explainable_metrics_at_10=agg_exp_10,
        top_k_overlap_at_5=tot_overlap_5,
        top_k_jaccard_at_5=mean_jaccard_5,
        top_k_overlap_at_10=tot_overlap_10,
        top_k_jaccard_at_10=mean_jaccard_10,
        legacy_only_top_10=legacy_only_top_10,
        explainable_only_top_10=explainable_only_top_10,
        high_relevance_missed_legacy=high_rel_missed_leg,
        high_relevance_missed_explainable=high_rel_missed_exp,
        irrelevant_in_top_k_legacy=irrelevant_top_leg,
        irrelevant_in_top_k_explainable=irrelevant_top_exp,
        borderline_disagreements=borderline_disagree,
        hard_constraint_fails_in_legacy_top_k=hard_fail_in_leg_k,
        semantic_language_gap_cases=semantic_gap_cases,
        large_rank_disagreements=large_disagreements,
        candidate_summaries=candidate_summaries,
        records=all_records,
    )


__all__ = [
    "SCHEMA_VERSION",
    "HumanLabel",
    "VALID_HUMAN_LABELS",
    "SemanticGapCategory",
    "VALID_SEMANTIC_GAP_CATEGORIES",
    "BenchmarkIntegrityError",
    "EvaluationRecord",
    "MetricResult",
    "ComparisonSummary",
    "BenchmarkReport",
    "validate_evaluation_record",
    "validate_benchmark_integrity",
    "calculate_ranking_metrics",
    "compare_matchers",
    "run_benchmark",
    "save_evaluation_records",
    "load_evaluation_records",
    "load_benchmark_dataset",
]

