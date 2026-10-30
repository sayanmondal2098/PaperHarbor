"""Author copies remain available independently of publisher/index availability."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from paperharbor.app import PaperHarborApp
from paperharbor.models import CandidatePDF, PaperStatus, Reference
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.providers.author_copies import author_copy_candidates, source_catalog
from paperharbor.recovery import recovery_links
from paperharbor.web import UploadedReferenceReader


TITLE = "Beyond Blacklists: Learning to Detect Malicious Web Sites from Suspicious URLs"
DOI = "10.1145/1557019.1557153"
AUTHOR_PDF = "https://cseweb.ucsd.edu/~jtma/papers/beyondbl-kdd2009.pdf"


class TestAuthorCopies(unittest.TestCase):
    def reference(self, **kwargs):
        return Reference(key="ma2009", title=TITLE, doi=DOI, first_author="Ma", year=2009, **kwargs)

    def test_catalog_carries_evidence_and_exact_identifiers(self):
        for doi, entry in source_catalog().items():
            self.assertTrue(doi.startswith("10.1145/"))
            self.assertTrue(entry["title"])
            self.assertTrue(entry["source_page"].startswith("https://"))
            self.assertTrue(entry["verified_on"])
            self.assertTrue(all(url.startswith("https://") for url in entry["pdf_urls"]))
        self.assertEqual(author_copy_candidates(self.reference())[0].url, AUTHOR_PDF)

    def test_title_conflicts_and_unknown_dois_are_not_matched(self):
        self.assertEqual(author_copy_candidates(Reference(key="wrong", title="An unrelated paper", doi=DOI)), [])
        self.assertEqual(author_copy_candidates(Reference(key="unknown", title=TITLE, doi="10.1145/unknown")), [])
        self.assertEqual(author_copy_candidates(Reference(key="no-doi", title=TITLE)), [])

    def test_short_title_and_acm_url_are_supported(self):
        short = Reference(key="short", title="Beyond blacklists", doi=DOI.upper())
        self.assertEqual(author_copy_candidates(short)[0].url, AUTHOR_PDF)
        url_only = Reference(key="url", title=TITLE, url=f"https://dl.acm.org/doi/{DOI}")
        self.assertEqual(author_copy_candidates(url_only)[0].url, AUTHOR_PDF)

    def test_2011_acm_paper_has_an_author_copy_independent_of_escholarship(self):
        ref = Reference(key="ma2011", title="Learning to Detect Malicious URLs", doi="10.1145/1961189.1961202")
        self.assertEqual(author_copy_candidates(ref)[0].url,
                         "https://cseweb.ucsd.edu/~savage/papers/TIST11.pdf")

    def test_normal_pipeline_downloads_author_copy_without_overrides_or_metadata(self):
        reference = self.reference()
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([reference]), Path(folder), request_delay=0)
            for provider in (app.aggregator.unpaywall, app.aggregator.openalex,
                             app.aggregator.semantic_scholar, app.aggregator.crossref):
                provider.search = MagicMock(side_effect=AssertionError("Known author copy should be tried first"))
            def download(url, path, **kwargs):
                self.assertEqual(url, AUTHOR_PDF)
                payload = b"%PDF-1.4\n" + b"x" * 2048
                Path(path).write_bytes(payload)
                return True, len(payload), None
            app.downloader.download_pdf = MagicMock(side_effect=download)
            app.run()
            result = app.reporter.results[0]
            self.assertEqual(result.status, PaperStatus.DOWNLOADED)
            self.assertEqual(result.provider, "Verified author copies")
            self.assertTrue(Path(result.saved_path).is_file())
            app.aggregator.unpaywall.search.assert_not_called()
            app.aggregator.openalex.search.assert_not_called()

    def test_live_discovery_still_runs_after_reviewed_copies_fail(self):
        aggregator = ProviderAggregator()
        reference = self.reference()
        first, _ = aggregator.find_candidates(reference)
        self.assertEqual(first[0].url, AUTHOR_PDF)
        for provider in (aggregator.unpaywall, aggregator.openalex, aggregator.europe_pmc,
                         aggregator.arxiv, aggregator.semantic_scholar, aggregator.crossref):
            provider.search = MagicMock(return_value=[])
        fallback = CandidatePDF(url="https://repo.edu/new.pdf", provider="Unpaywall", oa_status="green")
        aggregator.unpaywall.search.return_value = [fallback]
        self.assertIn(fallback, aggregator.find_fallback_candidates(reference))
        aggregator.unpaywall.search.assert_called_once_with(reference)

    def test_manual_results_include_author_links_alongside_acm(self):
        links = recovery_links(self.reference())
        self.assertEqual(links[0]["url"], AUTHOR_PDF)
        self.assertTrue(any(link["label"] == "ACM Digital Library" for link in links))


if __name__ == "__main__":
    unittest.main()
