# A-Jent Matching Systems Benchmark & Evaluation Infrastructure

This directory contains the versioned matching benchmark dataset, schema specification, human labeling guide, and test fixtures for evaluating A-Jent's job matching systems.

---

## 1. Directory Structure

```text
evaluation/
├── benchmark_schema.md      # Official labeling guide, label definitions & taxonomy
├── benchmark_fixtures.py    # Structured candidate profiles & jobs covering Categories A-J
├── matching_pairs.jsonl     # 50 curated candidate/job evaluation records (Schema 1.0)
└── README.md                # Benchmark documentation and workflow guide
```

---

## 2. Benchmark Purpose & Scope

The benchmark is designed to answer a single empirical question:
> **How well do the legacy TF-IDF matcher and the new deterministic explainable matcher rank jobs compared with human judgments?**

### Strict Operational Constraints
- **Pure Measurement:** This benchmark is an offline evaluation tool. It never affects live production ranking, notifications, auto-apply, or job scraping.
- **Genuine Human Judgments:** Relevance labels (`HIGH_RELEVANCE`, `BORDERLINE`, `IRRELEVANT`) must be assigned by human domain reviewers. Generating ground-truth labels using matchers or LLMs is strictly prohibited.
- **No Embeddings or Vector DBs:** Evaluation infrastructure uses Python standard library only to establish baseline deterministic performance before deciding if embeddings are needed.
- **Descriptive Metrics Only:** Benchmark execution reports measured metrics independently for each matcher without declaring an automated "winner".

---

## 3. Benchmark Dataset Summary

The initial reference benchmark suite (`matching_pairs.jsonl`) contains:
- **5 Diverse Candidate Profiles:**
  - `cand_ds_ml_01`: Senior Data Scientist & ML Specialist
  - `cand_data_analyst_02`: Mid-level Business Intelligence & Data Analyst
  - `cand_backend_03`: Senior Backend & Cloud Infrastructure Engineer
  - `cand_frontend_04`: Mid-level Frontend & Web Application Developer
  - `cand_junior_se_05`: Junior / Entry-level Software Engineer (Fresher / Student)
- **25 Representative Job Profiles** covering all 10 evaluation categories:
  - **Category A:** Strong exact matches
  - **Category B:** Partial skill matches
  - **Category C:** Alias & synonym cases (taxonomy normalization)
  - **Category D:** Related role affinities (e.g. Data Science ↔ ML Engineering)
  - **Category E:** Adjacent role affinities (e.g. Data Science ↔ Data Engineering)
  - **Category F:** Clearly unrelated roles (e.g. Software Engineer ↔ Recruiter/Design)
  - **Category G:** Hard constraint conflicts (seniority mismatch, location conflict)
  - **Category H:** Underspecified listings with missing information
  - **Category I:** Vague job descriptions with generic buzzwords
  - **Category J:** Semantic responsibility similarity (distinct vocabulary)
- **50 Candidate/Job Benchmark Pairs:**
  - 12 `HIGH_RELEVANCE`
  - 15 `BORDERLINE`
  - 18 `IRRELEVANT`
  - 5 Unlabeled (baseline control pairs)

---

## 4. How to Run the Benchmark

### Offline Benchmark Execution via Python API
```python
from a_jent.matching_evaluation import run_benchmark
from evaluation.benchmark_fixtures import get_benchmark_candidates, get_benchmark_jobs

candidates = get_benchmark_candidates()
jobs = get_benchmark_jobs()

# Run deterministic benchmark
report = run_benchmark(
    benchmark_pairs="evaluation/matching_pairs.jsonl",
    candidates=candidates,
    jobs=jobs,
)

# Print formatted markdown report
print(report.format_markdown_report())
```

### Dataset Integrity Validation
To verify schema conformity, validate labels, and catch duplicate pairs:
```python
from a_jent.matching_evaluation import validate_benchmark_integrity

stats = validate_benchmark_integrity("evaluation/matching_pairs.jsonl")
print("Benchmark integrity valid:", stats)
```

---

## 5. Metric Semantics

For each candidate, rankings are generated independently by:
1. **Legacy TF-IDF Matcher:** Continuous similarity score (0.0 to 1.0)
2. **Deterministic Explainable Matcher:** Bounded score (0 to 100)

Metrics are computed independently at $K = 5$ and $K = 10$:
- **Precision@K:**
  $$\text{Precision@K} = \frac{\text{HIGH\_RELEVANCE jobs in Top-K}}{\text{actual\_k}}$$
- **Recall@K:**
  $$\text{Recall@K} = \frac{\text{HIGH\_RELEVANCE jobs in Top-K}}{\text{total HIGH\_RELEVANCE jobs in dataset}}$$
- **Top-K Jaccard Similarity:** Measures agreement between legacy and explainable Top-K sets.
- **`BORDERLINE` Handling:** Never counted as relevant; documented separately.
- **Missing Information:** Underspecified attributes remain neutral and are not penalized as `IRRELEVANT`.
