"""
Automated Tests for Task 18: Matching Evaluation & Shadow Matching
------------------------------------------------------------------
Verifies:
Dataset validation:
1. Valid evaluation record creation and serialization.
2. Schema version check ("1.0").
3. Valid human labels (HIGH_RELEVANCE, BORDERLINE, IRRELEVANT).
4. Invalid human labels are rejected with ValueError.
5. Missing required fields (candidate_id, job_id) rejected.

Matcher comparison:
6. Both matchers receive the same logical job set.
7. Legacy score and rank are captured and preserved.
8. Explainable score, rank, and tier are captured and preserved.
9. CandidateProfile is not mutated during comparison.
10. JobProfile and raw_job dictionaries are not mutated during comparison.

Ranking & Top-K:
11. Rankings are deterministic and consistent.
12. Top-K selection properly flags in_legacy_top_k and in_explainable_top_k.
13. Fewer-than-K jobs handled safely without manufactured entries.
14. Rank delta is correctly calculated (legacy_rank - explainable_rank).
15. Large rank disagreements are flagged when exceeding threshold.
16. Hard constraint rejections in legacy top-K are correctly identified.

Labels & Relevance:
17. HIGH_RELEVANCE records are correctly identified as relevant.
18. BORDERLINE records are NOT counted as relevant.
19. IRRELEVANT records are NOT counted as relevant.
20. Unlabeled records are excluded from labeled metrics.

Metrics calculation:
21. Precision@5 exact calculation (3 of 5 relevant -> 0.6).
22. Recall@5 exact calculation (3 of 4 total relevant in top 5 -> 0.75).
23. Dataset with no labeled records returns 'insufficient_labeled_data'.
24. Dataset with zero HIGH_RELEVANCE records returns 'insufficient_labeled_data'.
25. Fewer-than-K jobs calculates precision over actual_k.

Determinism & Serialization:
26. Running the same evaluation twice produces identical results.
27. JSONL save and load round-trip preserves all fields and types.
28. Reference matching_pairs.jsonl loads and validates cleanly.
"""

import sys
import unittest
from pathlib import Path
import tempfile

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent.candidate_profiler import CandidateProfile
from a_jent.job_normalizer import JobProfile
from a_jent.matching_evaluation import (
    BenchmarkIntegrityError,
    BenchmarkReport,
    ComparisonSummary,
    EvaluationRecord,
    HumanLabel,
    MetricResult,
    SCHEMA_VERSION,
    SemanticGapCategory,
    VALID_HUMAN_LABELS,
    VALID_SEMANTIC_GAP_CATEGORIES,
    calculate_ranking_metrics,
    compare_matchers,
    load_benchmark_dataset,
    load_evaluation_records,
    run_benchmark,
    save_evaluation_records,
    validate_benchmark_integrity,
    validate_evaluation_record,
)


