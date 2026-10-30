"""Manual PDFs are recognized by content, not just a plausible filename."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from pypdf import PdfWriter
from paperharbor.app import PaperHarborApp
from paperharbor.local_files import LocalPdfIndex
from paperharbor.models import Reference, PaperStatus
from paperharbor.web import UploadedReferenceReader


class LocalFiles(unittest.TestCase):
    title = "A precise title for the intended research paper"

    def pdf(self, path, doi="10.1234/intended", title=None):
        writer = PdfWriter()
        writer.add_blank_page(width=600, height=800)
        writer.add_metadata({"/Title": title or self.title, "/doi": doi, "/Keywords": "x" * 2048})
        writer.write(path)

    def test_content_match_keeps_manual_name_and_avoids_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "browser-download.pdf"
            self.pdf(path)
            ref = Reference(key="a", title=self.title, doi="10.1234/intended")
            app = PaperHarborApp(UploadedReferenceReader([ref]), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(side_effect=AssertionError("No network expected"))
            app.run()
            self.assertEqual(app.reporter.results[0].status, PaperStatus.SKIPPED_ALREADY_IN_DEST)
            self.assertEqual(app.reporter.results[0].saved_filename, path.name)
            app.aggregator.find_candidates.assert_not_called()

    def test_same_title_wrong_doi_and_same_doi_wrong_title_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            self.pdf(Path(folder) / "one.pdf", doi="10.1234/intended-extra")
            self.pdf(Path(folder) / "two.pdf", title="A completely unrelated research paper")
            ref = Reference(key="a", title=self.title, doi="10.1234/intended")
            self.assertIsNone(LocalPdfIndex(folder).find(ref))

    def test_numeric_acm_name_still_requires_matching_title(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "235815.235821.pdf"
            self.pdf(path, doi="", title="Some unrelated paper about a different topic")
            ref = Reference(key="a", title=self.title, doi="10.1145/235815.235821")
            self.assertIsNone(LocalPdfIndex(folder).find(ref))
            self.pdf(path, doi="")
            self.assertEqual(LocalPdfIndex(folder).find(ref), path)

    def test_corrupt_files_do_not_stop_other_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "bad.pdf").write_bytes(b"<html>" + b"x" * 2048)
            path = Path(folder) / "good.pdf"
            self.pdf(path)
            ref = Reference(key="a", title=self.title, doi="10.1234/intended")
            self.assertEqual(LocalPdfIndex(folder).find(ref), path)
