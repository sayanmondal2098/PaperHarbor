"""ResearchGate link extraction, work identity, and download fallbacks."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from paperharbor.app import PaperHarborApp
from paperharbor.models import CandidatePDF, PaperStatus, Reference
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.providers.landing import LandingPageResolver, is_known_oa_host
from paperharbor.providers.researchgate import ResearchGateProvider, is_researchgate_url
from paperharbor.recovery import recovery_action, recovery_links
from paperharbor.web import UploadedReferenceReader


PAGE = "https://www.researchgate.net/publication/123456789_Test_Paper"
PDF = "https://www.researchgate.net/profile/Author/publication/123456789_Test_Paper/links/abc/Test-Paper.pdf"


class TestResearchGate(unittest.TestCase):
    def resolver(self, html, status=200):
        resolver = LandingPageResolver(MagicMock())
        response = MagicMock(status_code=status, url=PAGE)
        response.headers = {"content-type": "text/html"}
        response.text = html
        resolver.session.get = MagicMock(return_value=response)
        return resolver

    def test_recognizes_publication_and_direct_file_without_guessing(self):
        provider = ResearchGateProvider()
        for url, direct in [(PAGE, False), (PDF + "?download=1", True)]:
            candidates = provider.search(Reference(key="x", url=url))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].url, url)
            self.assertEqual(candidates[0].provider, "ResearchGate")
            self.assertEqual(candidates[0].is_direct_pdf, direct)
        for url in ["https://evilresearchgate.net/publication/123", "https://researchgate.net.evil.org/publication/123",
                    "https://www.researchgate.net/profile/Author", "https://www.researchgate.net/search/publication?q=paper"]:
            self.assertEqual(provider.search(Reference(key="x", url=url)), [])
        self.assertFalse(is_researchgate_url("file://researchgate.net/publication/123"))
        self.assertFalse(is_known_oa_host(PAGE))

    def test_metadata_and_same_publication_controls(self):
        resolver = self.resolver(f'<meta name="citation_pdf_url" content="{PDF}">'
            f'<a href="{PDF}">Download full-text PDF</a>')
        self.assertEqual(resolver.resolve(PAGE), [PDF])
        target = PAGE + "/links/abc/download"
        resolver = self.resolver(f'<a href="{target}">Download full-text</a>')
        self.assertEqual(resolver.resolve(PAGE), [target])

    def test_references_related_work_and_supplements_are_excluded(self):
        wrong = PDF.replace("123456789", "987654321")
        resolver = self.resolver(f'<section class="references"><a href="{PDF}">PDF</a></section>'
            f'<div class="related"><a href="{PDF}">Download full-text PDF</a></div>'
            f'<div id="supplement"><a href="{PDF}">PDF</a></div>'
            f'<a href="{wrong}">Download full-text PDF</a>'
            '<a href="https://elsewhere.edu/unrelated.pdf">Download full-text PDF</a>')
        self.assertEqual(resolver.resolve(PAGE), [])

    def test_conflicting_doi_or_title_is_rejected(self):
        for metadata, kwargs in [
            ('<meta name="citation_doi" content="10.1234/wrong">', {"expected_doi": "10.1234/right"}),
            ('<meta name="citation_title" content="A different paper">', {"expected_title": "Test Paper"}),
        ]:
            resolver = self.resolver(metadata + f'<meta name="citation_pdf_url" content="{PDF}">')
            self.assertEqual(resolver.resolve(PAGE, **kwargs), [])
            self.assertIn("conflicting", resolver.last_error)

    def test_request_only_and_denied_pages_provide_guidance_without_fake_links(self):
        for html, status in [('<button>Request full-text</button>', 200), ("Sign in", 403)]:
            resolver = self.resolver(html, status)
            self.assertEqual(resolver.resolve(PAGE), [])
            self.assertIn("ResearchGate", resolver.last_error)
            self.assertIn("Request full-text", recovery_action("DOWNLOAD_FAILED", resolver.last_error))
        self.assertIn("Wait", recovery_action("DOWNLOAD_FAILED", "ResearchGate: HTTP 429"))

    def test_aggregator_includes_supplied_researchgate_page(self):
        aggregator = ProviderAggregator()
        for provider in (aggregator.author_copies, aggregator.acm, aggregator.unpaywall,
                         aggregator.openalex, aggregator.europe_pmc, aggregator.arxiv,
                         aggregator.semantic_scholar, aggregator.crossref):
            provider.search = MagicMock(return_value=[])
        candidates, _ = aggregator.find_candidates(Reference(key="x", title="Test Paper", url=PAGE))
        self.assertTrue(any(c.provider == "ResearchGate" and c.url == PAGE for c in candidates))
        self.assertEqual(sum(c.url == PAGE for c in candidates), 1)

    def test_resolved_pdf_downloads_with_article_referer(self):
        ref = Reference(key="x", title="Test Paper", url=PAGE)
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([ref]), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=(ResearchGateProvider().search(ref), PAGE))
            app.aggregator.find_fallback_candidates = MagicMock(return_value=[])
            app.landing_resolver = self.resolver(f'<a href="{PDF}">Download full-text PDF</a>')
            app.downloader.download_pdf = MagicMock(return_value=(True, 2048, None))
            app.run()
            result = app.reporter.results[0]
            self.assertEqual(result.status, PaperStatus.DOWNLOADED)
            self.assertEqual(result.provider, "ResearchGate")
            self.assertEqual(result.pdf_url, PDF)
            self.assertEqual(app.downloader.download_pdf.call_args.kwargs["referer"], PAGE)

    def test_denial_continues_to_repository(self):
        ref = Reference(key="x", title="Test Paper", url=PAGE)
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([ref]), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=(ResearchGateProvider().search(ref), PAGE))
            app.aggregator.find_fallback_candidates = MagicMock(return_value=[CandidatePDF("https://repo.edu/paper.pdf", "Repository")])
            app.landing_resolver = self.resolver("Access denied", 403)
            app.downloader.download_pdf = MagicMock(return_value=(True, 2048, None))
            app.run()
            result = app.reporter.results[0]
            self.assertEqual(result.status, PaperStatus.DOWNLOADED)
            self.assertEqual(result.provider, "Repository")
            self.assertIn("ResearchGate", result.attempts[0]["error"])

    def test_recovery_links_include_publication_and_search(self):
        links = recovery_links(Reference(key="x", title="A paper & more", url=PAGE, doi="10.1234/a"))
        self.assertIn({"label": "ResearchGate publication", "url": PAGE}, links)
        search = next(link["url"] for link in links if link["label"] == "Search ResearchGate")
        self.assertTrue(search.endswith("q=10.1234/a"))


if __name__ == "__main__":
    unittest.main()
