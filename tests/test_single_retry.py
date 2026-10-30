"""A single-paper linked retry is bounded to one extra PDF request."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from paperharbor.app import PaperHarborApp
from paperharbor.models import Reference, DownloadResult, PaperStatus
from paperharbor.web import UploadedReferenceReader


class TestSingleRetry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ref = Reference(key="paper", title="A paper", doi="10.1234/test")
        self.app = PaperHarborApp(UploadedReferenceReader([self.ref]), Path(self.temp.name),
                                 request_delay=0, auto_retry_once=True)

    def tearDown(self):
        self.temp.cleanup()

    def fail_initial(self, reference):
        self.app.reporter.record(DownloadResult(
            reference=reference, status=PaperStatus.OA_BLOCKED_MANUAL,
            notes="Initial candidates failed.", attempts=[
                {"provider": "Publisher", "url": "https://dl.acm.org/doi/pdf/10.1234/test",
                 "stage": "download", "error": "HTTP 403"},
                {"provider": "Repository", "url": "https://repository.edu/paper.pdf",
                 "stage": "download", "error": "Network error"},
            ]))

    def test_retry_prefers_repository_succeeds_and_keeps_one_result(self):
        self.app._process_single_reference = MagicMock(side_effect=self.fail_initial)
        def download(url, path, **kwargs):
            self.assertEqual(url, "https://repository.edu/paper.pdf")
            self.assertEqual(self.app.downloader.retries, 0)
            Path(path).write_bytes(b"%PDF-1.4\n" + b"x" * 2048)
            return True, 2057, None
        self.app.downloader.download_pdf = MagicMock(side_effect=download)
        self.app.run()
        self.app._process_single_reference.assert_called_once()
        self.app.downloader.download_pdf.assert_called_once()
        self.assertEqual(len(self.app.reporter.results), 1)
        result = self.app.reporter.results[0]
        self.assertEqual(result.status, PaperStatus.DOWNLOADED)
        self.assertEqual(result.auto_retry_count, 1)
        self.assertEqual(result.auto_retry_url, "https://repository.edu/paper.pdf")
        self.assertEqual(result.attempts[-1]["stage"], "auto_retry")
        self.assertEqual(self.app.downloader.retries, 2)

    def test_failed_retry_is_never_repeated(self):
        self.app._process_single_reference = MagicMock(side_effect=self.fail_initial)
        self.app.downloader.download_pdf = MagicMock(return_value=(False, 0, "HTTP 403"))
        self.app.run()
        self.app._retry_single_once(self.ref)
        self.app.downloader.download_pdf.assert_called_once()
        self.assertEqual(self.app.reporter.results[0].auto_retry_count, 1)
        self.assertEqual(len(self.app.reporter.results), 1)
        self.assertIn("retry 1/1 failed", self.app.reporter.results[0].notes)

    def test_opt_out_and_batch_inputs_do_not_trigger_auto_retry(self):
        self.app._process_single_reference = MagicMock(side_effect=self.fail_initial)
        self.app.downloader.download_pdf = MagicMock()
        self.app.auto_retry_once = False
        self.app.run()
        self.app.downloader.download_pdf.assert_not_called()
        self.app.auto_retry_once = True
        self.app.reader.references.append(Reference(key="second"))
        self.app.run()
        self.app.downloader.download_pdf.assert_not_called()

    def test_terminal_results_are_not_retried_and_no_link_does_not_guess(self):
        self.app.downloader.download_pdf = MagicMock()
        for status in (PaperStatus.DOWNLOADED, PaperStatus.WITHDRAWN,
                       PaperStatus.WEB_RESOURCE, PaperStatus.SKIPPED_ALREADY_IN_DEST):
            self.app.reporter.results = [DownloadResult(self.ref, status)]
            self.app._retry_single_once(self.ref)
        self.app.downloader.download_pdf.assert_not_called()
        self.app.reporter.results = [DownloadResult(self.ref, PaperStatus.DOWNLOAD_FAILED)]
        self.app._retry_single_once(self.ref)
        self.app.downloader.download_pdf.assert_not_called()
        self.assertIn("no direct PDF link", self.app.reporter.results[0].notes)

    def test_explicit_link_is_preserved_and_exceptions_still_use_the_limit(self):
        self.app.pdf_overrides = {self.ref.key: "https://authors.edu/alternate.pdf"}
        self.fail_initial(self.ref)
        self.app.downloader.download_pdf = MagicMock(side_effect=RuntimeError("Disk error"))
        self.app._retry_single_once(self.ref)
        self.app._retry_single_once(self.ref)
        self.app.downloader.download_pdf.assert_called_once()
        self.assertEqual(self.app.downloader.download_pdf.call_args.args[0],
                         "https://authors.edu/alternate.pdf")
        self.assertEqual(self.app.downloader.retries, 2)
        self.assertIn("Disk error", self.app.reporter.results[0].notes)

    def test_rate_limited_url_is_not_immediately_requested_again(self):
        self.app.reporter.results = [DownloadResult(
            self.ref, PaperStatus.DOWNLOAD_FAILED, attempts=[
                {"stage": "download", "url": "https://repo.edu/paper.pdf",
                 "error": "HTTP 429; server requests a 120s wait. Retry later."}])]
        self.app.downloader.download_pdf = MagicMock()
        self.app._retry_single_once(self.ref)
        self.app.downloader.download_pdf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
