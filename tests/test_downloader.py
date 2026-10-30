"""Unit tests for PDF downloader and magic byte verification."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paperharbor.downloader import PdfDownloader


class TestPdfDownloader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dest_folder = Path(self.temp_dir.name)
        self.downloader = PdfDownloader(timeout=5)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("requests.Session.get")
    def test_download_valid_pdf(self, mock_get):
        # Prepare mock response with %PDF- header and sufficient length
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Valid PDF header + padding
        valid_pdf_content = b"%PDF-1.7\n" + b"1 0 obj\n<< /Type /Catalog >>\nendobj\n" + b"A" * 2000
        mock_resp.iter_content.return_value = [valid_pdf_content[:500], valid_pdf_content[500:]]
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp

        target_file = self.dest_folder / "test_paper.pdf"
        success, size_bytes, err = self.downloader.download_pdf("https://example.com/paper.pdf", target_file)

        self.assertTrue(success)
        self.assertIsNone(err)
        self.assertEqual(size_bytes, len(valid_pdf_content))
        self.assertTrue(target_file.exists())
        self.assertTrue(target_file.read_bytes().startswith(b"%PDF-"))

    @patch("requests.Session.get")
    def test_reject_html_paywall_page(self, mock_get):
        # Mock HTML paywall login page returning 200 OK
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        html_content = b"<!DOCTYPE html><html><head><title>Sign In to Publisher</title></head><body>Paywall</body></html>"
        mock_resp.iter_content.return_value = [html_content]
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp

        target_file = self.dest_folder / "fake_paper.pdf"
        success, size_bytes, err = self.downloader.download_pdf("https://example.com/paywalled", target_file)

        self.assertFalse(success)
        self.assertIn("not a valid PDF", err)
        self.assertFalse(target_file.exists())

    @patch("requests.Session.get")
    def test_reject_truncated_or_empty_file(self, mock_get):
        # Mock a file that has %PDF- but is only 50 bytes (corrupted)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        short_content = b"%PDF-corrupted"
        mock_resp.iter_content.return_value = [short_content]
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp

        target_file = self.dest_folder / "corrupted.pdf"
        success, size_bytes, err = self.downloader.download_pdf("https://example.com/bad", target_file, min_bytes=1024)

        self.assertFalse(success)
        self.assertIn("too small", err)
        self.assertFalse(target_file.exists())

    @patch("requests.Session.get")
    def test_handle_404_or_500_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.reason = "Not Found"
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp

        target_file = self.dest_folder / "missing.pdf"
        success, size_bytes, err = self.downloader.download_pdf("https://example.com/missing", target_file)

        self.assertFalse(success)
        self.assertIn("HTTP 404", err)
        self.assertFalse(target_file.exists())


if __name__ == "__main__":
    unittest.main()
