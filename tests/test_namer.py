"""Unit tests for filename generation and sanitization."""

import unittest
from pathlib import Path
import tempfile

from paperharbor.models import Reference
from paperharbor.namer import (
    generate_filename,
    get_unique_destination_path,
    sanitize_author,
    sanitize_title,
)


class TestNamer(unittest.TestCase):
    def test_standard_filename(self):
        ref = Reference(
            key="ABC123",
            title="Phishing Detection",
            authors=["Smith, John"],
            first_author="Smith",
            year=2025,
            doi="10.1000/182"
        )
        filename = generate_filename(ref)
        self.assertEqual(filename, "2025_Smith_Phishing_Detection.pdf")

    def test_special_characters_and_html(self):
        ref = Reference(
            key="XYZ789",
            title="Deep Learning & <i>Neural Networks</i>: A Survey / Review?",
            authors=["Müller, Hans"],
            first_author="Müller",
            year=2024
        )
        filename = generate_filename(ref)
        # Muller is normalized from Müller, HTML tags removed, colons and slashes removed
        self.assertTrue(filename.startswith("2024_Muller_Deep_Learning_Neural_Networks"))
        self.assertTrue(filename.endswith(".pdf"))
        self.assertNotIn("<", filename)
        self.assertNotIn(">", filename)
        self.assertNotIn(":", filename)
        self.assertNotIn("/", filename)
        self.assertNotIn("?", filename)

    def test_missing_metadata_fallbacks(self):
        ref = Reference(key="EMPTY1")
        filename = generate_filename(ref)
        self.assertEqual(filename, "UnknownYear_UnknownAuthor_Untitled.pdf")

    def test_title_truncation(self):
        long_title = "A " + "Very " * 40 + "Long Academic Paper Title That Might Break Windows Path Limits"
        sanitized = sanitize_title(long_title, max_words=6, max_chars=40)
        self.assertLessEqual(len(sanitized), 40)
        self.assertFalse(sanitized.endswith("_"))

    def test_unique_destination_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir)
            base_name = "2025_Smith_Phishing_Detection.pdf"
            
            p1 = get_unique_destination_path(dest, base_name)
            self.assertEqual(p1.name, base_name)
            p1.write_bytes(b"%PDF-1.5 test content")

            # Second path should have _1
            p2 = get_unique_destination_path(dest, base_name)
            self.assertEqual(p2.name, "2025_Smith_Phishing_Detection_1.pdf")
            p2.write_bytes(b"%PDF-1.5 test content")

            # Third path should have _2
            p3 = get_unique_destination_path(dest, base_name)
            self.assertEqual(p3.name, "2025_Smith_Phishing_Detection_2.pdf")


if __name__ == "__main__":
    unittest.main()
