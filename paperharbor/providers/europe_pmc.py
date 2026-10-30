"""Europe PMC Open Access repository provider.

Provides full-text open access links for biomedical and life sciences research.
"""

import logging
from typing import List
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class EuropePmcProvider(BaseProvider):
    """Searches Europe PMC for open access full text PDFs."""

    @property
    def name(self) -> str:
        return "Europe PMC"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        doi = reference.clean_doi
        if not doi:
            return []

        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            "query": f'DOI:"{doi}"',
            "format": "json",
            "resultType": "core"
        }

        try:
            resp = self.get(url, params=params, timeout=12)
            if resp.status_code != 200:
                return []

            data = resp.json()
            result_list = data.get("resultList", {}).get("result", [])
            if not result_list:
                return []

            paper = result_list[0]
            is_oa = paper.get("isOpenAccess") == "Y"
            if not is_oa:
                return []

            candidates: List[CandidatePDF] = []
            full_text_urls = paper.get("fullTextUrlList", {}).get("fullTextUrl", [])

            for item in full_text_urls:
                doc_style = item.get("documentStyle", "").lower()
                pdf_url = item.get("url")
                if doc_style == "pdf" and pdf_url:
                    candidates.append(CandidatePDF(
                        url=pdf_url,
                        provider=self.name,
                        landing_page=f"https://europepmc.org/article/MED/{paper.get('pmid')}" if paper.get("pmid") else None,
                        oa_status="gold",
                        is_direct_pdf=True
                    ))

            return candidates

        except requests.RequestException as e:
            logger.debug(f"[EuropePMC] Request error for DOI {doi}: {e}")
            return []
