"""Semantic Scholar API provider."""

import logging
from urllib.parse import quote
from typing import List
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class SemanticScholarProvider(BaseProvider):
    """Searches Semantic Scholar API for open access PDF links."""

    @property
    def name(self) -> str:
        return "Semantic Scholar"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        doi = reference.clean_doi
        if not doi:
            return []

        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}"
        params = {"fields": "isOpenAccess,openAccessPdf,url"}

        try:
            resp = self.get(url, params=params, timeout=12)
            if resp.status_code != 200:
                return []

            data = resp.json()
            if not data.get("isOpenAccess"):
                return []

            oa_pdf = data.get("openAccessPdf")
            if oa_pdf and isinstance(oa_pdf, dict) and oa_pdf.get("url"):
                pdf_url = oa_pdf.get("url")
                return [CandidatePDF(
                    url=pdf_url,
                    provider=self.name,
                    landing_page=data.get("url"),
                    oa_status="open",
                    is_direct_pdf=True
                )]

            return []

        except requests.RequestException as e:
            logger.debug(f"[SemanticScholar] Request error for DOI {doi}: {e}")
            return []
