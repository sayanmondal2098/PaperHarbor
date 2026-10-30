"""Scholar discovery is automatic, identity matched, and bounded on blocks."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from paperharbor.app import PaperHarborApp
from paperharbor.models import Reference, CandidatePDF, PaperStatus
from paperharbor.providers.google_scholar import GoogleScholarProvider, external_url
from paperharbor.web import UploadedReferenceReader


TITLE = "An Entropy-Based Network Anomaly Detection Method"
DOI = "10.3390/e17042367"
PDF = "https://repository.edu/files/entropy.pdf"


class ScholarTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"SERPAPI_API_KEY": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.provider = GoogleScholarProvider()
        self.ref = Reference(key="a", title=TITLE, doi=DOI)

    def response(self, html="", status=200):
        response = MagicMock(status_code=status, text=html, url="https://scholar.google.com/scholar")
        response.headers = {}
        return response

    def results(self, title=TITLE, pdf=PDF):
        return ('<div id="gs_res_ccl_mid"><div class="gs_r gs_or gs_scl">'
                '<div class="gs_or_ggsm"><a href="' + pdf + '">[PDF] repository.edu</a></div>'
                '<h3 class="gs_rt"><span class="gs_ctc">[PDF]</span><a href="https://doi.org/' + DOI + '">'
                + title + '</a></h3></div></div>')

    def test_pdf_is_first_landing_second_and_query_is_exact_title(self):
        self.provider.session.get = MagicMock(return_value=self.response(self.results()))
        found = self.provider.search(self.ref)
        self.assertEqual(found[0].url, PDF)
        self.assertTrue(found[0].is_direct_pdf)
        self.assertEqual(found[1].url, 'https://doi.org/' + DOI)
        self.assertFalse(found[1].is_direct_pdf)
        self.assertEqual(self.provider.session.get.call_args.kwargs['params']['q'], '"' + TITLE + '"')
        self.assertEqual(self.provider.search(self.ref), found)
        self.provider.session.get.assert_called_once()

    def test_unrelated_result_and_conflicting_doi_are_rejected(self):
        for html in (self.results(title="A different research paper"),
                     self.results().replace(DOI, "10.3390/wrong")):
            provider = GoogleScholarProvider()
            provider.session.get = MagicMock(return_value=self.response(html))
            self.assertEqual(provider.search(self.ref), [])

    def test_only_public_web_urls_are_accepted(self):
        self.assertEqual(external_url('/scholar_url?url=https%3A%2F%2Frepository.edu%2Fpaper.pdf'),
                         'https://repository.edu/paper.pdf')
        for value in ('/scholar?cites=123', 'javascript:alert(1)', 'file:///C:/private.pdf',
                      'https://user:secret@repository.edu/paper.pdf'):
            self.assertIsNone(external_url(value))

    def test_rate_limit_stops_further_requests_and_honors_retry_after(self):
        response = self.response(status=429)
        response.headers = {"Retry-After": "7200"}
        self.provider.session.get = MagicMock(return_value=response)
        with patch('paperharbor.providers.google_scholar.time.monotonic', return_value=100):
            self.assertEqual(self.provider.search(self.ref), [])
            self.assertEqual(self.provider._cooldown_until, 7300)
            self.assertEqual(self.provider.search(Reference(key='b', title='Another research title')), [])
        self.provider.session.get.assert_called_once()
        self.assertIn('429', self.provider.last_error)

    def test_challenge_and_forbidden_stop_the_job_without_browser_actions(self):
        for response in (self.response('<form id="gs_captcha_f"></form>'), self.response(status=403)):
            provider = GoogleScholarProvider()
            provider.session.get = MagicMock(return_value=response)
            self.assertEqual(provider.search(self.ref), [])
            self.assertEqual(provider.search(Reference(key='b', title='Another research title')), [])
            provider.session.get.assert_called_once()
            self.assertTrue(provider.last_error)

    def test_api_pdf_resources_without_pdf_extension_and_key_scope(self):
        response = self.response()
        response.json.return_value = {'organic_results': [{
            'title': TITLE, 'link': 'https://doi.org/' + DOI,
            'resources': [{'file_format': 'PDF', 'link': 'https://repository.edu/download/123'}]}]}
        self.provider.session.get = MagicMock(return_value=response)
        with patch.dict(os.environ, {'SERPAPI_API_KEY': 'secret-test-key'}):
            found = self.provider.search(self.ref)
        self.assertEqual(found[0].url, 'https://repository.edu/download/123')
        self.assertTrue(found[0].is_direct_pdf)
        call = self.provider.session.get.call_args
        self.assertEqual(call.args[0], 'https://serpapi.com/search.json')
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertNotIn('secret-test-key', str(found) + self.provider.last_error)

    def test_api_error_and_network_exception_do_not_leak_credentials(self):
        with patch.dict(os.environ, {'SERPAPI_API_KEY': 'secret-test-key'}):
            self.provider.session.get = MagicMock(side_effect=requests.ConnectionError('URL?api_key=secret-test-key'))
            self.assertEqual(self.provider.search(self.ref), [])
            self.assertNotIn('secret-test-key', self.provider.last_error)
            self.provider._next_request = 0
            response = self.response()
            response.json.return_value = {'error': 'bad key secret-test-key'}
            self.provider.session.get = MagicMock(return_value=response)
            self.assertEqual(self.provider.search(self.ref), [])
            self.assertNotIn('secret-test-key', self.provider.last_error)

    def test_doi_only_requires_identity_evidence_and_empty_input_is_skipped(self):
        self.provider.session.get = MagicMock(return_value=self.response(self.results()))
        self.assertTrue(self.provider.search(Reference(key='doi', doi=DOI)))
        self.provider.search(Reference(key='empty'))
        self.provider.session.get.assert_called_once()

    def test_distinct_direct_searches_are_spaced(self):
        self.provider.session.get = MagicMock(return_value=self.response('<div id="gs_res_ccl_mid"></div>'))
        with patch('paperharbor.providers.google_scholar.time.monotonic', return_value=100), patch(
                'paperharbor.providers.google_scholar.time.sleep') as sleep:
            self.provider.search(self.ref)
            self.provider.search(Reference(key='b', title='Another full research title'))
        sleep.assert_called_once_with(15)

    def test_normal_fallback_downloads_scholar_pdf_without_user_override(self):
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([self.ref]), Path(folder), request_delay=0)
            for name in ('author_copies', 'acm', 'researchgate', 'unpaywall', 'openalex',
                         'europe_pmc', 'arxiv', 'semantic_scholar', 'crossref'):
                getattr(app.aggregator, name).search = MagicMock(return_value=[])
            app.aggregator.google_scholar.session.get = MagicMock(return_value=self.response(self.results()))
            def download(url, path, **kwargs):
                self.assertEqual(url, PDF)
                payload = b'%PDF-1.7\\n' + b'x' * 2048
                Path(path).write_bytes(payload)
                return True, len(payload), None
            app.downloader.download_pdf = MagicMock(side_effect=download)
            app.run()
            result = app.reporter.results[0]
            self.assertEqual(result.status, PaperStatus.DOWNLOADED)
            self.assertEqual(result.provider, 'Google Scholar')
            self.assertTrue(Path(result.saved_path).exists())
            app.downloader.download_pdf.assert_called_once()
            app.aggregator.google_scholar.session.get.assert_called_once()

    def test_successful_early_download_does_not_search_scholar(self):
        with tempfile.TemporaryDirectory() as folder:
            app = PaperHarborApp(UploadedReferenceReader([self.ref]), Path(folder), request_delay=0)
            app.aggregator.find_candidates = MagicMock(return_value=([
                CandidatePDF(PDF, 'Early provider')], self.ref.publisher_url))
            app.aggregator.google_scholar.search = MagicMock()
            app.downloader.download_pdf = MagicMock(return_value=(True, 2048, None))
            app.run()
            app.aggregator.google_scholar.search.assert_not_called()