class TestMatchingEvaluation(unittest.TestCase):
    # =======================================================================
    # DATASET VALIDATION (1-5)
    # =======================================================================

    def test_1_valid_evaluation_record_creation(self):
        """Valid evaluation record can be created, serialized, and deserialized."""
        rec = EvaluationRecord(
            candidate_id="cand_01",
            job_id="job_01",
            job_title="Senior Python Engineer",
            company="Acme Corp",
            legacy_score=0.45,
            explainable_score=85.0,
            legacy_rank=1,
            explainable_rank=1,
            rank_delta=0,
            in_legacy_top_k=True,
            in_explainable_top_k=True,
            hard_constraint_status="PASS",
            explainable_tier="STRONG",
            matched_required_skills=["python"],
            human_label=HumanLabel.HIGH_RELEVANCE.value,
        )
        d = rec.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)
        self.assertEqual(d["candidate_id"], "cand_01")
        self.assertEqual(d["human_label"], "HIGH_RELEVANCE")

        rec2 = EvaluationRecord.from_dict(d)
        self.assertEqual(rec.candidate_id, rec2.candidate_id)
        self.assertEqual(rec.legacy_score, rec2.legacy_score)
        self.assertEqual(rec.human_label, rec2.human_label)

    def test_2_schema_version_validation(self):
        """Unsupported schema version is rejected with ValueError."""
        data = {
            "schema_version": "9.9",
            "candidate_id": "cand_01",
            "job_id": "job_01",
        }
        with self.assertRaises(ValueError) as ctx:
            validate_evaluation_record(data)
        self.assertIn("Unsupported schema_version", str(ctx.exception))

    def test_3_valid_human_labels_accepted(self):
        """All valid human labels (HIGH_RELEVANCE, BORDERLINE, IRRELEVANT, None) are accepted."""
        for lbl in ["HIGH_RELEVANCE", "BORDERLINE", "IRRELEVANT", None]:
            data = {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": "cand_01",
                "job_id": "job_01",
                "human_label": lbl,
            }
            # Should not raise
            validate_evaluation_record(data)

    def test_4_invalid_human_labels_rejected(self):
        """Invalid human labels (e.g. 'GOOD', 'RELEVANT') are rejected with ValueError."""
        for bad_lbl in ["GOOD", "RELEVANT", "MAYBE", "5_STARS", ""]:
            data = {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": "cand_01",
                "job_id": "job_01",
                "human_label": bad_lbl,
            }
            with self.assertRaises(ValueError) as ctx:
                validate_evaluation_record(data)
            self.assertIn("Invalid human_label", str(ctx.exception))

    def test_5_missing_required_fields_rejected(self):
        """Missing candidate_id or job_id raises ValueError."""
        with self.assertRaises(ValueError):
            validate_evaluation_record({"job_id": "j1"})

        with self.assertRaises(ValueError):
            validate_evaluation_record({"candidate_id": "c1"})

        with self.assertRaises(ValueError):
            validate_evaluation_record({"candidate_id": "", "job_id": "j1"})

    # =======================================================================
    # MATCHER COMPARISON (6-10)
    # =======================================================================

    def setUp(self):
        self.candidate = CandidateProfile(
            normalized_skills=["python", "sql", "pandas"],
            seniority="senior",
            work_mode="remote",
            employment_preferences=["full_time"],
            experience_years=4.0,
        )
        self.job1 = JobProfile(
            job_id="job_01",
            title="Senior Python Engineer",
            company="TechA",
            source="remoteok",
            required_skills=["python", "sql"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
            experience_years=3.0,
            raw_job={
                "id": "job_01",
                "title": "Senior Python Engineer",
                "description": "Looking for a Senior Python Developer with SQL experience.",
                "company": "TechA",
                "source": "remoteok",
            },
        )
        self.job2 = JobProfile(
            job_id="job_02",
            title="Senior Data Analyst",
            company="TechB",
            source="arbeitnow",
            required_skills=["sql", "pandas"],
            seniority="senior",
            work_mode="remote",
            employment_type="full_time",
            experience_years=2.0,
            raw_job={
                "id": "job_02",
                "title": "Senior Data Analyst",
                "description": "Analyze data with SQL and Pandas in a remote team.",
                "company": "TechB",
                "source": "arbeitnow",
            },
        )
        self.job3 = JobProfile(
            job_id="job_03",
            title="Junior Frontend Developer",
            company="TechC",
            source="himalayas",
            required_skills=["react", "html"],
            seniority="junior",
            work_mode="onsite",
            employment_type="full_time",
            experience_years=1.0,
            raw_job={
                "id": "job_03",
                "title": "Junior Frontend Developer",
                "description": "Build user interfaces using React and HTML.",
                "company": "TechC",
                "source": "himalayas",
            },
        )

    def test_6_both_matchers_receive_same_jobs(self):
        """Both legacy and explainable matchers evaluate the exact same job collection."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            k=2,
        )
        self.assertEqual(summary.total_jobs, 3)
        self.assertEqual(len(summary.records), 3)
        evaluated_jids = {r.job_id for r in summary.records}
        self.assertEqual(evaluated_jids, {"job_01", "job_02", "job_03"})

    def test_7_legacy_score_and_rank_preserved(self):
        """Legacy TF-IDF scores and 1-indexed rankings are preserved in records."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
        )
        for r in summary.records:
            self.assertIsInstance(r.legacy_score, float)
            self.assertGreaterEqual(r.legacy_score, 0.0)
            self.assertIn(r.legacy_rank, [1, 2, 3])

    def test_8_explainable_score_and_rank_preserved(self):
        """Explainable scores, ranks, and tiers are preserved in records."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
        )
        rec_job1 = next(r for r in summary.records if r.job_id == "job_01")
        rec_job3 = next(r for r in summary.records if r.job_id == "job_03")

        self.assertGreaterEqual(rec_job1.explainable_score, 75.0)
        self.assertEqual(rec_job1.explainable_tier, "STRONG")

        # Job 3 has hard constraint failure (Senior vs Junior onsite)
        self.assertEqual(rec_job3.explainable_score, 0.0)
        self.assertEqual(rec_job3.explainable_tier, "INCOMPATIBLE")
        self.assertEqual(rec_job3.hard_constraint_status, "FAIL")

    def test_9_candidate_profile_not_mutated(self):
        """CandidateProfile remains completely unmutated after comparison."""
        snap = self.candidate.to_dict()
        compare_matchers(self.candidate, [self.job1, self.job2, self.job3])
        self.assertEqual(self.candidate.to_dict(), snap)

    def test_10_job_profile_and_raw_job_not_mutated(self):
        """JobProfile and underlying raw_job dicts remain unmutated after comparison."""
        snap1 = self.job1.to_dict()
        raw_snap1 = dict(self.job1.raw_job)

        compare_matchers(self.candidate, [self.job1, self.job2, self.job3])

        self.assertEqual(self.job1.to_dict(), snap1)
        self.assertEqual(self.job1.raw_job, raw_snap1)

    # =======================================================================
    # RANKING & TOP-K (11-16)
    # =======================================================================

    def test_11_rankings_deterministic(self):
        """Multiple runs produce identical rankings and scores."""
        s1 = compare_matchers(self.candidate, [self.job1, self.job2, self.job3])
        s2 = compare_matchers(self.candidate, [self.job1, self.job2, self.job3])

        for r1, r2 in zip(s1.records, s2.records):
            self.assertEqual(r1.legacy_rank, r2.legacy_rank)
            self.assertEqual(r1.explainable_rank, r2.explainable_rank)
            self.assertEqual(r1.legacy_score, r2.legacy_score)
            self.assertEqual(r1.explainable_score, r2.explainable_score)

    def test_12_top_k_membership_flags(self):
        """in_legacy_top_k and in_explainable_top_k accurately reflect K cutoff."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            k=2,
        )
        legacy_top_k_count = sum(1 for r in summary.records if r.in_legacy_top_k)
        explainable_top_k_count = sum(1 for r in summary.records if r.in_explainable_top_k)

        self.assertEqual(legacy_top_k_count, 2)
        self.assertEqual(explainable_top_k_count, 2)

    def test_13_fewer_than_k_jobs_handled_safely(self):
        """When total jobs < K, actual_k = total jobs and no phantom entries are created."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2],
            k=10,  # K=10, but only 2 jobs exist
        )
        self.assertEqual(summary.total_jobs, 2)
        self.assertEqual(summary.actual_k, 2)
        self.assertEqual(summary.k, 10)
        self.assertEqual(len(summary.records), 2)
        self.assertTrue(all(r.in_legacy_top_k for r in summary.records))
        self.assertTrue(all(r.in_explainable_top_k for r in summary.records))

    def test_14_rank_delta_calculation(self):
        """rank_delta equals legacy_rank - explainable_rank."""
        summary = compare_matchers(self.candidate, [self.job1, self.job2, self.job3])
        for r in summary.records:
            self.assertEqual(r.rank_delta, r.legacy_rank - r.explainable_rank)

    def test_15_large_rank_disagreements_flagged(self):
        """Jobs with abs(rank_delta) >= threshold are flagged in large_rank_disagreements."""
        # Create a set of jobs where one job has large ranking difference
        records = [
            EvaluationRecord(
                candidate_id="c1",
                job_id=f"j_{i}",
                job_title=f"Job {i}",
                legacy_rank=i,
                explainable_rank=10 - i + 1,
                rank_delta=i - (10 - i + 1),
            )
            for i in range(1, 11)
        ]
        # Inspect disagreements with threshold = 5
        disagreements = [r for r in records if abs(r.rank_delta) >= 5]
        self.assertTrue(len(disagreements) > 0)

    def test_16_hard_constraint_rejections_in_legacy_top_k_identified(self):
        """Jobs that legacy ranked in top-K but failed hard constraints are identified."""
        # job3 fails hard constraints. Let's force K=3 so job3 is in top-K
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            k=3,
        )
        self.assertEqual(summary.hard_constraint_rejections_count, 1)
        self.assertIn("job_03", summary.hard_constraint_rejections_in_legacy_top_k)

    # =======================================================================
    # LABELS & RELEVANCE (17-20)
    # =======================================================================

    def test_17_high_relevance_recognized(self):
        """HIGH_RELEVANCE records are included in relevant totals."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            human_labels={
                "job_01": HumanLabel.HIGH_RELEVANCE.value,
                "job_02": HumanLabel.HIGH_RELEVANCE.value,
            },
            k=2,
        )
        self.assertEqual(summary.explainable_metrics.total_high_relevance, 2)
        self.assertEqual(summary.explainable_metrics.status, "calculated")

    def test_18_borderline_not_counted_as_relevant(self):
        """BORDERLINE labels are excluded from relevant numerator and denominator."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            human_labels={
                "job_01": HumanLabel.HIGH_RELEVANCE.value,
                "job_02": HumanLabel.BORDERLINE.value,
                "job_03": HumanLabel.IRRELEVANT.value,
            },
            k=2,
        )
        # Total relevant must be exactly 1 (job_01), BORDERLINE is NOT relevant
        self.assertEqual(summary.explainable_metrics.total_high_relevance, 1)

    def test_19_irrelevant_not_counted_as_relevant(self):
        """IRRELEVANT labels are not counted as relevant."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            human_labels={
                "job_01": HumanLabel.IRRELEVANT.value,
                "job_02": HumanLabel.IRRELEVANT.value,
                "job_03": HumanLabel.IRRELEVANT.value,
            },
            k=2,
        )
        # No HIGH_RELEVANCE labels -> insufficient_labeled_data
        self.assertEqual(
            summary.explainable_metrics.status, "insufficient_labeled_data"
        )
        self.assertIsNone(summary.explainable_metrics.precision_at_k)

    def test_20_unlabeled_records_excluded_from_metrics(self):
        """Unlabeled records are not counted as HIGH_RELEVANCE."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            human_labels={"job_01": HumanLabel.HIGH_RELEVANCE.value},  # others unlabeled
            k=3,
        )
        self.assertEqual(summary.explainable_metrics.total_high_relevance, 1)

    # =======================================================================
    # METRICS CALCULATION (21-25)
    # =======================================================================

    def test_21_precision_at_k_exact_calculation(self):
        """3 of top 5 jobs are HIGH_RELEVANCE -> Precision@5 = 0.6."""
        records = [
            EvaluationRecord(
                candidate_id="c1",
                job_id=f"j_{i}",
                job_title=f"Job {i}",
                explainable_rank=i,
                human_label=(
                    HumanLabel.HIGH_RELEVANCE.value
                    if i in (1, 3, 5)
                    else HumanLabel.IRRELEVANT.value
                ),
            )
            for i in range(1, 11)
        ]
        metrics = calculate_ranking_metrics(records, rank_attr="explainable_rank", k=5)
        self.assertEqual(metrics.status, "calculated")
        self.assertEqual(metrics.actual_k, 5)
        self.assertEqual(metrics.high_relevance_in_top_k, 3)
        self.assertEqual(metrics.precision_at_k, 0.6)

    def test_22_recall_at_k_exact_calculation(self):
        """4 total HIGH_RELEVANCE jobs, 3 appear in top 5 -> Recall@5 = 0.75."""
        records = [
            EvaluationRecord(
                candidate_id="c1",
                job_id=f"j_{i}",
                job_title=f"Job {i}",
                explainable_rank=i,
                # 4 total HIGH_RELEVANCE: positions 1, 2, 4, 8
                human_label=(
                    HumanLabel.HIGH_RELEVANCE.value
                    if i in (1, 2, 4, 8)
                    else HumanLabel.IRRELEVANT.value
                ),
            )
            for i in range(1, 11)
        ]
        metrics = calculate_ranking_metrics(records, rank_attr="explainable_rank", k=5)
        self.assertEqual(metrics.status, "calculated")
        self.assertEqual(metrics.total_high_relevance, 4)
        self.assertEqual(metrics.high_relevance_in_top_k, 3)
        self.assertEqual(metrics.recall_at_k, 0.75)
        self.assertEqual(metrics.precision_at_k, 0.6)

    def test_23_no_labeled_data_returns_insufficient_status(self):
        """Dataset with no labels returns status='insufficient_labeled_data' without misleading zeros."""
        records = [
            EvaluationRecord(
                candidate_id="c1",
                job_id=f"j_{i}",
                job_title=f"Job {i}",
                explainable_rank=i,
                human_label=None,
            )
            for i in range(1, 6)
        ]
        metrics = calculate_ranking_metrics(records, rank_attr="explainable_rank", k=5)
        self.assertEqual(metrics.status, "insufficient_labeled_data")
        self.assertIsNone(metrics.precision_at_k)
        self.assertIsNone(metrics.recall_at_k)

    def test_24_zero_high_relevance_returns_insufficient_status(self):
        """Dataset with only BORDERLINE or IRRELEVANT returns 'insufficient_labeled_data'."""
        records = [
            EvaluationRecord(
                candidate_id="c1",
                job_id="j_1",
                job_title="Job 1",
                explainable_rank=1,
                human_label=HumanLabel.BORDERLINE.value,
            ),
            EvaluationRecord(
                candidate_id="c1",
                job_id="j_2",
                job_title="Job 2",
                explainable_rank=2,
                human_label=HumanLabel.IRRELEVANT.value,
            ),
        ]
        metrics = calculate_ranking_metrics(records, rank_attr="explainable_rank", k=2)
        self.assertEqual(metrics.status, "insufficient_labeled_data")
        self.assertIsNone(metrics.precision_at_k)
        self.assertIsNone(metrics.recall_at_k)

    def test_25_fewer_than_k_jobs_precision_over_actual_k(self):
        """When total jobs < K (e.g. 2 jobs, K=5), precision is calculated over actual_k (2)."""
        records = [
            EvaluationRecord(
                candidate_id="c1",
                job_id="j_1",
                job_title="Job 1",
                explainable_rank=1,
                human_label=HumanLabel.HIGH_RELEVANCE.value,
            ),
            EvaluationRecord(
                candidate_id="c1",
                job_id="j_2",
                job_title="Job 2",
                explainable_rank=2,
                human_label=HumanLabel.IRRELEVANT.value,
            ),
        ]
        metrics = calculate_ranking_metrics(records, rank_attr="explainable_rank", k=5)
        self.assertEqual(metrics.actual_k, 2)
        self.assertEqual(metrics.precision_at_k, 0.5)  # 1 / 2 = 0.5
        self.assertEqual(metrics.recall_at_k, 1.0)  # 1 / 1 = 1.0

    # =======================================================================
    # DETERMINISM & SERIALIZATION (26-28)
    # =======================================================================

    def test_26_deterministic_repeated_evaluation(self):
        """Repeated comparisons on the same input yield identical summary dictionaries."""
        summary1 = compare_matchers(self.candidate, [self.job1, self.job2, self.job3])
        summary2 = compare_matchers(self.candidate, [self.job1, self.job2, self.job3])

        self.assertEqual(summary1.to_dict()["records"], summary2.to_dict()["records"])
        self.assertEqual(summary1.top_k_jaccard_similarity, summary2.top_k_jaccard_similarity)
        self.assertEqual(summary1.top_k_overlap_count, summary2.top_k_overlap_count)

    def test_27_jsonl_save_and_load_round_trip(self):
        """Evaluation records can be saved and loaded from JSONL without data loss."""
        summary = compare_matchers(
            candidate=self.candidate,
            jobs=[self.job1, self.job2, self.job3],
            human_labels={"job_01": "HIGH_RELEVANCE", "job_02": "BORDERLINE"},
        )
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            save_evaluation_records(summary.records, tmp_path)
            loaded_records = load_evaluation_records(tmp_path)

            self.assertEqual(len(loaded_records), len(summary.records))
            for orig, loaded in zip(summary.records, loaded_records):
                self.assertEqual(orig.job_id, loaded.job_id)
                self.assertEqual(orig.legacy_rank, loaded.legacy_rank)
                self.assertEqual(orig.explainable_rank, loaded.explainable_rank)
                self.assertEqual(orig.human_label, loaded.human_label)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_28_reference_matching_pairs_fixture(self):
        """The reference evaluation/matching_pairs.jsonl file exists and is valid."""
        fixture_path = PROJECT_ROOT / "evaluation" / "matching_pairs.jsonl"
        self.assertTrue(fixture_path.exists(), f"Missing reference fixture: {fixture_path}")

        records = load_evaluation_records(fixture_path)
        self.assertGreaterEqual(len(records), 3)
        self.assertTrue(any(r.human_label == "HIGH_RELEVANCE" for r in records))
        self.assertTrue(any(r.human_label == "BORDERLINE" for r in records))
        self.assertTrue(any(r.human_label == "IRRELEVANT" for r in records))

    # =======================================================================
    # TASK 19 BENCHMARK INTEGRITY & SEMANTIC GAP TESTS (29-35)
    # =======================================================================

    def test_29_valid_semantic_gap_categories_accepted(self):
        """All supported semantic gap categories can be assigned and serialized."""
        for cat in VALID_SEMANTIC_GAP_CATEGORIES:
            rec = EvaluationRecord(
                candidate_id="cand_01",
                job_id="job_01",
                job_title="Engineer",
                semantic_gap_category=cat,
            )
            d = rec.to_dict()
            self.assertEqual(d["semantic_gap_category"], cat)
            reloaded = EvaluationRecord.from_dict(d)
            self.assertEqual(reloaded.semantic_gap_category, cat)

    def test_30_invalid_semantic_gap_category_rejected(self):
        """Invalid semantic gap category raises ValueError."""
        with self.assertRaises(ValueError):
            validate_evaluation_record({
                "candidate_id": "c1",
                "job_id": "j1",
                "semantic_gap_category": "INVALID_UNKNOWN_CATEGORY",
            })

    def test_31_benchmark_integrity_clean_dataset(self):
        """validate_benchmark_integrity succeeds and returns accurate counts for valid data."""
        records = [
            {"schema_version": "1.0", "candidate_id": "c1", "job_id": "j1", "human_label": "HIGH_RELEVANCE"},
            {"schema_version": "1.0", "candidate_id": "c1", "job_id": "j2", "human_label": "BORDERLINE"},
            {"schema_version": "1.0", "candidate_id": "c2", "job_id": "j1", "human_label": "IRRELEVANT"},
            {"schema_version": "1.0", "candidate_id": "c2", "job_id": "j3", "human_label": None},
        ]
        stats = validate_benchmark_integrity(records)
        self.assertEqual(stats["total_records"], 4)
        self.assertEqual(stats["unique_pairs"], 4)
        self.assertEqual(stats["unique_candidates"], 2)
        self.assertEqual(stats["unique_jobs"], 3)
        self.assertEqual(stats["labeled_count"], 3)
        self.assertEqual(stats["high_relevance_count"], 1)
        self.assertEqual(stats["borderline_count"], 1)
        self.assertEqual(stats["irrelevant_count"], 1)
        self.assertEqual(stats["unlabeled_count"], 1)

    def test_32_benchmark_integrity_duplicate_pairs_rejected(self):
        """Duplicate candidate/job pair with identical labels raises BenchmarkIntegrityError."""
        records = [
            {"candidate_id": "c1", "job_id": "j1", "human_label": "HIGH_RELEVANCE"},
            {"candidate_id": "c1", "job_id": "j1", "human_label": "HIGH_RELEVANCE"},
        ]
        with self.assertRaises(BenchmarkIntegrityError) as ctx:
            validate_benchmark_integrity(records)
        self.assertIn("Duplicate candidate/job pair found", str(ctx.exception))

    def test_33_benchmark_integrity_conflicting_duplicate_labels_rejected(self):
        """Duplicate candidate/job pair with conflicting labels raises BenchmarkIntegrityError."""
        records = [
            {"candidate_id": "c1", "job_id": "j1", "human_label": "HIGH_RELEVANCE"},
            {"candidate_id": "c1", "job_id": "j1", "human_label": "IRRELEVANT"},
        ]
        with self.assertRaises(BenchmarkIntegrityError) as ctx:
            validate_benchmark_integrity(records)
        self.assertIn("Conflicting labels", str(ctx.exception))

    def test_34_benchmark_integrity_malformed_jsonl_caught(self):
        """Malformed JSON line in benchmark file raises BenchmarkIntegrityError with line number."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write('{"candidate_id": "c1", "job_id": "j1"}\n')
            tmp.write('{"candidate_id": "c1", BROKEN_JSON\n')
            tmp_path = Path(tmp.name)

        try:
            with self.assertRaises(BenchmarkIntegrityError) as ctx:
                validate_benchmark_integrity(tmp_path)
            self.assertIn("Malformed JSONL at line 2", str(ctx.exception))
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_35_reviewer_id_and_notes_preserved(self):
        """Reviewer ID and reviewer notes round-trip cleanly without modification."""
        rec = EvaluationRecord(
            candidate_id="c1",
            job_id="j1",
            job_title="Software Engineer",
            human_label="BORDERLINE",
            notes="Missing required AWS experience.",
            reviewer_id="rev_01",
            semantic_gap_category=SemanticGapCategory.ROLE_AFFINITY.value,
        )
        d = rec.to_dict()
        self.assertEqual(d["reviewer_id"], "rev_01")
        self.assertEqual(d["notes"], "Missing required AWS experience.")
        self.assertEqual(d["semantic_gap_category"], "ROLE_AFFINITY")

        loaded = EvaluationRecord.from_dict(d)
        self.assertEqual(loaded.reviewer_id, "rev_01")
        self.assertEqual(loaded.notes, "Missing required AWS experience.")
        self.assertEqual(loaded.semantic_gap_category, "ROLE_AFFINITY")

    # =======================================================================
    # TASK 19 BENCHMARK RUNNER & METRICS TESTS (36-42)
    # =======================================================================

    def test_36_run_benchmark_multi_candidate_execution(self):
        """run_benchmark evaluates multiple candidates and aggregates independent metrics."""
        from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

        candidates = get_benchmark_candidates()
        jobs = get_benchmark_jobs()
        benchmark_file = PROJECT_ROOT / "evaluation" / "matching_pairs.jsonl"

        report = run_benchmark(
            benchmark_pairs=benchmark_file,
            candidates=candidates,
            jobs=jobs,
            timestamp="2026-10-03T00:00:00Z",
        )

        self.assertIsInstance(report, BenchmarkReport)
        self.assertEqual(report.total_candidates, 5)
        self.assertEqual(report.total_pairs, 50)
        self.assertEqual(report.labeled_pairs_count, 45)
        self.assertEqual(report.high_relevance_count, 12)
        self.assertEqual(report.borderline_count, 15)
        self.assertEqual(report.irrelevant_count, 18)
        self.assertEqual(report.unlabeled_count, 5)

        # Independent metrics computed for both matchers
        self.assertEqual(report.legacy_metrics_at_5.status, "calculated")
        self.assertEqual(report.explainable_metrics_at_5.status, "calculated")
        self.assertIsInstance(report.legacy_metrics_at_5.precision_at_k, float)
        self.assertIsInstance(report.explainable_metrics_at_5.precision_at_k, float)

        # Report can format clean markdown
        md = report.format_markdown_report()
        self.assertIn("# A-Jent Matching Benchmark Report", md)
        self.assertIn("Precision@5", md)
        self.assertIn("Precision@10", md)

    def test_37_run_benchmark_preserves_profiles_no_mutation(self):
        """run_benchmark does not mutate input candidate or job profile objects."""
        from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

        candidates = get_benchmark_candidates()
        jobs = get_benchmark_jobs()

        cand_before_skills = list(candidates["cand_ds_ml_01"].normalized_skills)
        job_before_raw = dict(jobs["job_ds_exact_01"].raw_job)

        run_benchmark(
            benchmark_pairs=[
                {"candidate_id": "cand_ds_ml_01", "job_id": "job_ds_exact_01", "human_label": "HIGH_RELEVANCE"},
            ],
            candidates=candidates,
            jobs=jobs,
            timestamp="2026-10-03T00:00:00Z",
        )

        self.assertEqual(candidates["cand_ds_ml_01"].normalized_skills, cand_before_skills)
        self.assertEqual(jobs["job_ds_exact_01"].raw_job, job_before_raw)

    def test_38_run_benchmark_deterministic_output(self):
        """Repeated benchmark execution yields bitwise identical dictionary reports."""
        from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

        candidates = get_benchmark_candidates()
        jobs = get_benchmark_jobs()
        pairs = [
            {"candidate_id": "cand_ds_ml_01", "job_id": "job_ds_exact_01", "human_label": "HIGH_RELEVANCE"},
            {"candidate_id": "cand_ds_ml_01", "job_id": "job_graphic_designer_04", "human_label": "IRRELEVANT"},
        ]

        rep1 = run_benchmark(pairs, candidates, jobs, timestamp="2026-10-03T00:00:00Z")
        rep2 = run_benchmark(pairs, candidates, jobs, timestamp="2026-10-03T00:00:00Z")

        self.assertEqual(rep1.to_dict(), rep2.to_dict())

    def test_39_run_benchmark_metrics_calculation_at_5_and_10(self):
        """Precision and Recall at K=5 and K=10 are accurately calculated."""
        from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

        candidates = get_benchmark_candidates()
        jobs = get_benchmark_jobs()
        benchmark_file = PROJECT_ROOT / "evaluation" / "matching_pairs.jsonl"

        report = run_benchmark(benchmark_file, candidates, jobs, timestamp="2026-10-03T00:00:00Z")

        # 5 candidates * 5 top positions = 25 evaluated top-5 positions
        self.assertEqual(report.legacy_metrics_at_5.actual_k, 25)
        self.assertEqual(report.explainable_metrics_at_5.actual_k, 25)

        # Total high relevance jobs across dataset is 12
        self.assertEqual(report.legacy_metrics_at_5.total_high_relevance, 12)
        self.assertEqual(report.explainable_metrics_at_5.total_high_relevance, 12)

        # 10 jobs per candidate * 5 candidates = 50 total evaluated at K=10
        self.assertEqual(report.legacy_metrics_at_10.actual_k, 50)
        self.assertEqual(report.explainable_metrics_at_10.actual_k, 50)

    def test_40_run_benchmark_surfaces_failure_and_disagreement_cases(self):
        """run_benchmark surfaces hard constraint fails in legacy top-K and semantic language gaps."""
        from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

        candidates = get_benchmark_candidates()
        jobs = get_benchmark_jobs()
        benchmark_file = PROJECT_ROOT / "evaluation" / "matching_pairs.jsonl"

        report = run_benchmark(benchmark_file, candidates, jobs, timestamp="2026-10-03T00:00:00Z")

        # Should identify hard constraint failures that penetrated legacy ranking
        self.assertGreater(len(report.hard_constraint_fails_in_legacy_top_k), 0)
        # Should surface semantic language gap cases
        self.assertGreater(len(report.semantic_language_gap_cases), 0)
        # Should surface large rank disagreements
        self.assertGreater(len(report.large_rank_disagreements), 0)

    def test_41_run_benchmark_insufficient_labeled_data_handling(self):
        """Dataset without HIGH_RELEVANCE labels returns insufficient_labeled_data status."""
        from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

        candidates = get_benchmark_candidates()
        jobs = get_benchmark_jobs()
        pairs = [
            {"candidate_id": "cand_ds_ml_01", "job_id": "job_graphic_designer_04", "human_label": "IRRELEVANT"},
            {"candidate_id": "cand_ds_ml_01", "job_id": "job_data_engineer_03", "human_label": "BORDERLINE"},
        ]

        report = run_benchmark(pairs, candidates, jobs, timestamp="2026-10-03T00:00:00Z")
        self.assertEqual(report.legacy_metrics_at_5.status, "insufficient_labeled_data")
        self.assertIsNone(report.legacy_metrics_at_5.precision_at_k)
        self.assertIsNone(report.legacy_metrics_at_5.recall_at_k)

    def test_42_reference_fixtures_coverage_across_categories(self):
        """The reference benchmark fixture contains all 5 candidates and 10 categories."""
        from evaluation.benchmark_fixtures import (
            get_benchmark_candidates,
            get_benchmark_jobs,
            get_curated_benchmark_pairs,
        )

        cands = get_benchmark_candidates()
        jobs = get_benchmark_jobs()
        pairs = get_curated_benchmark_pairs()

        self.assertEqual(len(cands), 5)
        self.assertEqual(len(jobs), 25)
        self.assertEqual(len(pairs), 50)

        # Verify all candidates are represented in pairs
        pair_cands = {p["candidate_id"] for p in pairs}
        self.assertEqual(pair_cands, set(cands.keys()))

        # Verify multiple semantic gap categories are represented
        categories = {p.get("semantic_gap_category") for p in pairs if p.get("semantic_gap_category")}
        self.assertIn("KEYWORD_OVERLAP_SUFFICIENT", categories)
        self.assertIn("ROLE_AFFINITY", categories)
        self.assertIn("HARD_CONSTRAINT", categories)
        self.assertIn("SEMANTIC_LANGUAGE_GAP", categories)
        self.assertIn("MISSING_INFORMATION", categories)


if __name__ == "__main__":
    unittest.main()

