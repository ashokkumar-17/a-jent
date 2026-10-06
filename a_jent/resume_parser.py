"""
Resume Parser Module
--------------------
Extracted from job_search_agent.py (Task 9).

Responsible for:
- Resume path configuration
- Extraction of text from candidate resume files (.pdf, .docx)
- Fallback keyword profile management when resume is unavailable
"""

import os
import sys
import logging
from pathlib import Path

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
        print(f"[WARN] Could not load config.yaml in resume_parser: {e}")
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
        print(f"[WARN] Could not load .env in resume_parser: {e}")


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


# --- Resume Path Configuration ---
RESUME_PATH = str(_get("RESUME_PATH", str(BASE_DIR / "resume.pdf")))


# --- Fallback Keyword Profile ---
FALLBACK_KEYWORDS_TEXT = (
    # Core roles
    "software engineer intern software engineering intern data science intern "
    "machine learning intern backend developer frontend developer full stack developer "
    "python developer javascript developer react developer node developer "
    "devops intern cloud intern data engineer intern data analyst intern "
    "computer science intern web developer intern product intern research intern "
    "entry level junior new grad graduate fresher trainee "
    # Skills
    "python javascript typescript react nextjs nodejs express fastapi django flask "
    "sql postgresql mysql mongodb redis docker kubernetes git github linux "
    "machine learning deep learning tensorflow pytorch scikit-learn pandas numpy "
    "api rest graphql microservices ci cd aws gcp azure cloud "
    "data structures algorithms system design object oriented programming "
    # India-specific
    "bangalore mumbai delhi hyderabad pune chennai india remote work from home "
    "internship stipend 6 months 3 months summer internship winter internship "
    "b.tech btech mtech msc bsc computer science engineering information technology "
    # Certifications / buzzwords
    "open source contribution competitive programming problem solving agile scrum "
    "communication teamwork analytical skills research publication ieee acm "
)


# -----------------------------------------------------------------------
# RESUME TEXT EXTRACTION
# -----------------------------------------------------------------------
def extract_resume_text(path: str) -> str:
    """Extract raw text from PDF or DOCX file.
    Returns empty string if file does not exist, format is unsupported, or parsing fails.
    """
    if not path or not os.path.exists(path):
        return ""
    ext = path.lower().rsplit(".", 1)[-1]
    try:
        if ext == "pdf":
            import pdfplumber
            text_parts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or "")
            return "\n".join(text_parts)
        elif ext == "docx":
            import docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)
        else:
            log.warning(f"Unsupported resume format: .{ext} — use .pdf or .docx")
            return ""
    except Exception as e:
        log.warning(f"Could not parse resume ({path}): {e}")
        return ""


def get_resume_text(resume_path: str = None) -> str:
    """Load text from configured resume path or fall back to keyword profile."""
    path = resume_path if resume_path is not None else RESUME_PATH
    text = extract_resume_text(path)
    if text.strip():
        log.info(f"Loaded resume: {len(text)} chars from {path}")
        return text
    log.info("No resume found/parsed — using fallback keyword profile.")
    return FALLBACK_KEYWORDS_TEXT
