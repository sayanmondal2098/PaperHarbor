"""ACM, publisher-viewer, identity, and documentation regressions from report 215039."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from paperharbor.app import PaperHarborApp
from paperharbor.models import Reference, PaperStatus, CandidatePDF
from paperharbor.providers.acm import AcmProvider
from paperharbor.providers.crossref import CrossrefProvider
from paperharbor.providers.landing import LandingPageResolver, publisher_pdf_variants
from paperharbor.providers.matching import same_title, conflicts_with_doi
from paperharbor.providers.openalex import OpenAlexProvider
from paperharbor.recovery import ReportReader
from paperharbor.web import UploadedReferenceReader
from paperharbor.downloader import PdfDownloader


class TestAcmSupport(unittest.TestCase):
    def test_doi_and_acm_url_generate_pdf_and_epdf_candidates(self):
        provider = AcmProvider()
        doi = "10.1145/3133956.3133982"
        for reference in [Reference(key="a", doi=doi),
                          Reference(key="b", url=f"https://dl.acm.org/doi/abs/{doi}")]:
            candidates = provider.search(reference)
            self.assertEqual(candidates[0].url, f"https://dl.acm.org/doi/pdf/{doi}")
            self.assertEqual(candidates[1].url, f"https://dl.acm.org/doi/epdf/{doi}")
            self.assertFalse(candidates[1].is_direct_pdf)
        self.assertEqual(provider.search(Reference(key="c", doi="10.1109/not-acm")), [])

    def test_legacy_acm_links_and_epdf_variants(self):
        url = "https://dl.acm.org/citation.cfm?id=3133982"
        self.assertFalse(AcmProvider().search(Reference(key="a", url=url))[0].is_direct_pdf)
        self.assertEqual(publisher_pdf_variants("https://dl.acm.org/doi/epdf/10.1145/3133956.3133982"),
                         ["https://dl.acm.org/doi/pdf/10.1145/3133956.3133982"])
        self.assertEqual(publisher_pdf_variants("https://notdl.acm.org/doi/10.1145/a"), [])

    def test_crossref_unspecified_pdf_link_is_not_discarded(self):
        provider = CrossrefProvider()
        response = MagicMock(status_code=200)
        response.json.return_value = {"message": {"link": [
            {"URL": "https://dl.acm.org/doi/pdf/10.1145/a", "content-type": "unspecified"}]}}
        provider.session.get = MagicMock(return_value=response)
        candidates = provider.search(Reference(key="a", doi="10.1145/a"))
        self.assertEqual(candidates[0].url, "https://dl.acm.org/doi/pdf/10.1145/a")
        self.assertTrue(candidates[0].is_direct_pdf)

    def test_crossref_title_discovery_requires_close_title_match(self):
        title = "Beyond Blacklists: Learning to Detect Malicious Web Sites from Suspicious URLs"
        provider = CrossrefProvider()
        response = MagicMock(status_code=200)
        response.json.return_value = {"message": {"items": [
            {"title": ["A survey of malicious URL detection"], "DOI": "10.1/wrong"},
            {"title": [title], "DOI": "10.1145/1557019.1557153"}]}}
        provider.session.get = MagicMock(return_value=response)
        candidates = provider.search(Reference(key="a", title=title))
        self.assertEqual(candidates[0].url, "https://doi.org/10.1145/1557019.1557153")


class TestWorkIdentity(unittest.TestCase):
    def test_secure_aggregation_doi_collision_is_rejected(self):
        reference = Reference(key="a", doi="10.1145/3133956.3133982")
        self.assertTrue(conflicts_with_doi(reference, "https://doi.org/10.1145/3625343.3625344"))
        self.assertFalse(conflicts_with_doi(reference, "https://dl.acm.org/doi/pdf/10.1145/3133956.3133982"))
        self.assertFalse(conflicts_with_doi(reference, "https://authors.edu/preprint.pdf"))

    def test_title_matching_tolerates_punctuation_but_rejects_another_work(self):
        self.assertTrue(same_title("POSTER---CAIRN: Real-Time Diagnosis", "POSTER—CAIRN: Real Time Diagnosis"))
        self.assertFalse(same_title("Practical Secure Aggregation for Privacy-Preserving Machine Learning",
                                   "Practical and Efficient Secure Aggregation for Privacy-Preserving Machine Learning"))

    def test_openalex_title_fallback_cannot_replace_an_existing_doi(self):
        title = "Practical Secure Aggregation for Privacy-Preserving Machine Learning"
        provider = OpenAlexProvider()
        response = MagicMock(status_code=200)
        response.json.return_value = {"results": [{"title": title,
            "doi": "https://doi.org/10.1145/3625343.3625344",
            "best_oa_location": {"pdf_url": "https://repo.edu/wrong.pdf"}}]}
        provider.session.get = MagicMock(return_value=response)
        self.assertEqual(provider._search_by_title(title, expected_doi="10.1145/3133956.3133982"), [])

    def test_landing_page_citation_doi_conflict_is_rejected(self):
        resolver = LandingPageResolver(MagicMock())
        response = MagicMock(status_code=200, url="https://dl.acm.org/doi/10.1145/wrong")
        response.headers = {"content-type": "text/html"}
        response.text = '<meta name="citation_doi" content="10.1145/wrong"><meta name="citation_pdf_url" content="/wrong.pdf">'
        resolver.session.get = MagicMock(return_value=response)
        self.assertEqual(resolver.resolve(response.url, expected_doi="10.1145/right"), [])
        self.assertIn("conflicting DOI", resolver.last_error)


class TestOtherDomains(unittest.TestCase):
    def test_unreachable_hosts_have_a_shorter_connection_timeout(self):
        import requests
        downloader = PdfDownloader(timeout=30, retries=0)
        downloader.session.get = MagicMock(side_effect=requests.ConnectTimeout())
        with tempfile.TemporaryDirectory() as folder:
            result = downloader.download_pdf("https://repo.edu/a.pdf", Path(folder)/"a.pdf")
        self.assertIn("10s", result[2])
        self.assertEqual(downloader.session.get.call_args.kwargs["timeout"], (10, 30))

    def test_same_doi_failures_are_not_requested_twice_in_one_run(self):
        refs = [Reference(key="one", doi="10.1234/test"), Reference(key="two", doi="10.1234/TEST")]
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader(refs), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=([], None))
            app.aggregator.find_fallback_candidates = MagicMock(return_value=[])
            app.run()
            self.assertEqual(app.aggregator.find_candidates.call_count, 1)
            self.assertEqual([r.reference.key for r in app.reporter.results], ["one", "two"])

    def test_attached_item_skip_is_not_reused_for_an_unattached_duplicate(self):
        refs = [Reference(key="attached", doi="10.1234/test", has_zotero_pdf=True),
                Reference(key="missing", doi="10.1234/test")]
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader(refs), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=([], None))
            app.aggregator.find_fallback_candidates = MagicMock(return_value=[])
            app.run()
            app.aggregator.find_candidates.assert_called_once()
            self.assertEqual(app.reporter.results[0].status, PaperStatus.SKIPPED_ALREADY_IN_ZOTERO)
            self.assertEqual(app.reporter.results[1].status, PaperStatus.PAYWALLED_OR_OA_NOT_FOUND)

    def test_withdrawn_arxiv_notice_stops_further_downloads(self):
        ref = Reference(key="withdrawn", title="A withdrawn work", url="https://arxiv.org/abs/2605.26290")
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([ref]), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=([
                CandidatePDF(ref.url, "arXiv", is_direct_pdf=False)], ref.url))
            response = MagicMock(status_code=200, url=ref.url)
            response.headers = {"content-type": "text/html"}
            response.text = '<span class="error">This paper has been withdrawn by its author</span><td class="comments">The simulation results are incorrect.</td><meta name="citation_pdf_url" content="/pdf/2605.26290">'
            app.landing_resolver.session.get = MagicMock(return_value=response)
            app.downloader.download_pdf = MagicMock()
            app.run()
            self.assertEqual(app.reporter.results[0].status, PaperStatus.WITHDRAWN)
            self.assertIn("simulation results", app.reporter.results[0].notes)
            app.downloader.download_pdf.assert_not_called()

    def test_pdfjs_viewer_reveals_same_host_pdf(self):
        resolver = LandingPageResolver(MagicMock())
        response = MagicMock(status_code=200, url="https://repo.edu/article")
        response.headers = {"content-type": "text/html"}
        response.text = '<iframe src="/viewer.html?file=%2Fbitstream%2Fpaper.pdf"></iframe>'
        resolver.session.get = MagicMock(return_value=response)
        self.assertEqual(resolver.resolve(response.url), ["https://repo.edu/bitstream/paper.pdf"])

    def test_openreview_ieee_and_iacr_url_forms(self):
        self.assertEqual(publisher_pdf_variants("https://openreview.net/forum?id=abc"),
                         ["https://openreview.net/pdf?id=abc"])
        self.assertEqual(publisher_pdf_variants("https://eprint.iacr.org/2017/281"),
                         ["https://eprint.iacr.org/2017/281.pdf"])
        self.assertEqual(publisher_pdf_variants("https://ieeexplore.ieee.org/document/11152540"),
                         ["https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=11152540"])
        self.assertEqual(publisher_pdf_variants("https://inria.hal.science/hal-01092771"),
                         ["https://inria.hal.science/hal-01092771/document"])

    def test_documentation_and_dataset_links_are_not_missing_pdfs(self):
        refs = [
            Reference(key="f", url="https://flower.ai/docs/examples/flower-secure-aggregation.html"),
            Reference(key="k", url="https://kafka.apache.org/41/operations/kraft/"),
            Reference(key="u", url="https://archive.ics.uci.edu/dataset/967/phiusiil"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader(refs), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock()
            app.run()
            app.aggregator.find_candidates.assert_not_called()
            self.assertEqual(app.reporter.get_summary()["WEB_RESOURCE"], 3)
            self.assertTrue(all(r.status == PaperStatus.WEB_RESOURCE for r in app.reporter.results))

    def test_new_reports_preserve_source_url_and_item_type_for_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder)/"report.csv"
            with report.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "Item_Key", "Status", "Title", "DOI", "Original_URL", "Item_Type"])
                writer.writeheader()
                writer.writerow({"Item_Key": "f", "Status": "DOWNLOAD_FAILED", "Title": "Resource",
                    "Original_URL": "https://flower.ai/docs/example", "Item_Type": "webpage"})
            ref = ReportReader(report).get_references()[0]
            self.assertEqual(ref.url, "https://flower.ai/docs/example")
            self.assertEqual(ref.item_type, "webpage")


if __name__ == "__main__":
    unittest.main()
