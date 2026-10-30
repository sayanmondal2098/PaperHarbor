"""Unit tests for CSV reporter."""

import csv
import tempfile
import unittest
from pathlib import Path

from paperharbor.models import DownloadResult, PaperStatus, Reference
from paperharbor.reporter import Reporter


class TestReporter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.report_path = Path(self.temp_dir.name) / "test_report.csv"
        self.reporter = Reporter(output_path=self.report_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_csv_recording_and_output(self):
        r1 = Reference(
            key="KEY1",
            title="Phishing Detection",
            authors=["Smith, John"],
            first_author="Smith",
            year=2025,
            doi="10.1145/123"
        )
        res1 = DownloadResult(
            reference=r1,
            status=PaperStatus.DOWNLOADED,
            provider="Unpaywall",
            pdf_url="https://oa.org/paper.pdf",
            saved_filename="2025_Smith_Phishing_Detection.pdf",
            saved_path="/data/2025_Smith_Phishing_Detection.pdf",
            file_size_bytes=204800,
            notes="Downloaded successfully"
        )

        r2 = Reference(
            key="KEY2",
            title="Paywalled Paper",
            authors=["Doe, Jane"],
            first_author="Doe",
            year=2024,
            doi="10.1016/456"
        )
        res2 = DownloadResult(
            reference=r2,
            status=PaperStatus.PAYWALLED_OR_OA_NOT_FOUND,
            publisher_url="https://doi.org/10.1016/456",
            notes="No OA found"
        )

        self.reporter.record(res1)
        self.reporter.record(res2)

        out_path = self.reporter.write_csv()
        self.assertTrue(out_path.exists())

        # Read back CSV
        with open(out_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Status"], "DOWNLOADED")
        self.assertEqual(rows[0]["First_Author"], "Smith")
        self.assertEqual(rows[0]["Year"], "2025")
        self.assertEqual(rows[0]["Saved_Filename"], "2025_Smith_Phishing_Detection.pdf")
        self.assertEqual(rows[0]["File_Size_KB"], "200.0")

        self.assertEqual(rows[1]["Status"], "PAYWALLED_OR_OA_NOT_FOUND")
        self.assertEqual(rows[1]["Publisher_Or_Landing_URL"], "https://doi.org/10.1016/456")

        summary = self.reporter.get_summary()
        self.assertEqual(summary["TOTAL_REFERENCES"], 2)
        self.assertEqual(summary[PaperStatus.DOWNLOADED.value], 1)
        self.assertEqual(summary[PaperStatus.PAYWALLED_OR_OA_NOT_FOUND.value], 1)


if __name__ == "__main__":
    unittest.main()
