# A-Jent Matching Calibration & Failure Analysis Report

**Task:** Task 20 - Analyze Benchmark Failures and Calibrate Deterministic Matching  
**Dataset:** `evaluation/matching_pairs.jsonl` (50 candidate/job pairs, 5 candidates, 25 jobs)  
**Evaluator Version:** Schema 1.0  

---

## 1. Executive Summary

This report documents the systematic evaluation, root-cause failure analysis, calibration, and before/after metrics of the deterministic explainable matching system.

Key findings:
1. **Mathematical Maximum Baseline:** On the 50-pair benchmark containing 12 human-labeled `HIGH_RELEVANCE` jobs across 5 candidates, the baseline explainable matcher achieved **Precision@5 = 0.4800 (12/25)** and **Recall@5 = 1.0000 (12/12)**, which represents the theoretical ceiling of precision and recall for $K=5$ with this label distribution.
2. **Evaluator Bug Identified:** A genuine constraint evaluator bug in `evaluate_employment_type` treated `job.employment_type == "unknown"` as a literal required employment type that contradicted `"full_time"`, causing `job_underspecified_08` to erroneously fail hard constraints with score $0.0$.
3. **Role Specificity Bug Identified:** Standalone broad keywords `"developer"` and `"engineer"` inside `software_backend["keywords"]` prematurely shadowed specialized titles (`frontend` and `devops_cloud`) due to dictionary evaluation order.
4. **Unrelated Role Omissions:** `UNRELATED_KEYWORDS` lacked `"account executive"` and `"b2b sales"`, allowing enterprise software sales listings to escape negative filtering and score $42.5$ via fallback rules.
5. **Zero-Requirement Free Pass Limitation:** The benchmark exposed that jobs with omitted or empty requirements receive $100\%$ full credit across missing components (required skills, preferred skills, experience), which can inflate underspecified listings (e.g., $92.5$) above genuine high-relevance matches with partial explicit skill match.

---

## 2. Baseline Benchmark Metrics

Independent measurement on `evaluation/matching_pairs.jsonl` before code changes:

| Metric | Legacy TF-IDF | Explainable Matcher (Baseline) | Theoretical Ceiling ($N=12$) | Agreement / Overlap |
| :--- | :--- | :--- | :--- | :--- |
| **Precision@5** | 0.4000 (10/25) | **0.4800** (12/25) | 0.4800 | Top-5 Jaccard: 0.4881 (Overlap: 16) |
| **Recall@5** | 0.8333 (10/12) | **1.0000** (12/12) | 1.0000 | - |
| **Precision@10** | 0.2400 (12/50) | **0.2400** (12/50) | 0.2400 | Top-10 Jaccard: 1.0000 (Overlap: 50) |
| **Recall@10** | 1.0000 (12/12) | **1.0000** (12/12) | 1.0000 | - |

### Disagreement Statistics (Baseline)
- **Large Rank Disagreements ($|\text{rank\_delta}| \ge 5$):** 9 pairs
- **Hard Constraint FAIL jobs in Legacy Top-10:** 12 occurrences
- **HIGH_RELEVANCE jobs missed by Legacy Top-5:** 2 (`job_quant_modeler_06` rank 7, `job_data_mining_research_25` rank 8)
- **HIGH_RELEVANCE jobs missed by Explainable Top-5:** 0 (All 12 retrieved in Top-5)
- **Semantic Language Gap Cases:** 2 pairs

---

## 3. Detailed Failure Case Analysis & Root Causes

### Case 1: `job_onsite_frankfurt_05` (Senior Data Scientist)
- **Candidates:** `cand_ds_ml_01`, `cand_backend_03`, `cand_frontend_04`
- **Legacy Matcher:** Ranked #4 or #5 with scores $0.111$ and $0.047$.
- **Explainable Matcher:** Ranked #9 or #10 with score $0.0$ (`INCOMPATIBLE`).
- **Human Label:** `IRRELEVANT`
- **Root Cause:** `HARD_CONSTRAINT` (Legacy TF-IDF failure).
- **Diagnosis:** Legacy TF-IDF is blind to work-mode constraints, ranking an onsite Frankfurt job highly based solely on word overlap ("Data Scientist", "Python"). Explainable matcher correctly rejected it via hard constraint gating.

