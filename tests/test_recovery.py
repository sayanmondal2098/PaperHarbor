"""Regression tests driven by failed report entries and a wrong cited-PDF download."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paperharbor.app import PaperHarborApp
from paperharbor.downloader import PdfDownloader
from paperharbor.models import CandidatePDF, PaperStatus, Reference
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.providers.landing import LandingPageResolver, publisher_pdf_variants
from paperharbor.providers.openalex import OpenAlexProvider
from paperharbor.providers.unpaywall import UnpaywallProvider
from paperharbor.recovery import ReportReader
from paperharbor.web import UploadedReferenceReader, _build_reader


def response(status=200, chunks=None, text="", url="https://publisher.org/article"):
    result = MagicMock()
    result.status_code = status
    result.reason = "test"
    result.headers = {"content-type": "text/html"}
    result.text, result.url = text, url
    result.iter_content.side_effect = lambda **kwargs: iter(chunks or [])
    result.__enter__.return_value = result
    return result


class TestDownloadRecovery(unittest.TestCase):
    def test_retries_202_and_sends_referrer(self):
        with tempfile.TemporaryDirectory() as folder:
            downloader = PdfDownloader(retries=1)
            downloader.session.get = MagicMock(side_effect=[
                response(202, [b"<html>Processing</html>"]),
                response(200, [b"", b"%P", b"DF-1.7\n" + b"x" * 2048]),
            ])
            with patch("paperharbor.downloader.time.sleep"):
                ok, _, error = downloader.download_pdf("https://publisher.org/paper.pdf",
                    Path(folder) / "paper.pdf", referer="https://publisher.org/article")
            self.assertTrue(ok, error)
            self.assertEqual(downloader.session.get.call_count, 2)
            self.assertEqual(downloader.session.get.call_args.kwargs["headers"]["Referer"],
                             "https://publisher.org/article")

    def test_access_denied_is_not_repeated_and_large_retry_after_is_respected(self):
        with tempfile.TemporaryDirectory() as folder:
            downloader = PdfDownloader()
            denied = response(403)
            downloader.session.get = MagicMock(return_value=denied)
            self.assertFalse(downloader.download_pdf("https://example.org/a", Path(folder)/"a.pdf")[0])
            self.assertEqual(downloader.session.get.call_count, 1)
            limited = response(429)
            limited.headers["Retry-After"] = "120"
            downloader.session.get = MagicMock(return_value=limited)
            result = downloader.download_pdf("https://example.org/a", Path(folder)/"a.pdf")
            self.assertIn("120s wait", result[2])
            self.assertEqual(downloader.session.get.call_count, 1)


class TestLandingRecovery(unittest.TestCase):
    def resolver(self, html):
        resolver = LandingPageResolver(MagicMock())
        resolver.session.get = MagicMock(return_value=response(text=html))
        return resolver

    def test_article_metadata_wins_over_cited_report(self):
        resolver = self.resolver('''<meta name="citation_pdf_url" content="/correct.pdf">
          <section id="references"><a href="https://docs.apwg.org/report.pdf">Download PDF</a></section>''')
        self.assertEqual(resolver.resolve("https://publisher.org/article"), ["https://publisher.org/correct.pdf"])

    def test_citation_links_and_unrelated_external_pdfs_are_not_candidates(self):
        resolver = self.resolver('''<section class="references"><a href="/cited.pdf">PDF</a></section>
          <a href="https://elsewhere.org/unrelated.pdf">Reference report</a><a href="/actual.pdf">PDF</a>''')
        self.assertEqual(resolver.resolve("https://publisher.org/article"), ["https://publisher.org/actual.pdf"])

    def test_repository_bitstream_and_current_frontiers_form(self):
        resolver = self.resolver('<a href="/server/api/core/bitstreams/abc/content">Download paper.pdf</a>')
        self.assertIn("https://publisher.org/server/api/core/bitstreams/abc/content",
                      resolver.resolve("https://publisher.org/article"))
        url = "https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2024.1308634/full"
        self.assertEqual(publisher_pdf_variants(url), [url[:-4] + "pdf"])
        self.assertEqual(publisher_pdf_variants("https://evilmdpi.com/1099-4300/17/4/2367"), [])
        urls = publisher_pdf_variants("https://onlinelibrary.wiley.com/doi/10.1002/a;2-v")
        self.assertIn("https://onlinelibrary.wiley.com/doi/pdf/10.1002/a;2-v", urls)


class TestProviderRecovery(unittest.TestCase):
    def test_provider_credentials_are_scoped_to_their_hosts(self):
        provider = OpenAlexProvider()
        provider.session.get = MagicMock(return_value=response())
        with patch.dict("os.environ", {"OPENALEX_API_KEY": "oa-test", "SEMANTIC_SCHOLAR_API_KEY": "ss-test"}):
            provider.get("https://api.openalex.org/works")
            self.assertEqual(provider.session.get.call_args.kwargs["headers"], {"Authorization": "Bearer oa-test"})
            self.assertFalse(provider.session.get.call_args.kwargs["allow_redirects"])
            provider.get("https://api.semanticscholar.org/graph/v1/paper")
            self.assertEqual(provider.session.get.call_args.kwargs["headers"], {"x-api-key": "ss-test"})
            provider.get("https://other.example/paper")
            self.assertEqual(provider.session.get.call_args.kwargs["headers"], {})

    def test_best_landing_location_is_not_lost(self):
        provider = OpenAlexProvider()
        candidates = provider._extract_candidates_from_work({
            "open_access": {"oa_status": "green"},
            "best_oa_location": {"landing_page_url": "https://repository.edu/item"},
        })
        self.assertEqual(candidates[0].url, "https://repository.edu/item")
        self.assertFalse(candidates[0].is_direct_pdf)
        provider = UnpaywallProvider()
        result = response()
        result.json.return_value = {"is_oa": True, "oa_status": "green",
            "best_oa_location": {"url_for_landing_page": "https://repository.edu/item"}}
        provider.session.get = MagicMock(return_value=result)
        self.assertEqual(provider.search(Reference(key="x", doi="10.1/test"))[0].url,
                         "https://repository.edu/item")

    def test_fallback_queries_remaining_providers_even_after_a_direct_candidate(self):
        aggregator = ProviderAggregator()
        providers = [aggregator.openalex, aggregator.europe_pmc, aggregator.arxiv,
                     aggregator.semantic_scholar, aggregator.crossref,
                     aggregator.author_copies, aggregator.acm, aggregator.unpaywall]
        for provider in providers:
            provider.search = MagicMock(return_value=[])
        aggregator._queried = {aggregator.openalex.name}
        aggregator.find_fallback_candidates(Reference(key="x", doi="10.1234/test"))
        providers[0].search.assert_not_called()
        for provider in providers[1:]:
            provider.search.assert_called_once()

    def test_failed_first_url_recovers_from_second_provider_and_records_attempts(self):
        ref = Reference(key="x", title="A paper", doi="10.1234/a")
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([ref]), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=([
                CandidatePDF("https://publisher.org/a.pdf", "First", oa_status="gold")], ref.publisher_url))
            app.aggregator.find_fallback_candidates = MagicMock(return_value=[
                CandidatePDF("https://repository.edu/a.pdf", "Repository")])
            app.downloader.download_pdf = MagicMock(side_effect=[(False, 0, "HTTP 403"), (True, 2048, None)])
            app.run()
            result = app.reporter.results[0]
            self.assertEqual(result.status, PaperStatus.DOWNLOADED)
            self.assertEqual(len(result.attempts), 2)
            with app.reporter.output_path.open(encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(len(json.loads(row["Attempt_Log"])), 2)

    def test_reference_error_does_not_stop_later_papers(self):
        refs = [Reference(key="1"), Reference(key="2")]
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader(refs), Path(folder), request_delay=0)
            with patch.object(app, "_process_single_reference", side_effect=[RuntimeError("bad item"), None]) as process, self.assertLogs("paperharbor.app", level="ERROR"):
                app.run()
            self.assertEqual(process.call_count, 2)
            self.assertEqual(app.reporter.results[0].status, PaperStatus.ERROR)


class TestReportRetry(unittest.TestCase):
    def test_report_upload_only_retries_unresolved_rows(self):
        content = "Item_Key,Status,Title,DOI,Year,First_Author\n"
        for index, status in enumerate(["DOWNLOADED", "DOWNLOAD_FAILED", "OA_BLOCKED_MANUAL",
                                        "PAYWALLED_OR_OA_NOT_FOUND", "SKIPPED_ALREADY_IN_DEST"]):
            content += f"{index},{status},Paper {index},10.1234/{index},2024,Smith\n"
        reader = _build_reader({"upload_name": "report.csv", "upload_content": content})
        self.assertEqual(len(reader.get_references()), 2)
        reader = _build_reader({"upload_name": "report.csv", "upload_content": content, "retry_not_found": True})
        self.assertEqual(len(reader.get_references()), 3)


if __name__ == "__main__":
    unittest.main()
