"""
Automated Tests for Task 13: Skill Taxonomy Foundation (a_jent/skill_taxonomy.py)
---------------------------------------------------------------------------------
Verifies all 10 core requirements:
1. Canonical skill remains canonical.
2. Known alias normalizes correctly.
3. Case differences normalize correctly.
4. Whitespace differences normalize correctly.
5. Multiple skills normalize correctly.
6. Unknown skill is not incorrectly mapped and handles preserve_unknown properly.
7. Different skills are not incorrectly treated as aliases (no false equivalence).
8. Taxonomy loads successfully and supports categorization queries.
9. Taxonomy version is available.
10. Duplicate aliases/canonical names are detected or rejected.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent.skill_taxonomy import (
    TAXONOMY_VERSION,
    SkillTaxonomy,
    get_all_categories,
    get_canonical_skills,
    get_skill_category,
    get_skill_entry,
    get_taxonomy_version,
    is_known_skill,
    load_taxonomy,
    normalize_skill,
    normalize_skills,
    validate_taxonomy,
)


class TestSkillTaxonomy(unittest.TestCase):
    # -----------------------------------------------------------------------
    # 1. Canonical skill remains canonical
    # -----------------------------------------------------------------------
    def test_canonical_skill_remains_canonical(self):
        """Canonical skill names normalize to themselves."""
        canonical_samples = [
            "python",
            "javascript",
            "typescript",
            "sql",
            "react",
            "postgresql",
            "docker",
            "kubernetes",
            "machine learning",
            "git",
        ]
        for skill in canonical_samples:
            self.assertEqual(
                normalize_skill(skill),
                skill,
                f"Canonical skill '{skill}' did not normalize to itself.",
            )

    # -----------------------------------------------------------------------
    # 2. Known alias normalizes correctly
    # -----------------------------------------------------------------------
    def test_known_alias_normalizes_correctly(self):
        """Known aliases map deterministically to their canonical forms."""
        test_pairs = [
            ("py", "python"),
            ("python3", "python"),
            ("python 3", "python"),
            ("js", "javascript"),
            ("es6", "javascript"),
            ("ts", "typescript"),
            ("cpp", "c++"),
            ("golang", "go"),
            ("k8s", "kubernetes"),
            ("postgres", "postgresql"),
            ("psql", "postgresql"),
            ("mongo", "mongodb"),
            ("sklearn", "scikit-learn"),
            ("ml", "machine learning"),
            ("ai", "artificial intelligence"),
            ("llm", "large language models"),
            ("amazon web services", "aws"),
            ("google cloud", "gcp"),
            ("cicd", "ci/cd"),
            ("rest", "rest api"),
            ("restful", "rest api"),
        ]
        for alias, expected_canonical in test_pairs:
            self.assertEqual(
                normalize_skill(alias),
                expected_canonical,
                f"Alias '{alias}' did not normalize to '{expected_canonical}'.",
            )

    # -----------------------------------------------------------------------
    # 3. Case differences normalize correctly
    # -----------------------------------------------------------------------
    def test_case_differences_normalize_correctly(self):
        """Normalization is case-insensitive."""
        self.assertEqual(normalize_skill("PYTHON"), "python")
        self.assertEqual(normalize_skill("Python"), "python")
        self.assertEqual(normalize_skill("PyThOn 3"), "python")
        self.assertEqual(normalize_skill("PostgreSQL"), "postgresql")
        self.assertEqual(normalize_skill("K8S"), "kubernetes")
        self.assertEqual(normalize_skill("JavaScript"), "javascript")
        self.assertEqual(normalize_skill("ReAcT"), "react")
        self.assertEqual(normalize_skill("SKLEARN"), "scikit-learn")

    # -----------------------------------------------------------------------
    # 4. Whitespace differences normalize correctly
    # -----------------------------------------------------------------------
    def test_whitespace_differences_normalize_correctly(self):
        """Leading, trailing, and redundant internal whitespace are ignored."""
        self.assertEqual(normalize_skill("   python   "), "python")
        self.assertEqual(normalize_skill("  python   3  "), "python")
        self.assertEqual(normalize_skill("\tpostgresql\n"), "postgresql")
        self.assertEqual(normalize_skill("  machine   learning  "), "machine learning")
        self.assertEqual(normalize_skill("  c   plus   plus  "), "c++")

    # -----------------------------------------------------------------------
    # 5. Multiple skills normalize correctly
    # -----------------------------------------------------------------------
    def test_multiple_skills_normalize_correctly(self):
        """normalize_skills() processes lists, normalizes, and deduplicates while preserving order."""
        skills = ["Python 3", "SQL", "PostgreSQL"]
        self.assertEqual(normalize_skills(skills), ["python", "sql", "postgresql"])

        # Deduplication check
        dup_skills = ["python", "Python 3", "py", "SQL", "sql"]
        self.assertEqual(normalize_skills(dup_skills), ["python", "sql"])

        # Empty / non-string elements filtered safely
        dirty_skills = ["", "  ", "python", None, "k8s"]
        self.assertEqual(normalize_skills(dirty_skills), ["python", "kubernetes"])

    # -----------------------------------------------------------------------
    # 6. Unknown skill is not incorrectly mapped
    # -----------------------------------------------------------------------
    def test_unknown_skill_handling(self):
        """Unknown skills return None by default and do not map to unrelated canonical skills."""
        unknowns = [
            "UnknownSkillXYZ",
            "RandomNonExistentTechnology",
            "Fortran1977Special",
            "CustomInternalFramework",
        ]
        for unk in unknowns:
            # Must NOT map to any existing skill
            self.assertIsNone(
                normalize_skill(unk, preserve_unknown=False),
                f"Unknown skill '{unk}' was unexpectedly mapped.",
            )
            self.assertFalse(is_known_skill(unk))

            # When preserve_unknown=True, returns cleaned string representation
            cleaned = normalize_skill(unk, preserve_unknown=True)
            self.assertEqual(cleaned, unk.strip().lower())

        # List behavior with unknown skills
        mixed = ["Python 3", "UnknownSkillXYZ", "PostgreSQL"]
        self.assertEqual(
            normalize_skills(mixed, preserve_unknown=False),
            ["python", "postgresql"],
        )
        self.assertEqual(
            normalize_skills(mixed, preserve_unknown=True),
            ["python", "unknownskillxyz", "postgresql"],
        )

    # -----------------------------------------------------------------------
    # 7. Different skills are not incorrectly treated as aliases (No false equivalence)
    # -----------------------------------------------------------------------
    def test_no_false_equivalence(self):
        """Technically distinct skills are not mapped to one another."""
        distinct_pairs = [
            ("python", "java"),
            ("sql", "postgresql"),
            ("sql", "mysql"),
            ("aws", "azure"),
            ("aws", "gcp"),
            ("tensorflow", "pytorch"),
            ("react", "next.js"),
            ("git", "github"),
            ("docker", "kubernetes"),
            ("c", "c++"),
            ("c++", "c#"),
            ("javascript", "typescript"),
            ("fastapi", "django"),
            ("flask", "django"),
        ]
        for s1, s2 in distinct_pairs:
            n1 = normalize_skill(s1)
            n2 = normalize_skill(s2)
            self.assertIsNotNone(n1, f"Skill '{s1}' failed to normalize.")
            self.assertIsNotNone(n2, f"Skill '{s2}' failed to normalize.")
            self.assertNotEqual(
                n1,
                n2,
                f"False equivalence detected: '{s1}' and '{s2}' normalized to the same value '{n1}'.",
            )

    # -----------------------------------------------------------------------
    # 8. Taxonomy loads successfully
    # -----------------------------------------------------------------------
    def test_taxonomy_loads_successfully(self):
        """Default taxonomy loads, indexes categories, and retrieves entries."""
        tax = load_taxonomy()
        self.assertIsInstance(tax, SkillTaxonomy)

        categories = get_all_categories()
        expected_categories = {
            "programming_languages",
            "data_science_ml",
            "frameworks_libraries",
            "databases",
            "cloud_devops",
            "tools_platforms",
        }
        self.assertTrue(expected_categories.issubset(set(categories)))

        # Category lookup
        self.assertEqual(get_skill_category("python"), "programming_languages")
        self.assertEqual(get_skill_category("postgres"), "databases")
        self.assertEqual(get_skill_category("k8s"), "cloud_devops")
        self.assertEqual(get_skill_category("pytorch"), "frameworks_libraries")
        self.assertEqual(get_skill_category("deep learning"), "data_science_ml")
        self.assertIsNone(get_skill_category("non_existent_skill"))

        # Entry lookup
        py_entry = get_skill_entry("python 3")
        self.assertIsNotNone(py_entry)
        self.assertEqual(py_entry["canonical"], "python")
        self.assertEqual(py_entry["category"], "programming_languages")
        self.assertIn("py", py_entry["aliases"])

        # Canonical skills filtering by category
        db_skills = get_canonical_skills("databases")
        self.assertIn("postgresql", db_skills)
        self.assertIn("mongodb", db_skills)
        self.assertNotIn("python", db_skills)

    # -----------------------------------------------------------------------
    # 9. Taxonomy version is available
    # -----------------------------------------------------------------------
    def test_taxonomy_version_is_available(self):
        """Taxonomy version string is defined and accessible."""
        self.assertTrue(bool(TAXONOMY_VERSION))
        self.assertEqual(get_taxonomy_version(), TAXONOMY_VERSION)
        self.assertEqual(TAXONOMY_VERSION, "1.0.0")

    # -----------------------------------------------------------------------
    # 10. Duplicate aliases/canonical names are detected or rejected
    # -----------------------------------------------------------------------
    def test_duplicate_and_invalid_taxonomy_detection(self):
        """Validation detects duplicate canonical skills, conflicting aliases, and invalid records."""
        # 1. Duplicate canonical
        dup_canonical = [
            {"canonical": "python", "category": "lang", "aliases": []},
            {"canonical": "python", "category": "lang2", "aliases": []},
        ]
        is_valid, errors = validate_taxonomy(dup_canonical)
        self.assertFalse(is_valid)
        self.assertTrue(any("Duplicate canonical" in e for e in errors))

        # 2. Conflicting alias assigned to two different skills
        conflict_alias = [
            {"canonical": "skill_a", "category": "cat", "aliases": ["shared_alias"]},
            {"canonical": "skill_b", "category": "cat", "aliases": ["shared_alias"]},
        ]
        is_valid, errors = validate_taxonomy(conflict_alias)
        self.assertFalse(is_valid)
        self.assertTrue(any("Duplicate alias" in e for e in errors))

        # 3. Alias colliding with canonical name of another skill
        collide_alias = [
            {"canonical": "sql", "category": "db", "aliases": ["postgres"]},
            {"canonical": "postgres", "category": "db", "aliases": []},
        ]
        is_valid, errors = validate_taxonomy(collide_alias)
        self.assertFalse(is_valid)
        self.assertTrue(any("collides with canonical" in e for e in errors))

        # 4. Strict mode raises ValueError
        with self.assertRaises(ValueError):
            SkillTaxonomy(entries=dup_canonical)


if __name__ == "__main__":
    unittest.main()
