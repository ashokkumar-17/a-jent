"""
Automated Tests for Task 9: Extracted Resume Parsing (resume_parser.py)
----------------------------------------------------------------------
Verifies:
1. extract_resume_text() handles empty, None, or nonexistent file paths returning "".
2. extract_resume_text() handles unsupported file extensions safely returning "".
3. PDF text extraction via pdfplumber correctly extracts and joins page text.
4. DOCX text extraction via python-docx correctly extracts and joins paragraph text.
5. Parser exceptions during PDF/DOCX extraction are caught, logged, and return "".
6. get_resume_text() loads and returns parsed resume text when available.
7. get_resume_text() falls back to FALLBACK_KEYWORDS_TEXT when resume is absent or empty.
8. Custom resume path argument in get_resume_text(resume_path) is respected.
9. Configuration resolution of RESUME_PATH works via default and overrides.
10. Backward compatibility: job_search_agent re-exports and delegation wrappers work seamlessly.
"""

import sys
import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from a_jent import resume_parser
import job_search_agent


class TestResumeParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------
    # 1. Edge Cases & Missing/Unsupported File Paths
    # -------------------------------------------------------------------
    def test_extract_resume_text_empty_or_none(self):
        """extract_resume_text() returns empty string when path is None or empty."""
        self.assertEqual(resume_parser.extract_resume_text(""), "")
        self.assertEqual(resume_parser.extract_resume_text(None), "")

    def test_extract_resume_text_nonexistent_file(self):
        """extract_resume_text() returns empty string when file does not exist on disk."""
        fake_path = str(self.temp_dir_path / "does_not_exist.pdf")
        self.assertEqual(resume_parser.extract_resume_text(fake_path), "")

    def test_extract_resume_text_unsupported_extension(self):
        """extract_resume_text() logs warning and returns empty string for unsupported formats."""
        txt_file = self.temp_dir_path / "resume.txt"
        txt_file.write_text("Plain text resume")

        with self.assertLogs("agent", level="WARNING") as log_cm:
            result = resume_parser.extract_resume_text(str(txt_file))
            self.assertEqual(result, "")
            self.assertTrue(any("Unsupported resume format: .txt" in msg for msg in log_cm.output))

    # -------------------------------------------------------------------
    # 2. PDF & DOCX Parsing
    # -------------------------------------------------------------------
    def test_extract_resume_text_pdf_success(self):
        """extract_resume_text() uses pdfplumber to extract page text joined by newlines."""
        pdf_file = self.temp_dir_path / "candidate.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 dummy content")

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1: Senior Software Engineer"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page 2: Python, Kubernetes, AWS"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__.return_value = mock_pdf

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict("sys.modules", {"pdfplumber": mock_pdfplumber}):
            text = resume_parser.extract_resume_text(str(pdf_file))
            self.assertEqual(text, "Page 1: Senior Software Engineer\nPage 2: Python, Kubernetes, AWS")
            mock_pdfplumber.open.assert_called_once_with(str(pdf_file))

    def test_extract_resume_text_docx_success(self):
        """extract_resume_text() uses python-docx to extract paragraph text joined by newlines."""
        docx_file = self.temp_dir_path / "candidate.docx"
        docx_file.write_bytes(b"PK dummy docx content")

        mock_p1 = MagicMock()
        mock_p1.text = "John Doe — Full Stack Engineer"
        mock_p2 = MagicMock()
        mock_p2.text = "FastAPI, React, PostgreSQL"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_p1, mock_p2]

        mock_docx_module = MagicMock()
        mock_docx_module.Document.return_value = mock_doc

        with patch.dict("sys.modules", {"docx": mock_docx_module}):
            text = resume_parser.extract_resume_text(str(docx_file))
            self.assertEqual(text, "John Doe — Full Stack Engineer\nFastAPI, React, PostgreSQL")
            mock_docx_module.Document.assert_called_once_with(str(docx_file))

    # -------------------------------------------------------------------
    # 3. Parser Exception Safety (No Unhandled Crashes)
    # -------------------------------------------------------------------
    def test_extract_resume_text_pdf_exception_handled_safely(self):
        """Exceptions during PDF parsing are caught, logged, and return empty string."""
        pdf_file = self.temp_dir_path / "corrupt.pdf"
        pdf_file.write_bytes(b"corrupt data")

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.side_effect = Exception("PDF header corrupted")

        with patch.dict("sys.modules", {"pdfplumber": mock_pdfplumber}):
            with self.assertLogs("agent", level="WARNING") as log_cm:
                result = resume_parser.extract_resume_text(str(pdf_file))
                self.assertEqual(result, "")
                self.assertTrue(any("Could not parse resume" in msg for msg in log_cm.output))

    def test_extract_resume_text_docx_exception_handled_safely(self):
        """Exceptions during DOCX parsing are caught, logged, and return empty string."""
        docx_file = self.temp_dir_path / "corrupt.docx"
        docx_file.write_bytes(b"corrupt data")

        mock_docx_module = MagicMock()
        mock_docx_module.Document.side_effect = Exception("DOCX package invalid")

        with patch.dict("sys.modules", {"docx": mock_docx_module}):
            with self.assertLogs("agent", level="WARNING") as log_cm:
                result = resume_parser.extract_resume_text(str(docx_file))
                self.assertEqual(result, "")
                self.assertTrue(any("Could not parse resume" in msg for msg in log_cm.output))

    # -------------------------------------------------------------------
    # 4. Fallback Selection & Profile Management
    # -------------------------------------------------------------------
    def test_get_resume_text_returns_extracted_text_when_available(self):
        """get_resume_text() returns extracted text when resume exists and contains text."""
        with patch.object(resume_parser, "extract_resume_text", return_value="Candidate Profile: ML Engineer"):
            text = resume_parser.get_resume_text()
            self.assertEqual(text, "Candidate Profile: ML Engineer")

    def test_get_resume_text_returns_fallback_keywords_when_empty(self):
        """get_resume_text() falls back to FALLBACK_KEYWORDS_TEXT when resume parsing yields empty."""
        with patch.object(resume_parser, "extract_resume_text", return_value="   "):
            text = resume_parser.get_resume_text()
            self.assertEqual(text, resume_parser.FALLBACK_KEYWORDS_TEXT)

    def test_get_resume_text_custom_path_override(self):
        """get_resume_text() accepts an explicit resume_path parameter."""
        custom_path = str(self.temp_dir_path / "custom.pdf")
        with patch.object(resume_parser, "extract_resume_text", return_value="Custom text") as mock_extract:
            text = resume_parser.get_resume_text(resume_path=custom_path)
            self.assertEqual(text, "Custom text")
            mock_extract.assert_called_once_with(custom_path)

    def test_fallback_keywords_text_content(self):
        """FALLBACK_KEYWORDS_TEXT contains foundational role and skill profile terms."""
        fb = resume_parser.FALLBACK_KEYWORDS_TEXT
        self.assertIn("software engineer", fb)
        self.assertIn("python", fb)
        self.assertIn("machine learning", fb)
        self.assertIn("docker", fb)
        self.assertIn("kubernetes", fb)

    # -------------------------------------------------------------------
    # 5. Configuration & Backward Compatibility
    # -------------------------------------------------------------------
    def test_configuration_resume_path_override(self):
        """_get() properly resolves RESUME_PATH from config or env."""
        with patch.dict("os.environ", {"RESUME_PATH": "/custom/path/resume.pdf"}):
            resolved = resume_parser._get("RESUME_PATH", "default.pdf")
            self.assertEqual(resolved, "/custom/path/resume.pdf")

    def test_job_search_agent_backward_compatibility(self):
        """job_search_agent re-exports resume parsing symbols and delegates seamlessly."""
        self.assertEqual(job_search_agent.RESUME_PATH, resume_parser.RESUME_PATH)
        self.assertEqual(job_search_agent.FALLBACK_KEYWORDS_TEXT, resume_parser.FALLBACK_KEYWORDS_TEXT)
        self.assertTrue(callable(job_search_agent.extract_resume_text))
        self.assertTrue(callable(job_search_agent.get_resume_text))

        # Test wrapper delegation
        with patch.object(resume_parser, "get_resume_text", return_value="Delegated text") as mock_get:
            res = job_search_agent.get_resume_text()
            self.assertEqual(res, "Delegated text")
            mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
