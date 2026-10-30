"""Live discovery works without the optional catalog and verifies PDF content."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from paperharbor.app import PaperHarborApp
from paperharbor.downloader import PdfDownloader
from paperharbor.models import Reference, DownloadResult, PaperStatus
from paperharbor.providers.author_copies import source_catalog
from paperharbor.providers.web_search import WebSearchProvider, result_url
from paperharbor.web import UploadedReferenceReader


TITLE = "Understanding bag-of-words model: a statistical framework"
DOI = "10.1007/s13042-010-0001-0"
URL = "https://university.edu/publication/paper.pdf"


def pdf_bytes(title):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    content = DecodedStreamObject()
    content.set_data(('BT /F1 10 Tf 30 700 Td (' + title + ') Tj ET').encode('ascii'))
    page[NameObject('/Contents')] = content
    writer.add_metadata({'/Keywords': 'x' * 2048})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'SERPAPI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        self.ref = Reference(key='paper', title=TITLE, doi=DOI)
        self.provider = WebSearchProvider()

    def html(self, url=URL, title=TITLE, snippet=''):
        return ('<div class="results"><div class="result"><a class="result__a" href="' + url + '">'
                + title + '</a><div class="result__snippet">' + snippet + '</div></div></div>')

    def response(self, text='', status=200, data=None):
        response = MagicMock(status_code=status, text=text)
        response.json.return_value = data
        return response

    def download_response(self, payload):
        response = MagicMock(status_code=200, url=URL, headers={})
        response.iter_content.side_effect = lambda **kwargs: iter([payload])
        response.__enter__.return_value = response
        return response

    def test_dynamic_title_search_deduplicates_and_caches_public_links(self):
        self.provider.session.get = MagicMock(return_value=self.response(self.html() + self.html()))
        found = self.provider.search(self.ref)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].url, URL)
        self.assertTrue(found[0].requires_identity_check)
        self.assertEqual(self.provider.search(self.ref), found)
        self.provider.session.get.assert_called_once()
        self.assertIn('filetype:pdf', self.provider.session.get.call_args.kwargs['params']['q'])

    def test_generic_search_title_is_accepted_only_with_matching_snippet(self):
        self.provider.session.get = MagicMock(return_value=self.response(
            self.html(title='Noname manuscript', snippet=TITLE)))
        self.assertEqual(self.provider.search(self.ref)[0].url, URL)

    def test_unrelated_results_and_conflicting_doi_are_rejected(self):
        html = (self.html(title='A completely unrelated paper') + self.html(url='https://doi.org/10.1007/wrong')
                + self.html(url='https://example.org/citation-report.pdf'))
        self.provider.session.get = MagicMock(return_value=self.response(html))
        self.assertEqual(self.provider.search(self.ref), [])

    def test_redirects_are_unwrapped_and_non_web_links_are_rejected(self):
        self.assertEqual(result_url('//duckduckgo.com/l/?uddg=https%3A%2F%2Funiversity.edu%2Fpaper.pdf'),
                         'https://university.edu/paper.pdf')
        for url in ('javascript:bad()', 'file:///C:/private.pdf', 'https://user:pass@university.edu/p.pdf', '/html/?q=foo'):
            self.assertIsNone(result_url(url))

    def test_challenges_and_rate_limits_stop_further_requests(self):
        for response in (self.response(status=202), self.response(status=429),
                         self.response('<form id="challenge-form"></form>')):
            provider = WebSearchProvider()
            provider.session.get = MagicMock(return_value=response)
            self.assertEqual(provider.search(self.ref), [])
            self.assertEqual(provider.search(Reference(key='b', title='A different complete research title')), [])
            provider.session.get.assert_called_once()

    def test_api_uses_google_web_search_and_does_not_expose_key(self):
        self.provider.session.get = MagicMock(return_value=self.response(data={
            'organic_results': [{'title': TITLE, 'link': URL}]}))
        with patch.dict(os.environ, {'SERPAPI_API_KEY': 'secret-key'}):
            self.assertTrue(self.provider.search(self.ref))
        call = self.provider.session.get.call_args
        self.assertEqual(call.kwargs['params']['engine'], 'google')
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertNotIn('secret-key', self.provider.last_error)

    def test_network_failures_do_not_expose_api_key(self):
        self.provider.session.get = MagicMock(side_effect=requests.ConnectionError('url?api_key=secret-key'))
        with patch.dict(os.environ, {'SERPAPI_API_KEY': 'secret-key'}):
            self.assertEqual(self.provider.search(self.ref), [])
        self.assertNotIn('secret-key', self.provider.last_error)

    def test_missing_or_malformed_optional_catalog_is_empty(self):
        for failure in (FileNotFoundError(), ValueError()):
            source_catalog.cache_clear()
            try:
                with patch('paperharbor.providers.author_copies.Path.read_text', side_effect=failure):
                    self.assertEqual(source_catalog(), {})
            finally:
                source_catalog.cache_clear()

    def test_real_pdf_title_is_checked_before_publishing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            downloader = PdfDownloader(retries=0)
            target = Path(folder) / 'paper.pdf'
            downloader.session.get = MagicMock(return_value=self.download_response(pdf_bytes('An unrelated paper')))
            ok, _, error = downloader.download_pdf(URL, target, expected_title=TITLE)
            self.assertFalse(ok)
            self.assertIn('first-page title', error)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(folder).glob('*.part_*')), [])
            downloader.session.get = MagicMock(return_value=self.download_response(pdf_bytes(TITLE)))
            ok, _, error = downloader.download_pdf(URL, target, expected_title=TITLE)
            self.assertTrue(ok, error)
            self.assertTrue(target.exists())

    def test_missing_catalog_pipeline_downloads_unlisted_pdf_automatically(self):
        with tempfile.TemporaryDirectory() as folder, patch(
                'paperharbor.providers.author_copies.source_catalog', return_value={}):
            app = PaperHarborApp(UploadedReferenceReader([self.ref]), Path(folder), request_delay=0)
            for name in ('acm', 'researchgate', 'unpaywall', 'openalex', 'europe_pmc', 'arxiv',
                         'semantic_scholar', 'crossref', 'google_scholar'):
                getattr(app.aggregator, name).search = MagicMock(return_value=[])
            app.aggregator.web_search.session.get = MagicMock(return_value=self.response(self.html()))
            app.downloader.session.get = MagicMock(return_value=self.download_response(pdf_bytes(TITLE)))
            app.run()
            result = app.reporter.results[0]
            self.assertEqual(result.status, PaperStatus.DOWNLOADED)
            self.assertEqual(result.provider, 'Live web search')
            self.assertTrue(Path(result.saved_path).exists())

    def test_single_retry_retains_web_pdf_validation(self):
        with tempfile.TemporaryDirectory() as folder, patch(
                'paperharbor.providers.author_copies.source_catalog', return_value={}):
            app = PaperHarborApp(UploadedReferenceReader([self.ref]), Path(folder), request_delay=0)
            app.reporter.results = [DownloadResult(self.ref, PaperStatus.DOWNLOAD_FAILED, attempts=[{
                'provider': 'Live web search', 'stage': 'download', 'url': URL,
                'requires_identity_check': True, 'error': 'Rejected web-search PDF'}])]
            app.downloader.session.get = MagicMock(return_value=self.download_response(pdf_bytes('Another paper title')))
            app._retry_single_once(self.ref)
            self.assertEqual(app.reporter.results[0].status, PaperStatus.DOWNLOAD_FAILED)
            self.assertEqual(list(Path(folder).glob('*.pdf')), [])

    def test_repository_resolution_retains_first_page_validation(self):
        with tempfile.TemporaryDirectory() as folder, patch(
                'paperharbor.providers.author_copies.source_catalog', return_value={}):
            app = PaperHarborApp(UploadedReferenceReader([self.ref]), Path(folder), request_delay=0)
            for name in ('acm', 'researchgate', 'unpaywall', 'openalex', 'europe_pmc', 'arxiv',
                         'semantic_scholar', 'crossref', 'google_scholar'):
                getattr(app.aggregator, name).search = MagicMock(return_value=[])
            app.aggregator.web_search.session.get = MagicMock(return_value=self.response(
                self.html(url='https://university.edu/item/123')))
            app.landing_resolver.resolve = MagicMock(return_value=[URL])
            app.downloader.session.get = MagicMock(return_value=self.download_response(pdf_bytes('Another paper title')))
            app.run()
            self.assertEqual(app.reporter.results[0].status, PaperStatus.DOWNLOAD_FAILED)
            self.assertEqual(list(Path(folder).glob('*.pdf')), [])
