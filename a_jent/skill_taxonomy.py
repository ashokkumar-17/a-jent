"""
Skill Taxonomy Foundation Module
--------------------------------
Deterministic canonical skill normalization for A-Jent.

Provides:
- Canonical skill definitions and verified aliases
- Categorized skill taxonomy (programming languages, ML/data science, databases, etc.)
- Deterministic, case-insensitive, whitespace-tolerant normalization API
- Safe unknown-skill handling without false equivalence
"""

from typing import Iterable, Optional

TAXONOMY_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# DEFAULT TAXONOMY ENTRIES
# Curated based on A-Jent's target technical domains and active job sources.
# ---------------------------------------------------------------------------
DEFAULT_TAXONOMY: list[dict] = [
    # -----------------------------------------------------------------------
    # 1. Programming Languages
    # -----------------------------------------------------------------------
    {
        "canonical": "python",
        "category": "programming_languages",
        "aliases": ["py", "python3", "python 3", "python 3.x", "python2"],
    },
    {
        "canonical": "javascript",
        "category": "programming_languages",
        "aliases": ["js", "ecmascript", "es6", "vanilla js"],
    },
    {
        "canonical": "typescript",
        "category": "programming_languages",
        "aliases": ["ts"],
    },
    {
        "canonical": "java",
        "category": "programming_languages",
        "aliases": ["java 8", "java 11", "java 17", "java 21", "core java"],
    },
    {
        "canonical": "c++",
        "category": "programming_languages",
        "aliases": ["cpp", "c plus plus"],
    },
    {
        "canonical": "c",
        "category": "programming_languages",
        "aliases": ["c lang", "c language"],
    },
    {
        "canonical": "c#",
        "category": "programming_languages",
        "aliases": ["csharp", "c sharp", "c#.net"],
    },
    {
        "canonical": "go",
        "category": "programming_languages",
        "aliases": ["golang"],
    },
    {
        "canonical": "rust",
        "category": "programming_languages",
        "aliases": ["rustlang"],
    },
    {
        "canonical": "sql",
        "category": "programming_languages",
        "aliases": ["structured query language"],
    },
    {
        "canonical": "html",
        "category": "programming_languages",
        "aliases": ["html5"],
    },
    {
        "canonical": "css",
        "category": "programming_languages",
        "aliases": ["css3"],
    },
    {
        "canonical": "bash",
        "category": "programming_languages",
        "aliases": ["shell", "shell script", "shell scripting", "bash script"],
    },

    # -----------------------------------------------------------------------
    # 2. Data Science & Machine Learning
    # -----------------------------------------------------------------------
    {
        "canonical": "machine learning",
        "category": "data_science_ml",
        "aliases": ["ml"],
    },
    {
        "canonical": "artificial intelligence",
        "category": "data_science_ml",
        "aliases": ["ai"],
    },
    {
        "canonical": "deep learning",
        "category": "data_science_ml",
        "aliases": ["dl"],
    },
    {
        "canonical": "natural language processing",
        "category": "data_science_ml",
        "aliases": ["nlp"],
    },
    {
        "canonical": "computer vision",
        "category": "data_science_ml",
        "aliases": ["cv"],
    },
    {
        "canonical": "large language models",
        "category": "data_science_ml",
        "aliases": ["llm", "llms", "large language model"],
    },
    {
        "canonical": "data science",
        "category": "data_science_ml",
        "aliases": ["ds"],
    },
    {
        "canonical": "data analysis",
        "category": "data_science_ml",
        "aliases": ["data analytics"],
    },
    {
        "canonical": "statistics",
        "category": "data_science_ml",
        "aliases": ["statistical analysis"],
    },

    # -----------------------------------------------------------------------
    # 3. Frameworks & Libraries
    # -----------------------------------------------------------------------
    {
        "canonical": "pytorch",
        "category": "frameworks_libraries",
        "aliases": ["torch"],
    },
    {
        "canonical": "tensorflow",
        "category": "frameworks_libraries",
        "aliases": ["tf"],
    },
    {
        "canonical": "scikit-learn",
        "category": "frameworks_libraries",
        "aliases": ["sklearn", "scikit learn"],
    },
    {
        "canonical": "pandas",
        "category": "frameworks_libraries",
        "aliases": [],
    },
    {
        "canonical": "numpy",
        "category": "frameworks_libraries",
        "aliases": [],
    },
    {
        "canonical": "react",
        "category": "frameworks_libraries",
        "aliases": ["reactjs", "react.js"],
    },
    {
        "canonical": "next.js",
        "category": "frameworks_libraries",
        "aliases": ["nextjs", "next"],
    },
    {
        "canonical": "fastapi",
        "category": "frameworks_libraries",
        "aliases": [],
    },
    {
        "canonical": "django",
        "category": "frameworks_libraries",
        "aliases": [],
    },
    {
        "canonical": "flask",
        "category": "frameworks_libraries",
        "aliases": [],
    },
    {
        "canonical": "express",
        "category": "frameworks_libraries",
        "aliases": ["expressjs", "express.js"],
    },
    {
        "canonical": "node.js",
        "category": "frameworks_libraries",
        "aliases": ["nodejs", "node"],
    },

    # -----------------------------------------------------------------------
    # 4. Databases
    # -----------------------------------------------------------------------
    {
        "canonical": "postgresql",
        "category": "databases",
        "aliases": ["postgres", "psql"],
    },
    {
        "canonical": "mysql",
        "category": "databases",
        "aliases": [],
    },
    {
        "canonical": "mongodb",
        "category": "databases",
        "aliases": ["mongo"],
    },
    {
        "canonical": "redis",
        "category": "databases",
        "aliases": [],
    },
    {
        "canonical": "sqlite",
        "category": "databases",
        "aliases": ["sqlite3"],
    },

    # -----------------------------------------------------------------------
    # 5. Cloud & DevOps
    # -----------------------------------------------------------------------
    {
        "canonical": "aws",
        "category": "cloud_devops",
        "aliases": ["amazon web services"],
    },
    {
        "canonical": "gcp",
        "category": "cloud_devops",
        "aliases": ["google cloud", "google cloud platform"],
    },
    {
        "canonical": "azure",
        "category": "cloud_devops",
        "aliases": ["microsoft azure"],
    },
    {
        "canonical": "docker",
        "category": "cloud_devops",
        "aliases": ["docker container", "docker containers"],
    },
    {
        "canonical": "kubernetes",
        "category": "cloud_devops",
        "aliases": ["k8s"],
    },
    {
        "canonical": "ci/cd",
        "category": "cloud_devops",
        "aliases": ["cicd", "continuous integration", "continuous deployment", "ci cd"],
    },
    {
        "canonical": "linux",
        "category": "cloud_devops",
        "aliases": ["gnu/linux"],
    },

    # -----------------------------------------------------------------------
    # 6. Tools, Protocols & Architecture
    # -----------------------------------------------------------------------
    {
        "canonical": "git",
        "category": "tools_platforms",
        "aliases": [],
    },
    {
        "canonical": "github",
        "category": "tools_platforms",
        "aliases": [],
    },
    {
        "canonical": "postman",
        "category": "tools_platforms",
        "aliases": [],
    },
    {
        "canonical": "rest api",
        "category": "tools_platforms",
        "aliases": ["rest", "restful", "restful api", "rest apis"],
    },
    {
        "canonical": "graphql",
        "category": "tools_platforms",
        "aliases": [],
    },
    {
        "canonical": "microservices",
        "category": "tools_platforms",
        "aliases": ["microservice"],
    },
]


