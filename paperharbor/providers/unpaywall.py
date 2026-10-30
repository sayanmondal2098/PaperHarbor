"""Unpaywall Open Access API provider.

Unpaywall indexes over 50,000 journals and repositories worldwide,
providing direct links to legal open access versions of papers with DOIs.
"""

import logging
from typing import List
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class UnpaywallProvider(BaseProvider):
    """Searches Unpaywall API for Open Access PDFs using paper DOIs."""

    @property
    def name(self) -> str:
        return "Unpaywall"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        doi = reference.clean_doi
        if not doi:
            return []

        url = f"https://api.unpaywall.org/v2/{doi}"
        params = {"email": self.email}

        try:
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 404:
                logger.debug(f"[Unpaywall] DOI not found in database: {doi}")
                return []
            if resp.status_code != 200:
                logger.debug(f"[Unpaywall] HTTP {resp.status_code} for DOI: {doi}")
                return []

            data = resp.json()
            if not data.get("is_oa", False):
                logger.debug(f"[Unpaywall] Paper marked not open access: {doi}")
                return []

            candidates: List[CandidatePDF] = []
            seen_urls = set()

            # 1. Check best_oa_location
            best = data.get("best_oa_location")
            if best and isinstance(best, dict):
                pdf_url = best.get("url_for_pdf")
                landing = best.get("url_for_landing_page") or best.get("url")
                version = best.get("version")
                oa_status = data.get("oa_status")

                if pdf_url and pdf_url not in seen_urls:
                    seen_urls.add(pdf_url)
                    candidates.append(CandidatePDF(
                        url=pdf_url,
                        provider=self.name,
                        landing_page=landing,
                        oa_status=oa_status,
                        version=version,
                        is_direct_pdf=True
                    ))

            # 2. Check all oa_locations for fallbacks
            for loc in data.get("oa_locations", []):
                pdf_url = loc.get("url_for_pdf")
                landing = loc.get("url_for_landing_page") or loc.get("url")
                version = loc.get("version")
                if pdf_url and pdf_url not in seen_urls:
                    seen_urls.add(pdf_url)
                    candidates.append(CandidatePDF(
                        url=pdf_url,
                        provider=self.name,
                        landing_page=landing,
                        oa_status=data.get("oa_status"),
                        version=version,
                        is_direct_pdf=True
                    ))

            return candidates

        except requests.RequestException as e:
            logger.warning(f"[Unpaywall] Request error for DOI {doi}: {e}")
            return []
        except Exception as e:
            logger.warning(f"[Unpaywall] Unexpected error for DOI {doi}: {e}")
            return []