### Case 2: `job_sales_executive_24` (Enterprise Account Executive - SaaS Sales)
- **Candidates:** `cand_backend_03`, `cand_frontend_04`, `cand_junior_se_05`
- **Legacy Matcher:** Ranks 9-10 (scores $0.000 - 0.013$).
- **Explainable Matcher (Baseline):** Ranked #4 / #5 (score $42.5$, Tier: WEAK).
- **Human Label:** `IRRELEVANT`
- **Root Cause:** `ROLE_AFFINITY` (Omission in `UNRELATED_KEYWORDS`).
- **Diagnosis:** `UNRELATED_KEYWORDS` included `"sales executive"` and `"sales manager"`, but omitted `"account executive"` (the universal tech title for software sales). Escaping step 1, it fell into step 6 `if cand_skill_track: return 0.70`, awarding $70\%$ role affinity ($17.5$ pts) $+ 10$ (no preferred) $+ 15$ (no exp) $= 42.5$ pts, outranking disqualified jobs.
- **Fixability:** Deterministically fixable by adding `"account executive"` and `"b2b sales"` to `UNRELATED_KEYWORDS`.

### Case 3: `job_underspecified_08` (Data Specialist)
- **Candidates:** `cand_ds_ml_01`, `cand_data_analyst_02`, `cand_junior_se_05`
- **Legacy Matcher:** Ranked #3 - #5 (scores $0.063 - 0.098$).
- **Explainable Matcher (Baseline):** Ranked #9 - #10 (score $0.0$, `INCOMPATIBLE`).
- **Human Label:** `BORDERLINE`
- **Root Cause:** `HARD_CONSTRAINT` (Evaluator bug in `evaluate_employment_type`).
- **Diagnosis:** In `constraint_evaluator.py`, `evaluate_employment_type` checked `if job_type in cand_prefs`. Because `job.employment_type == "unknown"`, it treated `"unknown"` as an explicit requirement that contradicted candidate's `"full_time"`, asserting `status = ConstraintStatus.FAIL`. "unknown" means the job posting omitted employment type; it is NOT a required employment type.
- **Fixability:** Deterministically fixable by handling `job_type in ("unknown", "none")` as `ConstraintStatus.UNKNOWN`.

### Case 4: Sub-string Masking in `ROLE_TRACKS`
- **Jobs:** `job_react_frontend_15`, `job_frontend_angular_23`, `job_devops_engineer_22`
- **Legacy Matcher:** Ranks 1-3.
- **Explainable Matcher (Baseline):** Misclassified roles as `software_backend`.
- **Human Label:** Varied (`HIGH_RELEVANCE` for frontend candidate, `IRRELEVANT` for backend candidate).
- **Root Cause:** `ROLE_AFFINITY` (Keyword priority hazard).
- **Diagnosis:** `software_backend` included standalone words `"developer"` and `"engineer"`. Because dictionary iteration checked `software_backend` before `frontend` and `devops_cloud`, "Senior Frontend Developer" matched `"developer"` and was mislabeled as a backend engineering role. For `cand_backend_03`, this falsely awarded $100\%$ role affinity to a pure React role.
- **Fixability:** Deterministically fixable by:
  1. Removing broad catch-alls `"developer"` and `"engineer"` from `software_backend["keywords"]`.
  2. Adopting maximal-length keyword matching (sorting keyword list by length descending) so specific phrases (`"frontend developer"`, `"devops engineer"`) match before substrings.

### Case 5: `job_bi_analyst_12` (Business Intelligence Analyst)
- **Candidate:** `cand_data_analyst_02`
- **Explainable Matcher (Baseline):** Score $92.5$, Role Affinity $70\%$.
- **Human Label:** `HIGH_RELEVANCE`
- **Root Cause:** `TAXONOMY_GAP` / `ROLE_AFFINITY` (Missing full acronym).
- **Diagnosis:** `data_analytics` keywords contained `"bi analyst"`, but omitted the full phrase `"business intelligence analyst"`. This caused the job to fall into general technical alignment ($70\%$) rather than direct domain alignment ($100\%$).
- **Fixability:** Deterministically fixable by adding `"business intelligence analyst"` and `"business intelligence"` to `data_analytics["keywords"]`.

