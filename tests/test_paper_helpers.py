"""Single-paper, diagnostics, publisher identities, and rate-limit helper contracts."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from paperharbor.cli import parse_args
from paperharbor.diagnose import diagnose
from paperharbor.downloader import PdfDownloader
from paperharbor.http_helpers import retry_after_seconds
from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.landing import LandingPageResolver, publisher_pdf_variants
from paperharbor.providers.matching import normalize_identifier
from paperharbor.providers.openalex import OpenAlexProvider
from paperharbor.single_paper import SinglePaperReader
from paperharbor.web import _build_reader


DOI = "10.1145/1557019.1557153"
TITLE = "Beyond Blacklists: Learning to Detect Malicious Web Sites from Suspicious URLs"


class TestSinglePaper(unittest.TestCase):
    def response(self, **work):
        response = MagicMock(status_code=200)
        response.json.return_value = {"message": {
            "DOI": DOI, "title": [TITLE],
            "author": [{"family": "Ma", "given": "Justin"}],
            "published": {"date-parts": [[2009]]}, **work}}
        return response

    def test_identifiers_include_acm_aliases_and_encoded_dois(self):
        for value in [DOI, "DOI: " + DOI,
                      "https://doi.org/" + DOI,
                      "https://doi.acm.org/" + DOI,
                      "https://dl.acm.org/doi/epdf/" + DOI + "?download=true",
                      "https://dl.acm.org/doi/" + DOI.replace("/", "%2F")]:
            with self.subTest(value=value):
                self.assertEqual(normalize_identifier(value)[0], DOI)
        for value in ["", "not a DOI", "javascript:alert(1)", "file:///paper.pdf",
                      "https://user:password@example.org/paper"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_identifier(value)

    def test_crossref_metadata_and_reader_cache(self):
        reader = SinglePaperReader(DOI)
        reader.session.get = MagicMock(return_value=self.response())
        ref = reader.get_references()[0]
        self.assertEqual((ref.title, ref.first_author, ref.year), (TITLE, "Ma", 2009))
        self.assertIs(reader.get_references()[0], ref)
        reader.session.get.assert_called_once()

    def test_metadata_failure_can_use_an_explicit_title(self):
        reader = SinglePaperReader(DOI, title=TITLE)
        reader.session.get = MagicMock(side_effect=requests.Timeout())
        self.assertEqual(reader.get_references()[0].title, TITLE)
        reader = SinglePaperReader(DOI)
        reader.session.get = MagicMock(side_effect=requests.Timeout())
        with self.assertRaisesRegex(ValueError, "metadata"):
            reader.get_references()

    def test_conflicting_metadata_doi_is_rejected(self):
        reader = SinglePaperReader(DOI)
        reader.session.get = MagicMock(return_value=self.response(DOI="10.1145/wrong"))
        with self.assertRaisesRegex(ValueError, "conflicting DOI"):
            reader.get_references()

    def test_legacy_url_with_title_remains_usable_when_blocked(self):
        reader = SinglePaperReader("https://dl.acm.org/citation.cfm?id=1557153", title=TITLE)
        reader.session.get = MagicMock(side_effect=requests.HTTPError())
        self.assertEqual(reader.get_references()[0].url,
                         "https://dl.acm.org/citation.cfm?id=1557153")

    def test_web_and_cli_expose_single_paper_sources(self):
        self.assertIsInstance(_build_reader({"paper_identifier": DOI, "paper_title": TITLE}), SinglePaperReader)
        self.assertEqual(parse_args(["--doi", DOI, "-d", "papers"]).doi, DOI)
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            parse_args(["--doi", DOI, "--url", "https://example.org", "-d", "papers"])
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            parse_args(["--title", TITLE, "-d", "papers"])


class TestDiagnosticHelper(unittest.TestCase):
    def test_diagnostic_deduplicates_and_rejects_conflicting_dois(self):
        reference = Reference(key="paper", title=TITLE, doi=DOI)
        with patch("paperharbor.diagnose.SinglePaperReader") as reader, patch(
                "paperharbor.diagnose.ProviderAggregator") as aggregator:
            reader.return_value.get_references.return_value = [reference]
            valid = CandidatePDF("https://authors.edu/paper.pdf", "Author")
            wrong = CandidatePDF("https://dl.acm.org/doi/pdf/10.1145/wrong", "Wrong")
            engine = aggregator.return_value
            engine.find_candidates.return_value = ([valid], reference.publisher_url)
            engine.find_fallback_candidates.return_value = [valid, wrong]
            engine.errors = ["Example service: HTTP 429"]
            result = diagnose(DOI, expanded=True)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["rejected_doi_conflicts"], [wrong.url])
        self.assertIn("Discovery only", result["note"])
        self.assertEqual(result["provider_errors"], ["Example service: HTTP 429"])


class TestDownloadHelpers(unittest.TestCase):
    def test_http_date_retry_after_and_invalid_values(self):
        now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(retry_after_seconds("Fri, 30 Oct 2026 12:00:15 GMT", now), 15)
        self.assertEqual(retry_after_seconds("120"), 120)
        self.assertEqual(retry_after_seconds("Fri, 30 Oct 2026 11:00:00 GMT", now), 0)
        self.assertIsNone(retry_after_seconds("invalid"))

    def test_pdf_redirect_cannot_change_work_identity(self):
        downloader = PdfDownloader(retries=0)
        response = MagicMock(status_code=200)
        response.url = "https://dl.acm.org/doi/pdf/10.1145/wrong"
        response.__enter__.return_value = response
        downloader.session.get = MagicMock(return_value=response)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"paper.pdf"
            result = downloader.download_pdf("https://authors.edu/paper.pdf", path, expected_doi=DOI)
            self.assertFalse(result[0])
            self.assertIn("conflicting DOI", result[2])
            self.assertFalse(path.exists())

    def test_metadata_429_cooldown_prevents_repeated_network_calls(self):
        provider = OpenAlexProvider()
        response = MagicMock(status_code=429)
        response.headers = {"Retry-After": "60"}
        provider.session.get = MagicMock(return_value=response)
        provider.get("https://api.openalex.org/works")
        with self.assertRaises(requests.RequestException):
            provider.get("https://api.openalex.org/works")
        provider.session.get.assert_called_once()

    def test_author_page_selects_exact_title_instead_of_other_papers_or_slides(self):
        resolver = LandingPageResolver(MagicMock())
        response = MagicMock(status_code=200, url="https://authors.edu/pubs")
        response.headers = {"content-type": "text/html"}
        response.text = f'<a href="/unrelated.pdf">Other research</a><a href="/paper.pdf">{TITLE}</a><a href="/slides.pdf">PDF</a>'
        resolver.session.get = MagicMock(return_value=response)
        self.assertEqual(resolver.resolve(response.url, expected_title=TITLE), ["https://authors.edu/paper.pdf"])
        response.text = '<a href="/one.pdf">PDF</a><a href="/two.pdf">PDF</a>'
        self.assertEqual(resolver.resolve(response.url, expected_title=TITLE), [])
        self.assertIn("Multiple PDF links", resolver.last_error)

    def test_supported_publisher_routes_remain_available(self):
        cases = {
            "https://dl.acm.org/doi/full/10.1145/1557019.1557153": "/doi/pdf/10.1145/",
            "https://onlinelibrary.wiley.com/doi/abs/10.1002/example;2-v": "/doi/pdf/",
            "https://www.mdpi.com/1099-4300/17/4/2367": "/pdf",
            "https://www.frontiersin.org/journals/computer-science/articles/10.3389/example/full": "/pdf",
            "https://link.springer.com/article/10.1007/example": "/content/pdf/",
            "https://arxiv.org/abs/1412.6572": "/pdf/",
            "https://ieeexplore.ieee.org/document/11152540": "/stampPDF/",
            "https://inria.hal.science/hal-01092771": "/document",
            "https://openreview.net/forum?id=example": "/pdf?",
            "https://eprint.iacr.org/2017/281": ".pdf",
        }
        for url, fragment in cases.items():
            with self.subTest(url=url):
                self.assertTrue(any(fragment in link for link in publisher_pdf_variants(url)))


if __name__ == "__main__":
    unittest.main()
