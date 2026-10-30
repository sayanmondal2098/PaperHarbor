"""Springer URL identity, subscription previews, and public author copies."""

import unittest
from unittest.mock import MagicMock

from paperharbor.models import Reference
from paperharbor.providers.author_copies import author_copy_candidates
from paperharbor.providers.landing import LandingPageResolver, publisher_pdf_variants
from paperharbor.providers.matching import doi_from_url, conflicts_with_doi
from paperharbor.single_paper import SinglePaperReader


DOI = "10.1007/s13042-010-0001-0"
TITLE = "Understanding bag-of-words model: a statistical framework"
PDF = "https://link.springer.com/content/pdf/" + DOI + ".pdf"
AUTHOR_PDF = "https://www.lamda.nju.edu.cn/publication/ijmlc10.pdf"


class SpringerTests(unittest.TestCase):
    def test_article_pdf_fulltext_and_encoded_urls_keep_same_doi(self):
        for host in ("link.springer.com", "link.springernature.com"):
            for path in ("/article/" + DOI, "/article/" + DOI + "/",
                         "/article/" + DOI + "/fulltext.html", "/content/pdf/" + DOI + ".pdf",
                         "/content/pdf/" + DOI.replace("/", "%2F") + ".pdf"):
                url = "https://" + host + path + "?download=1"
                with self.subTest(url=url):
                    self.assertEqual(doi_from_url(url), DOI)
                    self.assertEqual(publisher_pdf_variants(url), [PDF])
        self.assertIsNone(doi_from_url("https://evillink.springer.com/article/" + DOI))

    def test_pasted_springer_url_is_identified_before_fetching_metadata(self):
        reader = SinglePaperReader("https://link.springer.com/article/" + DOI)
        self.assertEqual(reader.doi, DOI)
        ref = Reference(key="url", url=reader.url)
        candidate = author_copy_candidates(ref)[0]
        self.assertEqual(candidate.url, AUTHOR_PDF)
        self.assertEqual(candidate.version, "authorManuscript")
        self.assertTrue(conflicts_with_doi(Reference(key="wrong", doi="10.1007/another"), PDF))

    def test_subscription_preview_keeps_pdf_candidate_and_explains_access_failure(self):
        resolver = LandingPageResolver(MagicMock())
        response = MagicMock(status_code=200, url="https://link.springer.com/article/" + DOI)
        response.headers = {"content-type": "text/html"}
        response.text = ('<meta name="citation_doi" content="' + DOI + '">'
                         '<meta name="access" content="No">'
                         '<meta name="citation_pdf_url" content="' + PDF + '">'
                         '<p>This is a preview of subscription content</p>'
                         '<section id="references"><a href="https://elsewhere.edu/cited.pdf">PDF</a></section>')
        resolver.session.get = MagicMock(return_value=response)
        self.assertEqual(resolver.resolve(response.url, expected_doi=DOI), [PDF])
        self.assertIn("Springer subscription preview", resolver.last_error)

    def test_author_copy_does_not_match_another_work_with_same_doi_metadata(self):
        ref = Reference(key="wrong", doi=DOI, title="An unrelated statistical paper")
        self.assertEqual(author_copy_candidates(ref), [])
