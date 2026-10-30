"""Crossref metadata API provider.

Checks Crossref metadata for direct publisher full-text links (MDPI, SpringerOpen,
Frontiers, PLOS, etc.) and gathers publisher official landing pages.
"""

import logging
from typing import List, Tuple
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider
from paperharbor.providers.matching import same_title
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class CrossrefProvider(BaseProvider):
    """Searches Crossref works API for full text links in publication records."""

    @property
    def name(self) -> str:
        return "Crossref"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        doi = reference.clean_doi
        if not doi and len(reference.title.strip()) < 12:
            return []
        url = f"https://api.crossref.org/works/{doi}" if doi else "https://api.crossref.org/works"
        params = {"mailto": self.email}
        if not doi:
            params.update({"query.title": reference.title, "rows": 3})

        try:
            resp = self.get(url, params=params, timeout=12)
            if resp.status_code != 200:
                return []

            data = resp.json()
            message = data.get("message", {})
            if not doi:
                match = next((item for item in message.get("items", [])
                    if same_title(reference.title, " ".join(item.get("title", [])))), None)
                if not match:
                    return []
                message = match
                doi = message.get("DOI")
                if not doi:
                    return []
            links = message.get("link", [])

            candidates: List[CandidatePDF] = []
            for link_item in links:
                content_type = link_item.get("content-type", "").lower()
                pdf_url = link_item.get("URL")
                pdf_path = urlsplit(pdf_url or "").path.lower()
                if pdf_url and ("application/pdf" in content_type or pdf_path.endswith(".pdf") or "/doi/pdf/" in pdf_path):
                    candidates.append(CandidatePDF(
                        url=pdf_url,
                        provider=self.name,
                        landing_page=f"https://doi.org/{doi}",
                        oa_status="publisher",
                        is_direct_pdf=True
                    ))

            # Crossref may expose only an article URL or mark a PDF as "unspecified".
            landing = message.get("resource", {}).get("primary", {}).get("URL") or message.get("URL") or f"https://doi.org/{doi}"
            candidates.append(CandidatePDF(url=landing, provider=self.name, landing_page=landing,
                                          oa_status="publisher", is_direct_pdf=False))
            return candidates

        except requests.RequestException as e:
            logger.debug(f"[Crossref] Request error for DOI {doi}: {e}")
            return []
