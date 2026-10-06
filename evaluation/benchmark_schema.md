# A-Jent Matching Benchmark Schema & Human Labeling Guide

**Schema Version:** `1.0`  
**Module:** `a_jent.matching_evaluation`  
**Scope:** Controlled evaluation of Legacy TF-IDF vs Deterministic Explainable Matcher

---

## 1. Objective and Guiding Principles

This benchmark exists to collect empirical evidence on matching accuracy between:
1. The legacy TF-IDF lexical matcher (`a_jent.job_matcher`)
2. The deterministic explainable matcher (`a_jent.explainable_matcher`)

The fundamental question being evaluated is:
> **How well do the legacy TF-IDF matcher and the new deterministic explainable matcher rank jobs compared with human judgments?**

### Core Principles
- **Measurement, Not Optimization:** The benchmark measures performance without tuning thresholds, modifying scoring logic, or declaring automated "winners".
- **Human Authenticity:** Relevance labels (`HIGH_RELEVANCE`, `BORDERLINE`, `IRRELEVANT`) must reflect genuine human judgment. They must **never** be generated or inferred by matchers, heuristics, or LLMs.
- **Privacy and Safety:** Benchmark records must never store passwords, API keys, session tokens, raw resume contents, or sensitive personal identifiable information (PII).

---

## 2. Operational Definitions for Human Relevance Labels

Evaluators must assign one of the three supported labels based on practical career relevance:

### `HIGH_RELEVANCE`
- **Definition:** The job is a strong, realistic, and desirable career match for the candidate's demonstrated technical competencies, seniority level, and stated role direction.
- **Criteria:**
  - Candidate satisfies core required skills or industry-standard equivalents.
  - Candidate seniority aligns with the role demands (neither severely underqualified nor grossly overqualified).
  - Explicit candidate constraints (work mode, location, employment type) are satisfied without contradiction.
- **Distinction:** Reflects **practical suitability**, not superficial keyword overlap.

### `BORDERLINE`
- **Definition:** The job exhibits meaningful overlap with the candidate's background, but contains material gaps, ambiguity, or career friction.
- **Examples:**
  - **Adjacent Role:** Candidate is a Data Scientist; job is for a Data Engineer where pipeline infrastructure is the primary focus.
  - **Missing Core Skill:** Candidate meets 3 out of 5 required technologies, but lacks a non-negotiable tool (e.g. AWS or Kubernetes).
  - **Borderline Seniority:** Mid-level candidate evaluated against an early-Senior role.
  - **Ambiguous Requirements:** Vague job description where technical depth cannot be conclusively established.
- **Rule for Missing Information:** When job requirements or candidate details are underspecified, **do not automatically mark as `IRRELEVANT`**. Use `BORDERLINE` and document the ambiguity in `notes`.

### `IRRELEVANT`
- **Definition:** The job is clearly unrelated, functionally incompatible, or explicitly contradictory to the candidate's profile.
- **Examples:**
  - **Domain Mismatch:** Software Engineer evaluated against a Recruiter, Accountant, or Graphic Designer position.
  - **Hard Constraint Incompatibility:** Explicit seniority contradiction (e.g. Junior/Student applying for Staff/Principal 8+ years), work-mode conflict (onsite overseas vs remote-only candidate), or legal restriction (US citizenship requirement for international applicant).
  - **Zero Skill Overlap:** No transferable technical competencies or related role affinity.

---

## 3. Benchmark Evaluation Categories

To expose the strengths, failure modes, and boundaries of both matching architectures, the benchmark dataset incorporates pairs across 10 structured categories:

