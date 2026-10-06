"""
Job Matching & Scoring Module
-----------------------------
Extracted from job_search_agent.py (Task 8).

Responsible for:
- Synonym expansion / abbreviation normalization
- TF-IDF vectorization (unigrams + bigrams, English stop words)
- Cosine similarity scoring between resume and job listings
- Top-weighted resume keyword extraction for title boosting
- Score threshold filtering and ranking
"""

import os
import re
import logging
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

log = logging.getLogger("agent")

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
CONFIG_FILE = BASE_DIR / "config.yaml"


# -----------------------------------------------------------------------
# CONFIG LOADER — env var > config.yaml > default
# -----------------------------------------------------------------------
def _load_yaml_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[WARN] Could not load config.yaml in job_matcher: {e}")
        return {}


def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception as e:
        print(f"[WARN] Could not load .env in job_matcher: {e}")


_load_dotenv()
_cfg = _load_yaml_config()


def _get(key: str, default, cast=None):
    """Resolve: env var > config.yaml > default."""
    env_val = os.environ.get(key.upper())
    if env_val is not None:
        val = env_val
    else:
        val = _cfg.get(key.lower(), default)
    if cast and val is not None:
        try:
            return cast(val)
        except Exception:
            return default
    return val


# --- Matching Configuration Constants ---
SIMILARITY_THRESHOLD = _get("SIMILARITY_THRESHOLD", 0.12, float)
TITLE_BOOST_MULTIPLIER = _get("TITLE_BOOST_MULTIPLIER", 1.4, float)


# -----------------------------------------------------------------------
# SYNONYM EXPANSION TABLE
# Expands abbreviations/aliases before TF-IDF so they score correctly.
# -----------------------------------------------------------------------
SYNONYM_MAP = {
    r"\bml\b": "machine learning",
    r"\bai\b": "artificial intelligence",
    r"\bswe\b": "software engineer",
    r"\bsde\b": "software development engineer",
    r"\bfe\b": "frontend",
    r"\bbe\b": "backend",
    r"\bfs\b": "full stack",
    r"\bds\b": "data science",
    r"\bnlp\b": "natural language processing",
    r"\bcv\b": "computer vision",
    r"\bllm\b": "large language model",
    r"\bapi\b": "application programming interface",
    r"\bdb\b": "database",
    r"\bos\b": "operating system",
    r"\bci\b": "continuous integration",
    r"\bcd\b": "continuous deployment",
    r"\bk8s\b": "kubernetes",
    r"\baws\b": "amazon web services",
    r"\bgcp\b": "google cloud platform",
    r"\bjs\b": "javascript",
    r"\bts\b": "typescript",
    r"\bpy\b": "python",
}


def expand_synonyms(text: str) -> str:
    """Expand abbreviations/aliases so TF-IDF matches them correctly."""
    lower = text.lower()
    for pattern, replacement in SYNONYM_MAP.items():
        lower = re.sub(pattern, replacement, lower)
    return lower


# -----------------------------------------------------------------------
# LOCAL AI MATCHING — TF-IDF + cosine similarity + title boost
# -----------------------------------------------------------------------
def rank_by_similarity(
    resume_text: str,
    jobs: list,
    similarity_threshold: float = None,
    title_boost_multiplier: float = None,
) -> list:
    """
    Scores every job's (title + description) against the resume using
    TF-IDF cosine similarity. Applies synonym expansion first so
    abbreviations like "ML" or "SWE" match correctly. Then applies a
    title-boost multiplier if the job title contains a key term from the
    resume profile. Returns sorted, filtered list with 'score' field.
    """
    if not jobs:
        return []

    threshold = similarity_threshold if similarity_threshold is not None else SIMILARITY_THRESHOLD
    multiplier = title_boost_multiplier if title_boost_multiplier is not None else TITLE_BOOST_MULTIPLIER

    expanded_resume = expand_synonyms(resume_text)
    corpus = [expanded_resume] + [
        expand_synonyms(f"{j.get('title', '')} {j.get('description', '')}") for j in jobs
    ]

    vectorizer = TfidfVectorizer(stop_words="english", max_features=25000, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(corpus)
    resume_vec = matrix[0:1]
    job_vecs = matrix[1:]
    sims = cosine_similarity(resume_vec, job_vecs)[0]

    # Extract top-weight terms from resume for title-boost check
    feature_names = vectorizer.get_feature_names_out()
    resume_arr = resume_vec.toarray()[0]
    top_idx = resume_arr.argsort()[-50:][::-1]
    resume_keywords = set(feature_names[i] for i in top_idx if resume_arr[i] > 0)

    scored = []
    for job, score in zip(jobs, sims):
        title_lower = expand_synonyms(job.get("title", ""))
        # Title boost: if any top resume keyword appears in the job title
        if any(kw in title_lower for kw in resume_keywords):
            score = min(score * multiplier, 1.0)
        job["score"] = round(float(score), 4)
        scored.append(job)

    scored = [j for j in scored if j["score"] >= threshold]
    scored.sort(key=lambda j: j["score"], reverse=True)
    return scored