### Case 6: `job_quant_modeler_06` (Predictive Modeler & Quantitative Researcher)
- **Candidate:** `cand_ds_ml_01`
- **Legacy Matcher:** Rank #7, score $0.0307$ (missed in Top-5).
- **Explainable Matcher (Baseline):** Rank #5, score $82.5$ (retrieved in Top-5).
- **Human Label:** `HIGH_RELEVANCE`
- **Gap Category:** `SEMANTIC_LANGUAGE_GAP`
- **Diagnosis:** Responsibilities are described via mathematical/statistical terms ("statistical estimation algorithms", "mathematical patterns", "automated inference pipelines"). Legacy TF-IDF failed completely due to lack of shared vocabulary. Explainable matcher retrieved it at Rank 5 via Python/SQL skills $+ 70\%$ general alignment. Expanding `data_science_ml["keywords"]` to include `"predictive modeler"` and `"quantitative researcher"` increases role affinity from $70\%$ to $100\%$ (score $90.0$).

---

## 4. Proposed Changes

| Component / File | Specific Change | Behavior Before | Behavior After | Justification / Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `a_jent/constraint_evaluator.py` | In `evaluate_employment_type`: check `if job_type in ("unknown", "none"): return ConstraintStatus.UNKNOWN` | Returned `FAIL` ($0.0$) when candidate sought full-time and job employment type was "unknown". | Returns `UNKNOWN`; no unjustified hard constraint failure. | "unknown" indicates omitted metadata in job listings, not an explicit contradictory requirement. |
| `a_jent/explainable_matcher.py` | Add `"account executive"` and `"b2b sales"` to `UNRELATED_KEYWORDS` | "Enterprise Account Executive" got $70\%$ role affinity ($42.5$ pts) for tech candidates. | Matches unrelated keywords; receives $5\%$ role affinity ($26.2$ pts). | Standard sales roles must not receive positive technical affinity. |
| `a_jent/explainable_matcher.py` | In `ROLE_TRACKS["data_analytics"]`: add `"business intelligence analyst"`, `"business intelligence"`, `"product analyst"`, `"product growth analyst"` | `job_bi_analyst_12` received fallback $70\%$ role affinity ($92.5$ pts). | Directly aligns with `data_analytics`; receives $100\%$ role affinity ($100.0$ pts). | "BI" is the direct acronym for Business Intelligence. |
| `a_jent/explainable_matcher.py` | In `ROLE_TRACKS["data_science_ml"]`: add `"predictive modeler"`, `"quantitative researcher"` | `job_quant_modeler_06` received fallback $70\%$ role affinity ($82.5$ pts). | Directly aligns with `data_science_ml`; receives $100\%$ role affinity ($90.0$ pts). | Legitimate, established titles in quantitative data science. |
| `a_jent/explainable_matcher.py` | Remove `"developer"` and `"engineer"` from `software_backend`; implement longest-keyword matching in `_evaluate_role_affinity` | "Senior Frontend Developer" matched `"developer"` -> `software_backend`. | Matches `"frontend developer"` -> `frontend`; backend candidates get related family ($85\%$) rather than direct match ($100\%$). | Resolves substring-masking hazard where earlier tracks in iteration shadowed specific titles. |

---

## 5. Rejected Changes and Rationale

1. **REJECTED: Blind Component Weight Re-tuning (e.g. changing 50/25/10/15)**
   - *Rationale:* The 50/25/10/15 breakdown is structurally principled (skills dominate, role provides domain grounding, soft bonuses reward preferred/experience). Sweeping parameters across a 50-pair benchmark would be pure overfitting without a generalizable basis.
2. **REJECTED: Recalibrating Match Tier Thresholds (75 STRONG, 50 MODERATE)**
   - *Rationale:* The tiers represent explanatory bands, not ranking metrics. Candidates scoring $\ge 75$ consistently demonstrate strong required skill coverage; scores between 50-74 represent moderate/adjacent alignment. No interpretability failure was demonstrated.
3. **REJECTED: Hard Constraint Rejection on Hybrid Location Mismatch (`cand_data_analyst_02` vs Frankfurt)**
   - *Rationale:* Candidate is open to hybrid/onsite work in Bangalore without an explicit "no relocation" restriction. Treating different locations as hard failures would violate the core architectural rule: "Hard constraint FAIL requires explicit contradiction; absence of evidence is UNKNOWN."
