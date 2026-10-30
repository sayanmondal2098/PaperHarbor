"""ACM Digital Library article and ePDF candidates without requiring an ACM API key."""

import re
from urllib.parse import urlsplit

from paperharbor.models import CandidatePDF
from paperharbor.providers.base import BaseProvider
from paperharbor.providers.matching import doi_from_url


class AcmProvider(BaseProvider):
    @property
    def name(self):
        return "ACM Digital Library"

    def search(self, reference):
        doi = reference.clean_doi or doi_from_url(reference.url)
        if doi and re.fullmatch(r"10\.1145/[^\s?#]+", doi, re.I):
            landing = f"https://dl.acm.org/doi/{doi}"
            return [
                CandidatePDF(url=f"https://dl.acm.org/doi/pdf/{doi}", provider=self.name,
                             landing_page=landing, oa_status="publisher"),
                CandidatePDF(url=f"https://dl.acm.org/doi/epdf/{doi}", provider=self.name,
                             landing_page=landing, oa_status="publisher", is_direct_pdf=False),
                CandidatePDF(url=landing, provider=self.name, landing_page=landing,
                             oa_status="publisher", is_direct_pdf=False),
            ]
        # Legacy citation.cfm / authorize URLs are resolved through article metadata or redirects.
        if not reference.clean_doi and urlsplit(reference.url or "").hostname in ("dl.acm.org", "www.dl.acm.org"):
            return [CandidatePDF(url=reference.url, provider=self.name, is_direct_pdf=False)]
        return []
