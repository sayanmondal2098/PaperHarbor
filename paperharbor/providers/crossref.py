"""Crossref metadata API provider.

Checks Crossref metadata for direct publisher full-text links (MDPI, SpringerOpen,
Frontiers, PLOS, etc.) and gathers publisher official landing pages.
"""

import logging
from typing import List, Tuple
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class CrossrefProvider(BaseProvider):
    """Searches Crossref works API for full text links in publication records."""

    @property
    def name(self) -> str:
        return "Crossref"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        doi = reference.clean_doi
        if not doi:
            return []

        url = f"https://api.crossref.org/works/{doi}"
        params = {"mailto": self.email}

        try:
            resp = self.session.get(url, params=params, timeout=12)
            if resp.status_code != 200:
                return []

            data = resp.json()
            message = data.get("message", {})
            links = message.get("link", [])

            candidates: List[CandidatePDF] = []
            for link_item in links:
                content_type = link_item.get("content-type", "").lower()
                pdf_url = link_item.get("URL")
                if "application/pdf" in content_type and pdf_url:
                    candidates.append(CandidatePDF(
                        url=pdf_url,
                        provider=self.name,
                        landing_page=f"https://doi.org/{doi}",
                        oa_status="publisher",
                        is_direct_pdf=True
                    ))

            return candidates

        except requests.RequestException as e:
            logger.debug(f"[Crossref] Request error for DOI {doi}: {e}")
            return []