4. **REJECTED: Ad-hoc Synonym Ingestion for Semantic Language Gaps**
   - *Rationale:* Mapping "statistical estimation algorithms" $\to$ "machine learning" or "quantitative evaluator" $\to$ "data analyst" in `skill_taxonomy.py` would corrupt the taxonomy with non-standard synonyms. These are genuine semantic gaps best suited for semantic modeling, not fragile string substitution.

---

## 6. Post-Calibration Benchmark Results

Independent measurement on `evaluation/matching_pairs.jsonl` after applying justified changes:

| Metric | Baseline | Post-Calibration | Delta |
| :--- | :--- | :--- | :--- |
| **Precision@5** | 0.4800 (12/25) | 0.4400 (11/25) | -0.0400 |
| **Recall@5** | 1.0000 (12/12) | 0.9167 (11/12) | -0.0833 |
| **Precision@10** | 0.2400 (12/50) | 0.2400 (12/50) | 0.0000 |
| **Recall@10** | 1.0000 (12/12) | 1.0000 (12/12) | 0.0000 |
| **Top-5 Overlap Count** | 16 | **17** | +1 |
| **Top-5 Jaccard Similarity** | 0.4881 | **0.5548** | +0.0667 |
| **Large Rank Disagreements ($|\Delta| \ge 5$)** | 9 | **5** | **-4** (44% reduction) |
| **Hard Constraint Fails in Legacy Top-10** | 12 | **8** | -4 |

### Analysis of the Precision@5 / Recall@5 Trade-off
Why did Precision@5 change from $0.4800 \to 0.4400$ and Recall@5 from $1.0000 \to 0.9167$?
- **The Baseline Artifact:** In the baseline, `job_underspecified_08` ("Data Specialist", human label: `BORDERLINE`) was falsely failed by the `employment_type == "unknown"` bug, artificially forcing its score to $0.0$ and ranking it at #10.
- **The Calibrated Reality:** When the evaluator bug was fixed, `job_underspecified_08` correctly received `UNKNOWN` status. Because it required only 1 skill (`sql`), candidate `cand_ds_ml_01` matched it, scoring $92.5$.
- For `cand_ds_ml_01`, TWO borderline jobs with missing information (`job_underspecified_08` and `job_vague_rockstar_07`, both scoring $92.5$) ranked at #3 and #4.
- This placed `job_quant_modeler_06` ($90.0$) at #5 and pushed `job_ml_engineer_02` ($82.5$, partial skill match 3/4) to #6.
- **Reporting Rule:** As explicitly instructed by Section 14 ("Do not hide regressions. If an aggregate metric improves but important HIGH_RELEVANCE cases regress, explicitly report that"), this trade-off is reported transparently. The baseline's $1.0000$ recall was artificially reliant on an evaluator bug. Fixing the bug exposed the true structural challenge: **underspecified jobs with 0 or 1 requirement receive full credit, creating ranking pressure on high-relevance jobs with multiple technical requirements.**

---

## 7. Semantic Gap Assessment

- **Identified Potential Semantic Gap Cases:** 2 benchmark pairs
  1. `cand_ds_ml_01` vs `job_quant_modeler_06` ("Predictive Modeler & Quantitative Researcher")
     - Phraseology: "formulate statistical estimation algorithms", "automated inference pipelines".
     - Status: Deterministic rules successfully raised role affinity to $100\%$ ($90.0$ pts), but cannot bridge deep descriptive semantics without semantic representations.
  2. `cand_data_analyst_02` vs `job_data_mining_research_25` ("Business Quantitative Evaluator")
     - Phraseology: "KPI variance decks", "operational logs", "ad-hoc relational queries".
     - Status: Deterministic matcher retrieved it at Rank 2 ($92.5$ pts) via normalized skill coverage (`sql`, `data analysis`), whereas Legacy TF-IDF completely failed (Rank 8, score $0.0000$).
- **Architectural Conclusion:** The benchmark demonstrates a **small, recurring semantic gap pattern** in specialized and interdisciplinary subfields (e.g. quantitative research vs machine learning). While deterministic matching successfully achieves high recall ($91.7\% - 100\%$) and eliminates false positives, embedding-based representations would be valuable as a secondary semantic similarity reranker to distinguish deep responsibility nuances that syntax cannot capture.
