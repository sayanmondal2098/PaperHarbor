"""OpenAlex API provider.

OpenAlex is a free, comprehensive catalog of global research, indexing over
250 million scholarly works and tracking Open Access repositories worldwide.
Supports searching by DOI and fallback searching by Title.
"""

import logging
import urllib.parse
from typing import List, Optional
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAlexProvider(BaseProvider):
    """Searches OpenAlex works by DOI or Title for Open Access PDF locations."""

    @property
    def name(self) -> str:
        return "OpenAlex"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        candidates: List[CandidatePDF] = []
        
        # 1. Try search by DOI first
        if reference.clean_doi:
            candidates = self._search_by_doi(reference.clean_doi)
            if candidates:
                return candidates

        # 2. Fallback to search by Title if no DOI or DOI didn't return PDF
        if reference.title and len(reference.title.strip()) > 8:
            candidates = self._search_by_title(reference.title, reference.first_author)

        return candidates

    def _search_by_doi(self, doi: str) -> List[CandidatePDF]:
        url = f"https://api.openalex.org/works/https://doi.org/{doi}"
        params = {"mailto": self.email}

        try:
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 404:
                return []
            if resp.status_code != 200:
                logger.debug(f"[OpenAlex] HTTP {resp.status_code} for DOI {doi}")
                return []

            work = resp.json()
            return self._extract_candidates_from_work(work)

        except requests.RequestException as e:
            logger.warning(f"[OpenAlex] Request error for DOI {doi}: {e}")
            return []

    def _search_by_title(self, title: str, author: Optional[str] = None) -> List[CandidatePDF]:
        # Clean title for OpenAlex search
        clean_title = urllib.parse.quote(title.strip())
        url = f"https://api.openalex.org/works?filter=title.search:{clean_title}&per_page=3"
        params = {"mailto": self.email}

        try:
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return []

            data = resp.json()
            results = data.get("results", [])
            if not results:
                return []

            # Check the best match
            for work in results:
                work_title = (work.get("title") or "").strip().lower()
                orig_title = title.strip().lower()

                # Basic similarity check: share significant words
                orig_words = set(w for w in orig_title.split() if len(w) > 3)
                work_words = set(w for w in work_title.split() if len(w) > 3)
                if orig_words and work_words:
                    overlap = len(orig_words & work_words) / len(orig_words)
                    if overlap >= 0.6:  # 60% key word match
                        candidates = self._extract_candidates_from_work(work)
                        if candidates:
                            return candidates

            return []

        except requests.RequestException as e:
            logger.warning(f"[OpenAlex] Title search error: {e}")
            return []

    def _extract_candidates_from_work(self, work: dict) -> List[CandidatePDF]:
        oa_info = work.get("open_access", {})
        oa_status = oa_info.get("oa_status")
        
        candidates: List[CandidatePDF] = []
        seen_urls = set()

        # 1. Best OA location
        best = work.get("best_oa_location")
        if best and isinstance(best, dict):
            pdf_url = best.get("pdf_url")
            landing = best.get("landing_page_url")
            version = best.get("version")
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

        # 2. Primary location
        primary = work.get("primary_location")
        if primary and isinstance(primary, dict) and primary.get("is_oa"):
            pdf_url = primary.get("pdf_url")
            landing = primary.get("landing_page_url")
            version = primary.get("version")
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

        # 3. All locations
        for loc in work.get("locations", []):
            if loc.get("is_oa"):
                pdf_url = loc.get("pdf_url")
                landing = loc.get("landing_page_url")
                version = loc.get("version")
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

        return candidates
