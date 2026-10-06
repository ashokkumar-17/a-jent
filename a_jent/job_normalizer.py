"""
Job Normalizer Module
---------------------
Deterministically converts raw job dictionaries from A-Jent job sources
into structured JobProfile objects.

Extracts:
- Core metadata: job_id, title, company, raw_location, url, source, description
- Required skills vs preferred skills (normalized via a_jent.skill_taxonomy)
- Unknown skills from explicit skill sections
- Seniority (intern, entry_level, junior, mid_level, senior, lead)
- Minimum experience requirements in years
- Cleaned location and explicit work mode (remote, hybrid, onsite)
- Employment type (internship, full_time, part_time, contract, temporary)
- Graduation requirements (e.g., 2026, 2027)
- Textual evidence and confidence levels

Guarantees:
- Deterministic: same input dictionary -> identical JobProfile
- Non-mutating: original raw job dictionary is preserved unchanged
- False-positive safeguards (word boundaries, negative lookaheads, context checks)
- UNKNOWN != REMOTE: missing fields remain None / empty
- Standalone: does NOT modify the existing live TF-IDF matching pipeline
"""

from dataclasses import dataclass, field
import re
from typing import Any, Optional

from a_jent import skill_taxonomy

# ---------------------------------------------------------------------------
# STRUCTURED JOB PROFILE
# ---------------------------------------------------------------------------
@dataclass
class JobProfile:
    """Structured job listing representation extracted deterministically."""

    job_id: str = ""
    title: str = ""
    company: str = ""
    raw_location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""

    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    unknown_skills: list[str] = field(default_factory=list)

    seniority: Optional[str] = None
    experience_years: Optional[float] = None
    location: Optional[str] = None
    work_mode: Optional[str] = None
    employment_type: Optional[str] = None
    graduation_year: Optional[int] = None

    evidence: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, str] = field(default_factory=dict)
    raw_job: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize profile to standard dictionary representation."""
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "raw_location": self.raw_location,
            "url": self.url,
            "source": self.source,
            "description": self.description,
            "required_skills": list(self.required_skills),
            "preferred_skills": list(self.preferred_skills),
            "unknown_skills": list(self.unknown_skills),
            "seniority": self.seniority,
            "experience_years": self.experience_years,
            "location": self.location,
            "work_mode": self.work_mode,
            "employment_type": self.employment_type,
            "graduation_year": self.graduation_year,
            "evidence": dict(self.evidence),
            "confidence": dict(self.confidence),
        }


# ---------------------------------------------------------------------------
# KNOWN TARGET LOCATIONS
# ---------------------------------------------------------------------------
KNOWN_LOCATIONS = [
    "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi",
    "chennai", "noida", "gurgaon", "gurugram", "kolkata", "ahmedabad",
    "kochi", "coimbatore", "chandigarh", "jaipur", "remote", "india",
]


# ---------------------------------------------------------------------------
# SECTION PARSING REGEXES
# ---------------------------------------------------------------------------
REQ_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s*)?(requirements?|required\s+skills?|required\s+qualifications?|minimum\s+qualifications?|minimum\s+requirements?|required|must\s+have|mandatory|what\s+you(?:'ll|\s+will)?\s+need|what\s+we(?:'re|\s+are)?\s+looking\s+for|qualifications?)(?:\s*[:\-]\s*(.*)|\s*)$",
    re.IGNORECASE,
)
PREF_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s*)?(preferred\s+skills?|preferred\s+qualifications?|preferred\s+requirements?|preferred|nice\s+to\s+have|good\s+to\s+have|bonus(?:\s+points)?|plus|desirable|optional\s+skills?)(?:\s*[:\-]\s*(.*)|\s*)$",
    re.IGNORECASE,
)
GEN_SKILL_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s*)?(skills?|technical\s+skills?|tech\s+stack|key\s+skills?|technologies)(?:\s*[:\-]\s*(.*)|\s*)$",
    re.IGNORECASE,
)
OTHER_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s*)?(responsibilities|what\s+you(?:'ll|\s+will)?\s+do|about\s+(?:the\s+role|us|the\s+team|company)|what\s+we\s+offer|benefits|perks|location|work\s+mode|employment\s+type|job\s+type|experience\s+required|how\s+to\s+apply|salary|compensation|overview|summary)(?:\s*[:\-]\s*(.*)|\s*)$",
    re.IGNORECASE,
)
INLINE_SPLIT_RE = re.compile(
    r"(?i)(?:^|(?<=[\n\.;]))\s*(requirements?|required\s+skills?|required\s+qualifications?|minimum\s+qualifications?|required|must\s+have|mandatory|qualifications?|preferred\s+skills?|preferred\s+qualifications?|preferred|nice\s+to\s+have|good\s+to\s+have|bonus(?:\s+points)?|plus|desirable|responsibilities|benefits|location|work\s+mode|employment\s+type)\s*[:\-]",
)

NON_SKILL_WORDS = re.compile(
    r"(?i)\b(?:requirements?|qualifications?|preferred|skills?|technologies|tools|languages|responsibilities|experience|years?|degree|bachelor|master|communication|team|looking|responsible|benefits|perks|education|overview|summary)\b"
)


def _parse_job_sections(description: str) -> dict[str, str]:
    """Parse description into required, preferred, generic skills, general, and other sections."""
    # Pre-split text if inline headers exist on the same line
    splits = [m.start() for m in INLINE_SPLIT_RE.finditer(description)]
    if len(splits) > 1:
        segments = []
        prev = 0
        for s in splits:
            if s > prev:
                segments.append(description[prev:s].strip())
            prev = s
        segments.append(description[prev:].strip())
        lines = []
        for seg in segments:
            lines.extend(seg.splitlines())
    else:
        lines = description.splitlines()

    state = "general"
    sections: dict[str, list[str]] = {
        "general": [],
        "required": [],
        "preferred": [],
        "generic_skills": [],
        "other": [],
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Bullet point lines cannot be section headers
        if re.match(r"^(?:[-*•·]|\d+\.)\s+", stripped):
            sections[state].append(stripped)
            continue

        m_req = REQ_HEADER_RE.match(stripped)
        m_pref = PREF_HEADER_RE.match(stripped)
        m_gen = GEN_SKILL_HEADER_RE.match(stripped)
        m_other = OTHER_HEADER_RE.match(stripped)

        if m_req:
            state = "required"
            rest = m_req.group(2)
            if rest and rest.strip():
                sections[state].append(rest.strip())
        elif m_pref:
            state = "preferred"
            rest = m_pref.group(2)
            if rest and rest.strip():
                sections[state].append(rest.strip())
        elif m_gen:
            state = "generic_skills"
            rest = m_gen.group(2)
            if rest and rest.strip():
                sections[state].append(rest.strip())
        elif m_other:
            state = "other"
            rest = m_other.group(2)
            if rest and rest.strip():
                sections[state].append(rest.strip())
        else:
            sections[state].append(stripped)

    return {k: "\n".join(v) for k, v in sections.items()}



# ---------------------------------------------------------------------------
# SKILL EXTRACTION HELPERS & COMPILED PATTERNS
# ---------------------------------------------------------------------------
SPECIAL_SKILL_PATTERNS = [
    (r"(?i)(?:(?<=\s)|^|(?<=[,;(]))c\+\+(?=[,\s\.;\)]|$)", "c++"),
    (r"(?i)(?:(?<=\s)|^|(?<=[,;(]))c#(?=[,\s\.;\)]|$)", "c#"),
    (r"(?i)\bjava\b(?!\s*script\b)", "java"),
    (r"(?i)\breact\b(?!\s*native\b)", "react"),
    (r"(?i)\b(?:next\.js|nextjs)\b", "next.js"),
    (r"(?i)\b(?:node\.js|nodejs)\b", "node.js"),
    (r"(?i)\b(?:ci\/cd|cicd|ci cd)\b", "ci/cd"),
]


def _extract_skills_from_text(
    text: str, is_section: bool = False
) -> tuple[list[str], list[str]]:
    """Extract recognized canonical skills and unknown isolated skills from text."""
    normalized_skills: list[str] = []
    normalized_set: set[str] = set()
    unknown_skills: list[str] = []

    # 1. Special boundary skills
    for pattern, canonical_target in SPECIAL_SKILL_PATTERNS:
        if re.search(pattern, text):
            if canonical_target not in normalized_set:
                normalized_set.add(canonical_target)
                normalized_skills.append(canonical_target)

    # 2. Match against taxonomy entries
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
            if candidate in ("c++", "c#", "java", "react", "next.js", "node.js", "ci/cd"):
                continue

            if candidate == "c":
                if re.search(r"(?i)\b(?:c\s+lang(?:uage)?)\b", text):
                    normalized_set.add(canonical)
                    normalized_skills.append(canonical)
                    break
                elif is_section and re.search(r"(?i)(?:(?<=\s)|^|(?<=[,;(]))c(?=[,\s\.;\)]|$)(?!\+\+|#)", text):
                    normalized_set.add(canonical)
                    normalized_skills.append(canonical)
                    break
                continue

            if candidate == "go":
                if re.search(r"(?i)\bgolang\b", text):
                    normalized_set.add(canonical)
                    normalized_skills.append(canonical)
                    break
                elif is_section and re.search(r"(?i)\bgo\b", text):
                    normalized_set.add(canonical)
                    normalized_skills.append(canonical)
                    break
                continue

            escaped = re.escape(candidate)
            pattern_str = r"(?i)\b" + re.sub(r"\\\s+", r"\\s+", escaped) + r"\b"
            if re.search(pattern_str, text):
                normalized = skill_taxonomy.normalize_skill(candidate)
                if normalized and normalized not in normalized_set:
                    normalized_set.add(normalized)
                    normalized_skills.append(normalized)
                break

    # 3. Unmapped tokens in explicit section text
    if is_section:
        tokens = re.split(r"[,|\n•·\t\r/]+", text)
        for tok in tokens:
            cleaned = re.sub(r"^[-*•·\s\d\.)]+", "", tok).strip().rstrip(";,.:-")
            if not cleaned or len(cleaned) > 30 or len(cleaned.split()) > 3:
                continue
            if re.search(r"\d", cleaned) or NON_SKILL_WORDS.search(cleaned):
                continue
            if skill_taxonomy.is_known_skill(cleaned):
                norm = skill_taxonomy.normalize_skill(cleaned)
                if norm and norm not in normalized_set:
                    normalized_set.add(norm)
                    normalized_skills.append(norm)
            else:
                clean_lower = cleaned.lower()
                if clean_lower not in unknown_skills and clean_lower not in normalized_set:
                    unknown_skills.append(clean_lower)

    return normalized_skills, unknown_skills


def _partition_required_preferred_skills(
    title: str, description: str
) -> tuple[list[str], list[str], list[str], Optional[str]]:
    """Partition extracted skills into required and preferred based on explicit section structure and phrasing."""
    sections = _parse_job_sections(description)

    req_text = sections.get("required", "")
    pref_text = sections.get("preferred", "")
    gen_skills_text = sections.get("generic_skills", "")
    general_text = f"{title}\n{sections.get('general', '')}"

    required_skills: list[str] = []
    preferred_skills: list[str] = []
    unknown_skills: list[str] = []

    # 1. Process explicit required section
    if req_text:
        req_norm, req_unk = _extract_skills_from_text(req_text, is_section=True)
        for s in req_norm:
            if s not in required_skills:
                required_skills.append(s)
        for u in req_unk:
            if u not in unknown_skills:
                unknown_skills.append(u)

    # 2. Process explicit preferred section
    if pref_text:
        pref_norm, pref_unk = _extract_skills_from_text(pref_text, is_section=True)
        for s in pref_norm:
            if s not in preferred_skills and s not in required_skills:
                preferred_skills.append(s)
        for u in pref_unk:
            if u not in unknown_skills:
                unknown_skills.append(u)

    # 3. Process generic skills section (treated as required for now as documented)
    if gen_skills_text:
        gen_norm, gen_unk = _extract_skills_from_text(gen_skills_text, is_section=True)
        for s in gen_norm:
            if s not in required_skills and s not in preferred_skills:
                required_skills.append(s)
        for u in gen_unk:
            if u not in unknown_skills:
                unknown_skills.append(u)

    # 4. Process general body text and title
    # Detect inline preferred sentences (e.g. "Docker is preferred", "AWS knowledge is a plus")
    sentences = re.split(r"(?<=[.!?])\s+", general_text)
    for sent in sentences:
        is_inline_pref = bool(
            re.search(
                r"(?i)\b(?:is\s+(?:preferred|a\s+plus|desirable|bonus)|nice\s+to\s+have|good\s+to\s+have)\b",
                sent,
            )
        )
        sent_norm, _ = _extract_skills_from_text(sent, is_section=False)
        for s in sent_norm:
            if is_inline_pref:
                if s not in preferred_skills and s not in required_skills:
                    preferred_skills.append(s)
            else:
                if s not in required_skills and s not in preferred_skills:
                    required_skills.append(s)

    # Deduplicate: if a skill is in both required and preferred, required takes precedence
    preferred_skills = [s for s in preferred_skills if s not in required_skills]
    # Filter unknown skills that happen to be in normalized skills
    unknown_skills = [u for u in unknown_skills if u not in required_skills and u not in preferred_skills]

    evidence_parts = []
    if required_skills:
        evidence_parts.append(f"Required: {', '.join(required_skills[:5])}")
    if preferred_skills:
        evidence_parts.append(f"Preferred: {', '.join(preferred_skills[:5])}")
    evidence = "; ".join(evidence_parts) if evidence_parts else None

    return required_skills, preferred_skills, unknown_skills, evidence


# ---------------------------------------------------------------------------
# SENIORITY EXTRACTION
# ---------------------------------------------------------------------------
TITLE_SENIORITY_PATTERNS = [
    (r"(?i)\b(?:tech\s+lead|team\s+lead|lead|principal|staff)\b", "lead"),
    (r"(?i)\b(?:senior|sr\.?)\b", "senior"),
    (r"(?i)\bmid[- ]level\b", "mid_level"),
    (r"(?i)\b(?:junior|jr\.?)\b", "junior"),
    (r"(?i)\b(?:intern(?:ship)?|trainee)\b", "intern"),
    (r"(?i)\b(?:fresher|entry[- ]level|graduate|new\s+grad)\b", "entry_level"),
]

DESC_SENIORITY_PATTERNS = [
    (r"(?i)\b(?:role\s+level|seniority|level|experience\s+level)\s*[:\-]\s*(senior|lead|principal|staff)\b", "senior"),
    (r"(?i)\b(?:we\s+are\s+looking\s+for|seeking|hiring)\s+(?:an?|a)\s+(?:senior|sr\.?)\s+(?:software|developer|engineer|data)\b", "senior"),
    (r"(?i)\b(?:role\s+level|seniority|level|experience\s+level)\s*[:\-]\s*(junior|entry[- ]level|intern|fresher)\b", "entry_level"),
    (r"(?i)\b(?:fresher|fresh\s+graduates?\s+welcome|entry[- ]level\s+role)\b", "entry_level"),
    (r"(?i)\b(?:internship\s+role|internship\s+opportunity)\b", "intern"),
]


def _extract_seniority(title: str, description: str) -> tuple[Optional[str], Optional[str], str]:
    """Extract explicit seniority from job title or description, guarding against false positives."""
    # 1. Title is primary and most authoritative
    for pattern, seniority_val in TITLE_SENIORITY_PATTERNS:
        match = re.search(pattern, title)
        if match:
            return seniority_val, f"Title: '{match.group(0).strip()}'", "HIGH"

    # 2. Description (with false-positive protection against mentoring/reporting phrases)
    for pattern, seniority_val in DESC_SENIORITY_PATTERNS:
        match = re.search(pattern, description)
        if match:
            matched_snippet = match.group(0).strip()
            # Guard against "mentoring junior developers"
            if re.search(r"(?i)\b(?:mentoring|mentor|guide|supervise|leading)\s+(?:junior|interns?)\b", matched_snippet):
                continue
            return seniority_val, matched_snippet, "HIGH"

    return None, None, "LOW"


# ---------------------------------------------------------------------------
# EXPERIENCE REQUIREMENT EXTRACTION
# ---------------------------------------------------------------------------
EXP_RANGE_PATTERN = r"(?i)\b(\d+(?:\.\d+)?)\s*[-–—to]+\s*\d+(?:\.\d+)?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:\w+\s+){0,3}experience\b"
EXP_MIN_PATTERN = r"(?i)\b(?:minimum|at\s+least)?\s*(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:\w+\s+){0,3}experience\b"
EXP_HEADER_PATTERN = r"(?i)\b(?:experience\s+required|minimum\s+experience|experience)\s*[:\-]\s*(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\b"
EXP_ZERO_PATTERN = r"(?i)\b(?:0[-–—]|\b0\s*(?:years?|yrs?)|fresh\s+graduates?\s+welcome|no\s+experience\s+required|no\s+prior\s+experience)\b"


def _extract_experience(description: str) -> tuple[Optional[float], Optional[str], str]:
    """Extract minimum required professional experience in years."""
    # 1. Zero experience indicators
    zero_match = re.search(EXP_ZERO_PATTERN, description)
    if zero_match:
        return 0.0, zero_match.group(0).strip(), "HIGH"

    # 2. Range (e.g. 2-4 years of experience -> minimum is 2.0)
    range_match = re.search(EXP_RANGE_PATTERN, description)
    if range_match:
        try:
            return float(range_match.group(1)), range_match.group(0).strip(), "HIGH"
        except (ValueError, IndexError):
            pass

    # 3. Minimum / plus pattern (e.g. 2+ years of experience)
    min_match = re.search(EXP_MIN_PATTERN, description)
    if min_match:
        try:
            val = float(min_match.group(1))
            # Safeguard: experience requirements typically between 0.5 and 20 years
            if 0.5 <= val <= 20.0:
                return val, min_match.group(0).strip(), "HIGH"
        except (ValueError, IndexError):
            pass

    # 4. Explicit header (e.g. Experience: 3 years)
    header_match = re.search(EXP_HEADER_PATTERN, description)
    if header_match:
        try:
            val = float(header_match.group(1))
            if 0.5 <= val <= 20.0:
                return val, header_match.group(0).strip(), "HIGH"
        except (ValueError, IndexError):
            pass

    return None, None, "LOW"


# ---------------------------------------------------------------------------
# LOCATION & WORK MODE EXTRACTION
# ---------------------------------------------------------------------------
def _extract_location_and_work_mode(
    raw_location: str, title: str, description: str
) -> tuple[Optional[str], Optional[str], Optional[str], str]:
    """Extract primary location and explicit work mode (remote, hybrid, onsite)."""
    loc_cleaned: Optional[str] = None
    work_mode: Optional[str] = None
    evidence_parts: list[str] = []

    combined_text = f"{raw_location} {title} {description}"

    # 1. Work Mode detection (preserving UNKNOWN != REMOTE)
    if re.search(r"(?i)\b(?:hybrid|partially\s+remote|remote\s*\/\s*onsite)\b", combined_text):
        work_mode = "hybrid"
        evidence_parts.append("Work mode: hybrid")
    elif re.search(r"(?i)\b(?:remote|work\s+from\s+home|wfh|fully\s+remote)\b", f"{raw_location} {title}"):
        work_mode = "remote"
        evidence_parts.append("Work mode: remote (found in location/title)")
    elif re.search(r"(?i)\b(?:100%\s+remote|strictly\s+remote|remote\s+role|remote\s+position|work\s+mode\s*[:\-]\s*remote)\b", description):
        work_mode = "remote"
        evidence_parts.append("Work mode: remote (found in description)")
    elif re.search(r"(?i)\b(?:onsite|on[- ]site|in[- ]office)\b", combined_text):
        work_mode = "onsite"
        evidence_parts.append("Work mode: onsite")

    # 2. Location detection
    # Search raw_location first
    if raw_location and raw_location.strip():
        for loc in KNOWN_LOCATIONS:
            if re.search(r"(?i)\b" + re.escape(loc) + r"\b", raw_location):
                loc_cleaned = loc
                evidence_parts.append(f"Location: {loc}")
                break
        if not loc_cleaned and raw_location.strip().lower() != "remote":
            loc_cleaned = raw_location.strip().lower()
            evidence_parts.append(f"Location: {loc_cleaned}")

    # If raw_location was empty or remote, check description for explicit office location
    if not loc_cleaned or loc_cleaned == "remote":
        loc_header_match = re.search(
            r"(?i)\b(?:job\s+location|office\s+location|location)\s*[:\-]\s*([A-Za-z\s,]+?)(?=(?:\n|\r|\s{3,}|$))",
            description,
        )
        if loc_header_match:
            cand = loc_header_match.group(1).strip()
            for loc in KNOWN_LOCATIONS:
                if re.search(r"(?i)\b" + re.escape(loc) + r"\b", cand):
                    loc_cleaned = loc
                    evidence_parts.append(f"Location in desc: {loc}")
                    break

    evidence = "; ".join(evidence_parts) if evidence_parts else None
    conf = "HIGH" if (loc_cleaned or work_mode) else "LOW"
    return loc_cleaned, work_mode, evidence, conf


# ---------------------------------------------------------------------------
# EMPLOYMENT TYPE EXTRACTION
# ---------------------------------------------------------------------------
EMP_TYPE_PATTERNS = [
    (r"(?i)\b(?:employment\s+type|job\s+type)\s*[:\-]\s*(?:internships?)\b", "internship"),
    (r"(?i)\b(?:internships?)\b", "internship"),
    (r"(?i)\b(?:employment\s+type|job\s+type)\s*[:\-]\s*(?:full[- ]time|fulltime)\b", "full_time"),
    (r"(?i)\b(?:full[- ]time|fulltime)\b", "full_time"),
    (r"(?i)\b(?:employment\s+type|job\s+type)\s*[:\-]\s*(?:part[- ]time|parttime)\b", "part_time"),
    (r"(?i)\b(?:part[- ]time|parttime)\b", "part_time"),
    (r"(?i)\b(?:employment\s+type|job\s+type)\s*[:\-]\s*(?:contracts?|contractual)\b", "contract"),
    (r"(?i)\b(?:contract|contractual)\b", "contract"),
    (r"(?i)\b(?:temporary|temp)\b", "temporary"),
]


def _extract_employment_type(
    raw_job: dict, description: str
) -> tuple[Optional[str], Optional[str], str]:
    """Extract explicit employment type without inferring solely from title."""
    # 1. Check direct field on raw job if provided by source
    for field_name in ("job_type", "employment_type", "type"):
        val = raw_job.get(field_name)
        if val and isinstance(val, str):
            for pattern, canonical_type in EMP_TYPE_PATTERNS:
                if re.search(pattern, val):
                    return canonical_type, f"Field '{field_name}': {val}", "HIGH"

    # 2. Check explicit description header
    desc_header_match = re.search(
        r"(?i)\b(?:employment\s+type|job\s+type)\s*[:\-]\s*([a-zA-Z\s\-]+?)(?=(?:\n|\r|\s{3,}|$))",
        description,
    )
    if desc_header_match:
        for pattern, canonical_type in EMP_TYPE_PATTERNS:
            if re.search(pattern, desc_header_match.group(0)):
                return canonical_type, desc_header_match.group(0).strip(), "HIGH"

    # 3. Check explicit wording in description body (e.g. "this is a full-time position")
    body_match = re.search(r"(?i)\b(?:this\s+is\s+a|position\s+is|role\s+is)\s+(full[- ]time|part[- ]time|contract|internship)\b", description)
    if body_match:
        cand = body_match.group(1).lower()
        if "full" in cand:
            return "full_time", body_match.group(0).strip(), "HIGH"
        if "part" in cand:
            return "part_time", body_match.group(0).strip(), "HIGH"
        if "contract" in cand:
            return "contract", body_match.group(0).strip(), "HIGH"
        if "intern" in cand:
            return "internship", body_match.group(0).strip(), "HIGH"

    return None, None, "LOW"


# ---------------------------------------------------------------------------
# GRADUATION REQUIREMENTS EXTRACTION
# ---------------------------------------------------------------------------
GRAD_REQ_PATTERNS = [
    r"(?i)\b(?:graduating(?:\s+in)?|class\s+of|expected\s+graduation(?:\s+in)?|must\s+graduate\s+by|graduates?\s+of|passout\s+of|batch\s+of)\s*[:\-]?\s*(20\d{2})\b",
    r"(?i)\b(20\d{2})\s+graduates?\s+(?:only|preferred|eligible)\b",
    r"(?i)\b(20\d{2})\s+batch(?:\s+only)?\b",
]


def _extract_graduation_year(description: str) -> tuple[Optional[int], Optional[str], str]:
    """Extract explicit graduation year requirement, avoiding false matches."""
    for pattern in GRAD_REQ_PATTERNS:
        match = re.search(pattern, description)
        if match:
            try:
                year = int(match.group(1))
                if 2015 <= year <= 2035:
                    return year, match.group(0).strip(), "HIGH"
            except (ValueError, IndexError):
                continue
    return None, None, "LOW"


# ---------------------------------------------------------------------------
# PUBLIC JOB NORMALIZATION API
# ---------------------------------------------------------------------------
def normalize_job(job: Optional[dict]) -> JobProfile:
    """Deterministically convert a raw job dictionary into a JobProfile.

    Args:
        job: Raw dictionary as returned by any A-Jent job source.

    Returns:
        JobProfile instance containing normalized fields, evidence, and raw reference.
    """
    if not job or not isinstance(job, dict):
        return JobProfile()

    # Core source metadata (non-mutating, defaults safe)
    job_id = str(job.get("id") or job.get("job_id") or "")
    title = str(job.get("title") or job.get("position") or "").strip()
    company = str(job.get("company") or job.get("company_name") or "").strip()
    raw_location = str(job.get("location") or "").strip()
    url = str(job.get("url") or "").strip()
    source = str(job.get("source") or "").strip()
    description = str(job.get("description") or "").strip()

    evidence: dict[str, str] = {}
    confidence: dict[str, str] = {}

    # 1. Skills extraction and partitioning
    req_skills, pref_skills, unk_skills, skill_ev = _partition_required_preferred_skills(
        title, description
    )
    if skill_ev:
        evidence["skills"] = skill_ev
        confidence["skills"] = "HIGH"

    # 2. Seniority extraction
    seniority, sen_ev, sen_conf = _extract_seniority(title, description)
    if sen_ev:
        evidence["seniority"] = sen_ev
        confidence["seniority"] = sen_conf

    # 3. Experience requirement extraction
    exp_years, exp_ev, exp_conf = _extract_experience(description)
    if exp_ev:
        evidence["experience_years"] = exp_ev
        confidence["experience_years"] = exp_conf

    # 4. Location & Work mode extraction
    location, work_mode, loc_ev, loc_conf = _extract_location_and_work_mode(
        raw_location, title, description
    )
    if loc_ev:
        evidence["location_work_mode"] = loc_ev
        confidence["location_work_mode"] = loc_conf

    # 5. Employment type extraction (do not infer solely from title)
    emp_type, emp_ev, emp_conf = _extract_employment_type(job, description)
    if emp_ev:
        evidence["employment_type"] = emp_ev
        confidence["employment_type"] = emp_conf

    # 6. Graduation requirement extraction
    grad_year, grad_ev, grad_conf = _extract_graduation_year(description)
    if grad_ev:
        evidence["graduation_year"] = grad_ev
        confidence["graduation_year"] = grad_conf

    return JobProfile(
        job_id=job_id,
        title=title,
        company=company,
        raw_location=raw_location,
        url=url,
        source=source,
        description=description,
        required_skills=req_skills,
        preferred_skills=pref_skills,
        unknown_skills=unk_skills,
        seniority=seniority,
        experience_years=exp_years,
        location=location,
        work_mode=work_mode,
        employment_type=emp_type,
        graduation_year=grad_year,
        evidence=evidence,
        confidence=confidence,
        raw_job=dict(job),  # Shallow copy preserves raw data without mutation
    )


def normalize_jobs(jobs: list[dict]) -> list[JobProfile]:
    """Normalize a collection of raw job dictionaries.

    Args:
        jobs: List of raw job dictionaries.

    Returns:
        List of normalized JobProfile instances.
    """
    if not jobs:
        return []
    return [normalize_job(j) for j in jobs]
