"""Integration tests verifying the complete PaperHarbor workflow."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paperharbor.app import PaperHarborApp
from paperharbor.models import CandidatePDF, PaperStatus, Reference
from paperharbor.zotero.reader_base import ZoteroReaderBase


class MockReader(ZoteroReaderBase):
    def __init__(self, references):
        self.references = references

    def get_references(self, collection_filter=None, only_missing_pdf=True):
        if only_missing_pdf:
            return [r for r in self.references if not r.has_zotero_pdf]
        return self.references


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dest_folder = Path(self.temp_dir.name) / "PersonalPapers"
        self.report_path = Path(self.temp_dir.name) / "reports" / "summary.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("paperharbor.providers.aggregator.ProviderAggregator.find_candidates")
    @patch("paperharbor.downloader.PdfDownloader.download_pdf")
    def test_full_pipeline(self, mock_download, mock_find):
        # Setup 3 references:
        # Ref 1: Already has PDF in Zotero (should be SKIPPED_ALREADY_IN_ZOTERO)
        ref1 = Reference(
            key="ZOT_HAS_PDF",
            title="Old Survey on Malware",
            authors=["Johnson, Alice"],
            first_author="Johnson",
            year=2021,
            doi="10.1000/malware",
            has_zotero_pdf=True,
            zotero_attachments=["storage:old_survey.pdf"]
        )

        # Ref 2: Missing PDF in Zotero, Open Access available (should be DOWNLOADED)
        ref2 = Reference(
            key="ZOT_NEEDS_PDF",
            title="Phishing Detection",
            authors=["Smith, Bob"],
            first_author="Smith",
            year=2025,
            doi="10.1145/phishing2025"
        )

        # Ref 3: Missing PDF in Zotero, Paywalled / No OA (should be PAYWALLED_OR_OA_NOT_FOUND)
        ref3 = Reference(
            key="ZOT_PAYWALLED",
            title="Proprietary Hardware Architecture",
            authors=["Williams, Clara"],
            first_author="Williams",
            year=2023,
            doi="10.1109/secret"
        )

        reader = MockReader([ref1, ref2, ref3])

        # Configure mock find_candidates
        def find_side_effect(ref):
            if ref.key == "ZOT_NEEDS_PDF":
                return [CandidatePDF(
                    url="https://openaccess.org/phishing.pdf",
                    provider="Unpaywall",
                    oa_status="gold"
                )], ref.publisher_url
            return [], ref.publisher_url

        mock_find.side_effect = find_side_effect

        # Configure mock download_pdf
        def download_side_effect(url, path):
            Path(path).write_bytes(b"%PDF-1.7\nMock Content" + b"A" * 2000)
            return True, 2020, None

        mock_download.side_effect = download_side_effect

        # Initialize application
        app = PaperHarborApp(
            reader=reader,
            dest_folder=self.dest_folder,
            skip_zotero_has_pdf=True,
            skip_existing_dest=True,
            report_path=self.report_path,
            request_delay=0
        )

        report_file = app.run()

        # 1. Check report file exists
        self.assertTrue(report_file.exists())

        # 2. Check summary counts
        summary = app.reporter.get_summary()
        self.assertEqual(summary["TOTAL_REFERENCES"], 3)
        self.assertEqual(summary[PaperStatus.SKIPPED_ALREADY_IN_ZOTERO.value], 1)
        self.assertEqual(summary[PaperStatus.DOWNLOADED.value], 1)
        self.assertEqual(summary[PaperStatus.PAYWALLED_OR_OA_NOT_FOUND.value], 1)

        # 3. Check CSV contents
        with open(report_file, "r", encoding="utf-8-sig") as f:
            rows = {r["Item_Key"]: r for r in csv.DictReader(f)}

        # Ref 1 was skipped because Zotero already has it
        self.assertEqual(rows["ZOT_HAS_PDF"]["Status"], "SKIPPED_ALREADY_IN_ZOTERO")

        # Ref 2 was downloaded with expected filename
        self.assertEqual(rows["ZOT_NEEDS_PDF"]["Status"], "DOWNLOADED")
        self.assertEqual(rows["ZOT_NEEDS_PDF"]["Saved_Filename"], "2025_Smith_Phishing_Detection.pdf")
        self.assertEqual(rows["ZOT_NEEDS_PDF"]["Source_Provider"], "Unpaywall")

        # Ref 3 recorded publisher URL
        self.assertEqual(rows["ZOT_PAYWALLED"]["Status"], "PAYWALLED_OR_OA_NOT_FOUND")
        self.assertEqual(rows["ZOT_PAYWALLED"]["Publisher_Or_Landing_URL"], "https://doi.org/10.1109/secret")


if __name__ == "__main__":
    unittest.main()
