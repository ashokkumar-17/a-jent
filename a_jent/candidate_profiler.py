"""
Candidate Profiler Module
-------------------------
Converts raw resume text into a deterministic, structured CandidateProfile.

Extracts:
- Recognized technical skills (normalized via a_jent.skill_taxonomy)
- Unknown skills (preserved without false canonical mapping)
- Explicit seniority (student, intern, entry_level, junior, mid_level, senior, lead)
- Explicit years of professional experience
- Explicit graduation year
- Explicit location preferences
- Explicit work-mode preference (remote, hybrid, onsite)
- Explicit employment preferences (internship, full_time, part_time, contract)

Guarantees:
- Deterministic: same text -> identical profile
- No guessing or hallucination: missing information remains None / empty
- False-positive safeguards with word boundaries and contextual filtering
- Standalone: does NOT modify the existing TF-IDF matching pipeline
"""

from dataclasses import dataclass, field
import re
from typing import Any, Optional

from a_jent import skill_taxonomy

# ---------------------------------------------------------------------------
# STRUCTURED PROFILE
# ---------------------------------------------------------------------------
@dataclass
class CandidateProfile:
    """Structured candidate information extracted deterministically from resume text."""

    raw_skills: list[str] = field(default_factory=list)
    normalized_skills: list[str] = field(default_factory=list)
    unknown_skills: list[str] = field(default_factory=list)
    seniority: Optional[str] = None
    experience_years: Optional[float] = None
    graduation_year: Optional[int] = None
    current_location: Optional[str] = None
    preferred_locations: list[str] = field(default_factory=list)
    work_mode: Optional[str] = None
    employment_preferences: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize profile to standard dictionary representation."""
        return {
            "raw_skills": list(self.raw_skills),
            "normalized_skills": list(self.normalized_skills),
            "unknown_skills": list(self.unknown_skills),
            "seniority": self.seniority,
            "experience_years": self.experience_years,
            "graduation_year": self.graduation_year,
            "current_location": self.current_location,
            "preferred_locations": list(self.preferred_locations),
            "work_mode": self.work_mode,
            "employment_preferences": list(self.employment_preferences),
            "evidence": dict(self.evidence),
            "confidence": dict(self.confidence),
        }


# ---------------------------------------------------------------------------
# KNOWN TARGET LOCATIONS FOR PREFERENCE PARSING
# ---------------------------------------------------------------------------
KNOWN_LOCATIONS = [
    "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi",
    "chennai", "noida", "gurgaon", "gurugram", "kolkata", "ahmedabad",
    "kochi", "coimbatore", "chandigarh", "jaipur", "remote", "india",
]


# ---------------------------------------------------------------------------
# SKILL EXTRACTION HELPERS & COMPILED PATTERNS
# ---------------------------------------------------------------------------
# Special skills that require custom boundary handling (symbols or high-collision words)
SPECIAL_SKILL_PATTERNS = [
    (r"(?i)(?:(?<=\s)|^|(?<=[,;(]))c\+\+(?=[,\s\.;\)]|$)", "c++"),
    (r"(?i)(?:(?<=\s)|^|(?<=[,;(]))c#(?=[,\s\.;\)]|$)", "c#"),
    (r"(?i)\bjava\b(?!\s*script\b)", "java"),
    (r"(?i)\breact\b(?!\s*native\b)", "react"),
    (r"(?i)\b(?:next\.js|nextjs)\b", "next.js"),
    (r"(?i)\b(?:node\.js|nodejs)\b", "node.js"),
    (r"(?i)\b(?:ci\/cd|cicd|ci cd)\b", "ci/cd"),
]


def _extract_skills(text: str) -> tuple[list[str], list[str], list[str], Optional[str]]:
    """Extract and normalize skills using a_jent.skill_taxonomy with false-positive safeguards.

    Returns:
        (raw_skills, normalized_skills, unknown_skills, evidence_snippet)
    """
    raw_found: list[str] = []
    normalized_set: set[str] = set()
    normalized_list: list[str] = []
    unknown_list: list[str] = []
    evidence_parts: list[str] = []

    # 1. First check explicit "SKILLS" or "LANGUAGES" section if present
    skills_section_match = re.search(
        r"(?i)(?:technical\s+skills|programming\s+languages|skills\s*(?:&|and)\s*tools|core\s+competencies|languages\s*(?:&|and)\s*technologies|languages|skills)\s*[:\-\n](.+?)(?=(?:\n\s*[A-Z\s]{4,}|\Z))",
        text,
        re.DOTALL,
    )

    section_text = skills_section_match.group(1) if skills_section_match else ""

    # 2. Check special skills first
    for pattern, canonical_target in SPECIAL_SKILL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            raw_match = match.group(0).strip()
            raw_found.append(raw_match)
            if canonical_target not in normalized_set:
                normalized_set.add(canonical_target)
                normalized_list.append(canonical_target)
                evidence_parts.append(raw_match)

    # 3. Match against taxonomy entries
    all_canonicals = skill_taxonomy.get_canonical_skills()
    for canonical in all_canonicals:
        if canonical in normalized_set:
            continue
        entry = skill_taxonomy.get_skill_entry(canonical)
        if not entry:
            continue

        aliases = entry.get("aliases", [])
        candidates = [canonical] + aliases

        for candidate in candidates:
            # Skip special candidates already handled
            if candidate in ("c++", "c#", "java", "react", "next.js", "node.js", "ci/cd"):
                continue

            # Skip single-letter "c" unless in explicit skills section or "c language"
            if candidate == "c":
                if re.search(r"(?i)\b(?:c\s+lang(?:uage)?)\b", text):
                    raw_found.append("c language")
                    normalized_set.add(canonical)
                    normalized_list.append(canonical)
                    evidence_parts.append("c language")
                    break
                elif section_text and re.search(r"(?i)(?:(?<=\s)|^|(?<=[,;(]))c(?=[,\s\.;\)]|$)(?!\+\+|#)", section_text):
                    raw_found.append("c")
                    normalized_set.add(canonical)
                    normalized_list.append(canonical)
                    evidence_parts.append("c")
                    break
                continue

            # Skip generic "go" word in prose unless "golang" or in explicit skills section
            if candidate == "go":
                if re.search(r"(?i)\bgolang\b", text):
                    raw_found.append("golang")
                    normalized_set.add(canonical)
                    normalized_list.append(canonical)
                    evidence_parts.append("golang")
                    break
                elif section_text and re.search(r"(?i)\bgo\b", section_text):
                    raw_found.append("go")
                    normalized_set.add(canonical)
                    normalized_list.append(canonical)
                    evidence_parts.append("go")
                    break
                continue

            # Standard boundary match for skill
            escaped = re.escape(candidate)
            # Allow multiple interior whitespace
            pattern_str = r"(?i)\b" + re.sub(r"\\\s+", r"\\s+", escaped) + r"\b"
            match = re.search(pattern_str, text)
            if match:
                raw_match = match.group(0).strip()
                raw_found.append(raw_match)
                normalized = skill_taxonomy.normalize_skill(raw_match)
                if normalized and normalized not in normalized_set:
                    normalized_set.add(normalized)
                    normalized_list.append(normalized)
                    evidence_parts.append(raw_match)
                break

    # 4. If explicit skills section exists, scan for unmapped/unknown items
    if section_text:
        # Split section items by commas, newlines, pipes, bullets
        tokens = re.split(r"[,|\n•·\t\r/]+", section_text)
        for tok in tokens:
            cleaned = tok.strip()
            # Must look like an isolated skill (1-3 words, no full sentences)
            if cleaned and len(cleaned.split()) <= 3 and len(cleaned) <= 30:
                if not re.search(r"(?i)\b(?:technologies|tools|languages|frameworks|libraries|databases|proficiencies)\b", cleaned):
                    if not skill_taxonomy.is_known_skill(cleaned):
                        clean_lower = cleaned.lower()
                        if clean_lower not in unknown_list and clean_lower not in normalized_set:
                            unknown_list.append(clean_lower)

    evidence = ", ".join(evidence_parts[:10]) if evidence_parts else None
    return raw_found, normalized_list, unknown_list, evidence


# ---------------------------------------------------------------------------
# SENIORITY EXTRACTION
# ---------------------------------------------------------------------------
SENIORITY_PATTERNS = [
    # Senior / Lead
    (r"(?i)\b(?:tech\s+lead|team\s+lead|lead\s+developer|lead\s+engineer|principal\s+engineer)\b", "lead"),
    (r"(?i)\b(?:senior|sr\.?)\s+(?:software|developer|engineer|data|scientist|analyst|architect)\b", "senior"),
    # Mid-level
    (r"(?i)\bmid[- ]level\s+(?:software|developer|engineer)\b", "mid_level"),
    # Junior / Entry-Level / Fresher
    (r"(?i)\b(?:junior|jr\.?)\s+(?:software|developer|engineer|data|analyst)\b", "junior"),
    (r"(?i)\b(?:fresher|fresh\s+graduate|entry[- ]level|new\s+grad|new\s+graduate|recent\s+graduate)\b", "entry_level"),
    # Intern
    (r"(?i)\b(?:currently\s+working\s+as\s+an?|seeking\s+an?|working\s+as\s+an?)\s+intern\b", "intern"),
    (r"(?i)\b(?:data\s+science|software\s+engineering|software\s+developer|machine\s+learning|frontend|backend|full\s*stack|devops|research)\s+intern\b", "intern"),
    (r"(?i)\binternship\s+trainee\b", "intern"),
    # Student
    (r"(?i)\b(?:final[- ]year|pre[- ]final[- ]year|\d(?:st|nd|rd|th)[- ]year|undergraduate|postgraduate)\b.*?\bstudent\b", "student"),
    (r"(?i)\b(?:b\.?tech|m\.?tech|bca|mca|b\.?sc|m\.?sc|b\.?e\.?|college|university)\s+student\b", "student"),
    (r"(?i)\bstudent\s+at\b", "student"),
]


def _extract_seniority(text: str) -> tuple[Optional[str], Optional[str], str]:
    """Extract explicit seniority level and evidence snippet."""
    for pattern, seniority_val in SENIORITY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return seniority_val, match.group(0).strip(), "HIGH"
    return None, None, "LOW"


# ---------------------------------------------------------------------------
# EXPERIENCE EXTRACTION
# ---------------------------------------------------------------------------
EXP_PATTERNS = [
    r"(?i)\b(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:professional\s+|relevant\s+|industry\s+|work\s+|total\s+)?experience\b",
    r"(?i)\b(?:overall|total)?\s*experience\s*[:\-]\s*(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\b",
]


def _extract_experience(text: str) -> tuple[Optional[float], Optional[str], str]:
    """Extract explicit professional experience in years."""
    for pattern in EXP_PATTERNS:
        match = re.search(pattern, text)
        if match:
            try:
                years = float(match.group(1))
                return years, match.group(0).strip(), "HIGH"
            except (ValueError, IndexError):
                continue
    return None, None, "LOW"


# ---------------------------------------------------------------------------
# GRADUATION YEAR EXTRACTION
# ---------------------------------------------------------------------------
GRAD_PATTERNS = [
    r"(?i)\b(?:expected\s+graduation|graduation\s+year|year\s+of\s+graduation|graduating(?:\s+in)?|class\s+of)\s*[:\-]?\s*(20\d{2})\b",
    r"(?i)\b(?:b\.?tech|m\.?tech|bca|mca|b\.?sc|m\.?sc|b\.?e\.?|bachelor|master|degree)[^,\n\r]*?[,\s]\s*20\d{2}\s*[-–—to]+\s*(20\d{2})\b",
    r"(?i)\b(?:passout|passing\s+year|batch\s+of)\s*[:\-]?\s*(20\d{2})\b",
]


def _extract_graduation_year(text: str) -> tuple[Optional[int], Optional[str], str]:
    """Extract explicit graduation year."""
    for pattern in GRAD_PATTERNS:
        match = re.search(pattern, text)
        if match:
            try:
                year = int(match.group(1))
                if 2010 <= year <= 2035:
                    return year, match.group(0).strip(), "HIGH"
            except (ValueError, IndexError):
                continue
    return None, None, "LOW"


# ---------------------------------------------------------------------------
# LOCATION & PREFERENCES EXTRACTION
# ---------------------------------------------------------------------------
def _extract_locations(text: str) -> tuple[Optional[str], list[str], Optional[str], str]:
    """Extract explicit current location and preferred locations."""
    current_loc = None
    pref_locs: list[str] = []
    evidence_parts: list[str] = []

    # Current location check (header / contact line)
    curr_match = re.search(
        r"(?i)\b(?:current\s+location|location|residence|based\s+in)\s*[:\-]\s*([A-Za-z\s,]+?)(?=(?:\n|\r|\s{3,}|$))",
        text,
    )
    if curr_match:
        loc_str = curr_match.group(1).strip()
        # Ensure it matches a known location
        for loc in KNOWN_LOCATIONS:
            if re.search(r"(?i)\b" + re.escape(loc) + r"\b", loc_str):
                current_loc = loc
                evidence_parts.append(curr_match.group(0).strip())
                break

    # Preferred locations check
    pref_match = re.search(
        r"(?i)\b(?:preferred\s+locations?|location\s+preferences?|preferred\s+cities|open\s+to\s+relocate\s+to|willing\s+to\s+relocate\s+to|preferred\s+work\s+locations?)\s*[:\-]\s*([^\n\r]+)",
        text,
    )
    if pref_match:
        matched_text = pref_match.group(1)
        evidence_parts.append(pref_match.group(0).strip())
        for loc in KNOWN_LOCATIONS:
            if re.search(r"(?i)\b" + re.escape(loc) + r"\b", matched_text):
                if loc not in pref_locs:
                    pref_locs.append(loc)

    evidence = "; ".join(evidence_parts) if evidence_parts else None
    conf = "HIGH" if (current_loc or pref_locs) else "LOW"
    return current_loc, pref_locs, evidence, conf


# ---------------------------------------------------------------------------
# WORK MODE PREFERENCE EXTRACTION
# ---------------------------------------------------------------------------
WORK_MODE_PATTERNS = [
    # Remote
    (r"(?i)\b(?:open\s+to|preference\s+for|preferred\s+work\s+mode|seeking|looking\s+for|interested\s+in|available\s+for)\s+(?:only\s+)?remote(?:\s+roles|\s+work|\s+opportunities|\s+positions|\s+jobs)?\b", "remote"),
    (r"(?i)\b(?:work\s+mode|workplace\s+preference|job\s+type)\s*[:\-]\s*remote\b", "remote"),
    (r"(?i)\bprefer(?:s|red)?\s+remote\b", "remote"),
    # Hybrid
    (r"(?i)\b(?:work\s+mode|workplace\s+preference)\s*[:\-]\s*hybrid\b", "hybrid"),
    (r"(?i)\b(?:open\s+to|prefer(?:s|red)?|seeking)\s+hybrid(?:\s+roles|\s+work|\s+opportunities)?\b", "hybrid"),
    # Onsite
    (r"(?i)\b(?:work\s+mode|workplace\s+preference)\s*[:\-]\s*(?:onsite|on[- ]site|in[- ]office)\b", "onsite"),
    (r"(?i)\b(?:open\s+to|prefer(?:s|red)?|seeking)\s+(?:onsite|on[- ]site|in[- ]office)(?:\s+roles|\s+work|\s+opportunities)?\b", "onsite"),
]


def _extract_work_mode(text: str) -> tuple[Optional[str], Optional[str], str]:
    """Extract explicit work-mode preference (remote, hybrid, onsite)."""
    for pattern, mode_val in WORK_MODE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return mode_val, match.group(0).strip(), "HIGH"
    return None, None, "LOW"


# ---------------------------------------------------------------------------
# EMPLOYMENT PREFERENCES EXTRACTION
# ---------------------------------------------------------------------------
EMPLOYMENT_PATTERNS = [
    (r"(?i)\b(?:seeking|looking\s+for|open\s+to|interested\s+in|available\s+for)\s*[:\-]?\s*(?:summer\s+|winter\s+)?internships?(?:\s+opportunities|\s+roles|\s+positions)?\b", "internship"),
    (r"(?i)\b(?:employment\s+type|job\s+type|preference)\s*[:\-]\s*internships?\b", "internship"),
    (r"(?i)\b(?:seeking|looking\s+for|open\s+to|interested\s+in|available\s+for)\s*[:\-]?\s*full[- ]time(?:\s+opportunities|\s+roles|\s+positions|\s+jobs)?\b", "full_time"),
    (r"(?i)\b(?:employment\s+type|job\s+type|preference)\s*[:\-]\s*full[- ]time\b", "full_time"),
    (r"(?i)\b(?:seeking|looking\s+for|open\s+to|interested\s+in|available\s+for)\s*[:\-]?\s*part[- ]time(?:\s+opportunities|\s+roles|\s+positions|\s+jobs)?\b", "part_time"),
    (r"(?i)\b(?:employment\s+type|job\s+type|preference)\s*[:\-]\s*part[- ]time\b", "part_time"),
    (r"(?i)\b(?:seeking|looking\s+for|open\s+to|interested\s+in|available\s+for)\s*[:\-]?\s*contracts?(?:\s+opportunities|\s+roles|\s+positions)?\b", "contract"),
    (r"(?i)\b(?:employment\s+type|job\s+type|preference)\s*[:\-]\s*contracts?\b", "contract"),
]


def _extract_employment_preferences(text: str) -> tuple[list[str], Optional[str], str]:
    """Extract explicit employment preferences (internship, full_time, part_time, contract)."""
    prefs: list[str] = []
    evidence_parts: list[str] = []

    for pattern, emp_type in EMPLOYMENT_PATTERNS:
        match = re.search(pattern, text)
        if match:
            if emp_type not in prefs:
                prefs.append(emp_type)
                evidence_parts.append(match.group(0).strip())

    evidence = "; ".join(evidence_parts) if evidence_parts else None
    conf = "HIGH" if prefs else "LOW"
    return prefs, evidence, conf


# ---------------------------------------------------------------------------
# PUBLIC CANDIDATE PROFILING API
# ---------------------------------------------------------------------------
def profile_candidate(resume_text: Optional[str]) -> CandidateProfile:
    """Deterministically convert raw resume text into a CandidateProfile.

    Args:
        resume_text: Raw plain text extracted from a resume file or candidate profile.

    Returns:
        CandidateProfile instance with structured, normalized fields and evidence.
    """
    if not resume_text or not isinstance(resume_text, str) or not resume_text.strip():
        return CandidateProfile()

    evidence: dict[str, str] = {}
    confidence: dict[str, str] = {}

    # 1. Skills extraction
    raw_skills, norm_skills, unk_skills, skill_ev = _extract_skills(resume_text)
    if skill_ev:
        evidence["skills"] = skill_ev
        confidence["skills"] = "HIGH"

    # 2. Seniority extraction
    seniority, sen_ev, sen_conf = _extract_seniority(resume_text)
    if sen_ev:
        evidence["seniority"] = sen_ev
        confidence["seniority"] = sen_conf

    # 3. Experience extraction
    exp_years, exp_ev, exp_conf = _extract_experience(resume_text)
    if exp_ev:
        evidence["experience_years"] = exp_ev
        confidence["experience_years"] = exp_conf

    # 4. Graduation year extraction
    grad_year, grad_ev, grad_conf = _extract_graduation_year(resume_text)
    if grad_ev:
        evidence["graduation_year"] = grad_ev
        confidence["graduation_year"] = grad_conf

    # 5. Location preferences extraction
    curr_loc, pref_locs, loc_ev, loc_conf = _extract_locations(resume_text)
    if loc_ev:
        evidence["locations"] = loc_ev
        confidence["locations"] = loc_conf

    # 6. Work mode preference extraction
    work_mode, wm_ev, wm_conf = _extract_work_mode(resume_text)
    if wm_ev:
        evidence["work_mode"] = wm_ev
        confidence["work_mode"] = wm_conf

    # 7. Employment preferences extraction
    emp_prefs, emp_ev, emp_conf = _extract_employment_preferences(resume_text)
    if emp_ev:
        evidence["employment_preferences"] = emp_ev
        confidence["employment_preferences"] = emp_conf

    return CandidateProfile(
        raw_skills=raw_skills,
        normalized_skills=norm_skills,
        unknown_skills=unk_skills,
        seniority=seniority,
        experience_years=exp_years,
        graduation_year=grad_year,
        current_location=curr_loc,
        preferred_locations=pref_locs,
        work_mode=work_mode,
        employment_preferences=emp_prefs,
        evidence=evidence,
        confidence=confidence,
    )