| Category Code | Category Name | Description & Evaluation Purpose |
| :--- | :--- | :--- |
| **A** | **Strong Exact Matches** | Direct alignment between candidate skills and job requirements (e.g., Python + Pandas + SQL + Scikit-Learn for a Data Scientist). Tests baseline precision. |
| **B** | **Partial Skill Matches** | Candidate satisfies several key requirements but has material skill gaps (e.g., meets Python/FastAPI/AWS, lacks Go/Kafka). Tests proportional soft scoring. |
| **C** | **Alias & Synonym Cases** | Tests taxonomy normalization (e.g., "py" vs "Python", "postgres" vs "PostgreSQL", "k8s" vs "Kubernetes", "sklearn" vs "Scikit-Learn"). |
| **D** | **Related Roles** | Evaluates role affinity between close disciplines (e.g., Data Scientist ↔ ML Engineer, Backend Developer ↔ Software Engineer). |
| **E** | **Adjacent Roles** | Evaluates role affinity across adjacent domains with differing emphasis (e.g., Data Scientist ↔ Data Engineer, ML Engineer ↔ DevOps, Data Analyst ↔ Product Analyst). |
| **F** | **Clearly Unrelated Roles** | Completely disparate professions (e.g., Software Engineer ↔ Graphic Designer, Data Scientist ↔ Talent Acquisition). Tests false-positive suppression. |
| **G** | **Hard Constraint Conflicts** | Explicit eligibility contradictions (seniority gap, onsite location mismatch, employment-type conflict). Evaluates hard constraint evaluation (`FAIL`). |
| **H** | **Underspecified Cases** | Listings with missing requirements, omitted seniority, or unspecified location. Verifies that unknown attributes remain neutral rather than penalized. |
| **I** | **Vague Job Descriptions** | Listings relying on buzzwords ("Web Ninja", "Rockstar Coder") with minimal concrete skill criteria. Tests matcher resilience against low-information text. |
| **J** | **Semantic Responsibility Similarity** | Responsibilities are conceptually aligned but expressed in divergent vocabulary (e.g., "automated inference pipelines and statistical estimation" vs "ML engineering"). Crucial for measuring the need for semantic embeddings. |

---

## 4. Semantic-Gap Classification Taxonomy

Reviewers and analysts may optionally assign an explanatory category in `semantic_gap_category` to categorize why a matcher succeeded or failed:

1. `KEYWORD_OVERLAP_SUFFICIENT`: Standard lexical matching is entirely adequate.
2. `TAXONOMY_NORMALIZATION`: Aliases or acronyms require deterministic synonym normalization.
3. `ROLE_AFFINITY`: Disagreement stems from role family relationships (e.g. Data Science vs Engineering).
4. `HARD_CONSTRAINT`: Hard constraint failure correctly disqualifies a job despite positive keyword overlap.
5. `MISSING_INFORMATION`: Disagreement or uncertainty is caused by absent or underspecified listing metadata.
6. `SEMANTIC_LANGUAGE_GAP`: Meaning is identical or strongly related, but vocabulary differs entirely. **Note:** Different wording alone does not prove embeddings are needed; deterministic rules must be proven insufficient first.
7. `OTHER`: Unique edge case or domain-specific idiosyncrasy.

---

## 5. Dataset Integrity & Record Structure

Each benchmark record in `evaluation/matching_pairs.jsonl` adheres to the following specification:

```json
{
  "schema_version": "1.0",
  "candidate_id": "cand_ds_ml_01",
  "job_id": "job_ds_exact_01",
  "human_label": "HIGH_RELEVANCE",
  "notes": "Direct technical and seniority match across Python, SQL, and ML modeling.",
  "reviewer_id": "rev_human_eval_01",
  "semantic_gap_category": "KEYWORD_OVERLAP_SUFFICIENT"
}
```

### Integrity Rules
1. **Uniqueness:** Every `(candidate_id, job_id)` pair must be unique across the entire dataset. Duplicate pairs trigger a `BenchmarkIntegrityError`.
2. **Consistency:** Conflicting human labels for the same pair are strictly forbidden.
3. **Mandatory Notes for Ambiguity:** All `BORDERLINE` pairs and hard-constraint rejections should include clear notes detailing the reviewer's reasoning.
4. **No Synthesized Ground Truth:** Benchmark labels must be genuine human assessments.
