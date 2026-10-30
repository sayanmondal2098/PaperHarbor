"""Unit tests for Open Access search providers and aggregator."""

import unittest
from unittest.mock import MagicMock, patch

from paperharbor.models import Reference
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.providers.arxiv import ArxivProvider
from paperharbor.providers.openalex import OpenAlexProvider
from paperharbor.providers.unpaywall import UnpaywallProvider


class TestProviders(unittest.TestCase):
    def test_arxiv_id_extraction(self):
        arxiv = ArxivProvider()

        # From DOI
        ref1 = Reference(key="1", doi="10.48550/arXiv.2301.12345")
        self.assertEqual(arxiv._extract_arxiv_id(ref1), "2301.12345")

        # From URL
        ref2 = Reference(key="2", url="https://arxiv.org/abs/2105.09876")
        self.assertEqual(arxiv._extract_arxiv_id(ref2), "2105.09876")

        # From Extra
        ref3 = Reference(key="3", extra="arxiv: 2402.11223\nNote: test")
        self.assertEqual(arxiv._extract_arxiv_id(ref3), "2402.11223")

        cands = arxiv.search(ref1)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].url, "https://arxiv.org/pdf/2301.12345.pdf")
        self.assertEqual(cands[0].provider, "arXiv")

    @patch("requests.Session.get")
    def test_unpaywall_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://publisher.org/paper.pdf",
                "url_for_landing_page": "https://publisher.org/article",
                "version": "publishedVersion"
            },
            "oa_locations": [
                {
                    "url_for_pdf": "https://repository.org/fallback.pdf",
                    "url_for_landing_page": "https://repository.org/item"
                }
            ]
        }
        mock_get.return_value = mock_resp

        provider = UnpaywallProvider()
        ref = Reference(key="U1", doi="10.1000/182")
        cands = provider.search(ref)

        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0].url, "https://publisher.org/paper.pdf")
        self.assertEqual(cands[0].provider, "Unpaywall")
        self.assertEqual(cands[1].url, "https://repository.org/fallback.pdf")

    @patch("requests.Session.get")
    def test_unpaywall_paywalled(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "is_oa": False,
            "oa_status": "closed"
        }
        mock_get.return_value = mock_resp

        provider = UnpaywallProvider()
        ref = Reference(key="U2", doi="10.1000/paywalled")
        cands = provider.search(ref)
        self.assertEqual(len(cands), 0)

    @patch("requests.Session.get")
    def test_openalex_by_doi(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "open_access": {"is_oa": True, "oa_status": "hybrid"},
            "best_oa_location": {
                "pdf_url": "https://openalex.org/article.pdf",
                "landing_page_url": "https://openalex.org/work",
                "version": "publishedVersion"
            },
            "locations": []
        }
        mock_get.return_value = mock_resp

        provider = OpenAlexProvider()
        ref = Reference(key="OA1", doi="10.1016/j.jneumeth.2020.108999")
        cands = provider.search(ref)

        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].url, "https://openalex.org/article.pdf")
        self.assertEqual(cands[0].provider, "OpenAlex")

    def test_aggregator_publisher_url(self):
        aggregator = ProviderAggregator()
        ref = Reference(key="REF1", doi="10.1145/3372297.3417238")
        
        # When paywalled, publisher_url should be official DOI link
        self.assertEqual(ref.publisher_url, "https://doi.org/10.1145/3372297.3417238")


if __name__ == "__main__":
    unittest.main()