def _clean_string(s: str) -> str:
    """Standardize string by stripping surrounding whitespace and lowercasing."""
    if not isinstance(s, str):
        return ""
    # Collapse multiple interior spaces to a single space
    return " ".join(s.strip().lower().split())


def validate_taxonomy(entries: list[dict], strict: bool = False) -> tuple[bool, list[str]]:
    """Validate taxonomy entries for structural integrity and uniqueness.

    Checks:
    - Required fields ('canonical', 'category', 'aliases') present.
    - Canonical names are unique (case-insensitively).
    - Aliases do not duplicate other aliases or collide with canonical names
      of different skills.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors: list[str] = []
    canonical_seen: dict[str, dict] = {}
    alias_to_canonical: dict[str, str] = {}

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"Entry at index {idx} is not a dictionary.")
            continue

        raw_canonical = entry.get("canonical")
        category = entry.get("category")
        aliases = entry.get("aliases")

        if not raw_canonical or not isinstance(raw_canonical, str) or not raw_canonical.strip():
            errors.append(f"Entry at index {idx} has missing or invalid 'canonical' name.")
            continue

        canonical = _clean_string(raw_canonical)

        if not category or not isinstance(category, str) or not category.strip():
            errors.append(f"Skill '{canonical}' has missing or invalid 'category'.")

        if not isinstance(aliases, list):
            errors.append(f"Skill '{canonical}' aliases must be a list.")
            continue

        # Check for duplicate canonical names
        if canonical in canonical_seen:
            errors.append(f"Duplicate canonical skill '{canonical}' found.")
        else:
            canonical_seen[canonical] = entry

        # Check self-alias (canonical should not be listed as its own alias)
        # Check alias uniqueness
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                errors.append(f"Skill '{canonical}' has empty or non-string alias.")
                continue

            cleaned_alias = _clean_string(alias)
            if cleaned_alias == canonical:
                errors.append(f"Skill '{canonical}' lists itself in its aliases.")
                continue

            if cleaned_alias in alias_to_canonical:
                prev_canonical = alias_to_canonical[cleaned_alias]
                errors.append(
                    f"Duplicate alias '{cleaned_alias}' for '{canonical}' (already assigned to '{prev_canonical}')."
                )
            else:
                alias_to_canonical[cleaned_alias] = canonical

    # Check for alias collision with another skill's canonical name
    for alias, canonical in alias_to_canonical.items():
        if alias in canonical_seen and alias != canonical:
            errors.append(
                f"Alias '{alias}' for skill '{canonical}' collides with canonical skill '{alias}'."
            )

    is_valid = len(errors) == 0
    if strict and not is_valid:
        raise ValueError(f"Taxonomy validation failed with {len(errors)} error(s): {'; '.join(errors)}")
    return is_valid, errors


class SkillTaxonomy:
    """Deterministic, indexed skill taxonomy."""

    def __init__(self, entries: Optional[list[dict]] = None, version: str = TAXONOMY_VERSION):
        self.version = version
        raw_entries = entries if entries is not None else DEFAULT_TAXONOMY
        validate_taxonomy(raw_entries, strict=True)
        self.entries = raw_entries
        self._alias_to_canonical: dict[str, str] = {}
        self._canonical_to_entry: dict[str, dict] = {}
        self._categories: set[str] = set()

        self._build_index()

    def _build_index(self) -> None:
        for entry in self.entries:
            canonical = _clean_string(entry["canonical"])
            category = entry.get("category", "")
            self._canonical_to_entry[canonical] = entry
            self._alias_to_canonical[canonical] = canonical
            self._categories.add(category)

            for alias in entry.get("aliases", []):
                cleaned_alias = _clean_string(alias)
                if cleaned_alias:
                    self._alias_to_canonical[cleaned_alias] = canonical

    def normalize(self, skill: str, preserve_unknown: bool = False) -> Optional[str]:
        """Normalize a skill string to its canonical taxonomy name.

        Args:
            skill: Raw skill string (e.g. 'Python 3', 'k8s', 'POSTGRES').
            preserve_unknown: If True, returns cleaned raw string when unknown.
                              If False, returns None when unknown.

        Returns:
            Canonical skill name or None/cleaned string.
        """
        if skill is None or not isinstance(skill, str):
            return None
        cleaned = _clean_string(skill)
        if not cleaned:
            return None

        canonical = self._alias_to_canonical.get(cleaned)
        if canonical is not None:
            return canonical

        if preserve_unknown:
            return cleaned
        return None

    def normalize_many(
        self, skills: Iterable[str], preserve_unknown: bool = False
    ) -> list[str]:
        """Normalize a collection of skill strings, deduplicating while preserving order.

        Args:
            skills: Iterable of raw skill strings.
            preserve_unknown: Whether to retain unknown skills in cleaned form.

        Returns:
            List of normalized skills.
        """
        if not skills:
            return []
        seen = set()
        result: list[str] = []
        for raw in skills:
            normalized = self.normalize(raw, preserve_unknown=preserve_unknown)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def get_entry(self, skill: str) -> Optional[dict]:
        """Retrieve full taxonomy entry for a canonical skill or alias."""
        canonical = self.normalize(skill, preserve_unknown=False)
        if canonical:
            return self._canonical_to_entry.get(canonical)
        return None

    def get_category(self, skill: str) -> Optional[str]:
        """Retrieve category for a skill."""
        entry = self.get_entry(skill)
        return entry.get("category") if entry else None

    def is_known(self, skill: str) -> bool:
        """Check if a skill is in the taxonomy (either canonical or alias)."""
        return self.normalize(skill, preserve_unknown=False) is not None

    def get_canonical_skills(self, category: Optional[str] = None) -> list[str]:
        """Return sorted list of all canonical skills, optionally filtered by category."""
        if category:
            return sorted(
                c for c, e in self._canonical_to_entry.items() if e.get("category") == category
            )
        return sorted(self._canonical_to_entry.keys())

    def get_categories(self) -> list[str]:
        """Return sorted list of all taxonomy categories."""
        return sorted(self._categories)


# ---------------------------------------------------------------------------
# GLOBAL SINGLETON INSTANCE & CONVENIENCE FUNCTIONS
# ---------------------------------------------------------------------------
_DEFAULT_INSTANCE = SkillTaxonomy(DEFAULT_TAXONOMY, version=TAXONOMY_VERSION)


def normalize_skill(skill: str, preserve_unknown: bool = False) -> Optional[str]:
    """Normalize a skill string to its canonical taxonomy name."""
    return _DEFAULT_INSTANCE.normalize(skill, preserve_unknown=preserve_unknown)


def normalize_skills(
    skills: Iterable[str], preserve_unknown: bool = False
) -> list[str]:
    """Normalize and deduplicate an iterable of skill strings."""
    return _DEFAULT_INSTANCE.normalize_many(skills, preserve_unknown=preserve_unknown)


def get_skill_entry(skill: str) -> Optional[dict]:
    """Get full taxonomy dict for a skill."""
    return _DEFAULT_INSTANCE.get_entry(skill)


def get_skill_category(skill: str) -> Optional[str]:
    """Get category for a skill."""
    return _DEFAULT_INSTANCE.get_category(skill)


def is_known_skill(skill: str) -> bool:
    """Return True if skill exists in taxonomy."""
    return _DEFAULT_INSTANCE.is_known(skill)


def get_canonical_skills(category: Optional[str] = None) -> list[str]:
    """Return sorted list of canonical skill names."""
    return _DEFAULT_INSTANCE.get_canonical_skills(category=category)


def get_all_categories() -> list[str]:
    """Return sorted list of all categories."""
    return _DEFAULT_INSTANCE.get_categories()


def get_taxonomy_version() -> str:
    """Return current taxonomy version string."""
    return _DEFAULT_INSTANCE.version


def load_taxonomy(entries: Optional[list[dict]] = None) -> SkillTaxonomy:
    """Create and return a new SkillTaxonomy instance."""
    return SkillTaxonomy(entries=entries)
