"""Regressions from the 2026-10-31 failed-download report."""
import unittest
from unittest.mock import MagicMock
from paperharbor.models import Reference
from paperharbor.providers.author_copies import author_copy_candidates
from paperharbor.providers.landing import publisher_pdf_variants, LandingPageResolver
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.recovery import recovery_action, recovery_links, web_resource_kind


class ReportDomains(unittest.TestCase):
    def test_mdpi_suffixes_do_not_become_pdf_pdf_or_html_pdf(self):
        base = "https://www.mdpi.com/1099-4300/17/4/2367"
        for suffix in ("", "/", "/html", "/notes", "/pdf", "/pdf?version=1429602828"):
            self.assertEqual(publisher_pdf_variants(base + suffix), [base + "/pdf"])
        self.assertEqual(publisher_pdf_variants("https://evilmdpi.com/1099-4300/17/4/2367"), [])

    def test_mdpi_official_pdf_has_exact_identity_and_oa_status(self):
        ref = Reference(key="mdpi", doi="10.3390/e17042367",
                        title="An Entropy-Based Network Anomaly Detection Method")
        candidate = author_copy_candidates(ref)[0]
        self.assertIn("mdpi-res.com/d_attachment/entropy/entropy-17-02367/", candidate.url)
        self.assertEqual(candidate.oa_status, "gold")
        self.assertEqual(recovery_links(ref)[0]["label"], "MDPI official PDF")
        ref.title = "A different entropy paper"
        self.assertEqual(author_copy_candidates(ref), [])

    def test_mdpi_cdn_article_link_excludes_cited_pdf(self):
        resolver = LandingPageResolver(MagicMock())
        base = "https://www.mdpi.com/1099-4300/17/4/2367"
        asset = "https://mdpi-res.com/d_attachment/entropy/entropy-17-02367/article_deploy/entropy-17-02367-v2.pdf"
        response = MagicMock(status_code=200, url=base)
        response.headers = {"content-type": "text/html"}
        response.text = ('<meta name="citation_id" content="entropy-17-02367">'
                         '<a href="' + asset + '">PDF</a>'
                         '<section id="references"><a href="https://mdpi-res.com/cited.pdf">Download PDF</a></section>')
        resolver.session.get = MagicMock(return_value=response)
        urls = resolver.resolve(base)
        self.assertIn(asset, urls)
        self.assertNotIn("https://mdpi-res.com/cited.pdf", urls)

    def test_ieee_staging_and_elsevier_pii(self):
        urls = publisher_pdf_variants("http://xplorestaging.ieee.org/ielx7/8253410/10460360/10375702.pdf?arnumber=10375702")
        self.assertTrue(urls[0].startswith("https://ieeexplore.ieee.org/ielx7/"))
        self.assertIn("arnumber=10375702", urls[-1])
        urls = publisher_pdf_variants("https://linkinghub.elsevier.com/retrieve/pii/S016740482030078X")
        self.assertIn("/pii/S016740482030078X/pdfft", urls[0])

    def test_dataset_with_doi_is_a_web_resource(self):
        ref = Reference(key="dataset", item_type="dataset", doi="10.17632/c2gw7fy2j4.3",
                        url="https://data.mendeley.com/datasets/c2gw7fy2j4/3")
        self.assertEqual(web_resource_kind(ref), "Dataset")

    def test_publisher_denial_is_not_hidden_by_metadata_rate_limit(self):
        action = recovery_action("DOWNLOAD_FAILED", "HTTP 403; OpenAlex: HTTP 429")
        self.assertIn("browser", action)
        self.assertIn("Wait", recovery_action("DOWNLOAD_FAILED", "OpenAlex: HTTP 429"))

    def test_no_doi_still_queries_crossref_title_search(self):
        aggregator = ProviderAggregator()
        for name in ("author_copies", "acm", "researchgate", "unpaywall", "openalex", "europe_pmc", "arxiv", "semantic_scholar", "crossref"):
            getattr(aggregator, name).search = MagicMock(return_value=[])
        ref = Reference(key="missing", title="A long exact title without a DOI")
        aggregator.find_candidates(ref)
        aggregator.crossref.search.assert_called_once_with(ref)
