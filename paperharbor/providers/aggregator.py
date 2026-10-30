"""Aggregator for multi-provider Open Access paper search."""

import logging
from typing import List, Optional, Tuple
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.arxiv import ArxivProvider
from paperharbor.providers.landing import publisher_pdf_variants
from paperharbor.providers.crossref import CrossrefProvider
from paperharbor.providers.europe_pmc import EuropePmcProvider
from paperharbor.providers.openalex import OpenAlexProvider
from paperharbor.providers.semantic_scholar import SemanticScholarProvider
from paperharbor.providers.unpaywall import UnpaywallProvider

logger = logging.getLogger(__name__)


class ProviderAggregator:
    """Coordinates search across all supported Open Access providers in priority order."""

    def __init__(self, email: Optional[str] = None):
        self.email = email or "paperharbor.downloader@gmail.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"PaperHarbor/1.0 (mailto:{self.email})"
        })

        self.arxiv = ArxivProvider(email=self.email, session=self.session)
        self.unpaywall = UnpaywallProvider(email=self.email, session=self.session)
        self.openalex = OpenAlexProvider(email=self.email, session=self.session)
        self.europe_pmc = EuropePmcProvider(email=self.email, session=self.session)
        self.semantic_scholar = SemanticScholarProvider(email=self.email, session=self.session)
        self.crossref = CrossrefProvider(email=self.email, session=self.session)
        self._queried = set()
        self.errors = []

    def _search(self, provider, reference):
        self._queried.add(provider.name)
        provider.last_error = ""
        try:
            candidates = provider.search(reference)
            if provider.last_error:
                message = f"{provider.name}: {provider.last_error}"
                self.errors.append(message)
                logger.warning(message)
            return candidates
        except Exception as exc:
            message = f"{provider.name}: {type(exc).__name__}: {exc}"
            self.errors.append(message)
            logger.warning("Provider failed; continuing with other sources: %s", message)
            return []

    def find_fallback_candidates(self, reference):
        """After downloads fail, query every provider that the fast search skipped."""
        candidates = []
        for provider in (self.openalex, self.europe_pmc, self.arxiv, self.semantic_scholar, self.crossref):
            if provider.name not in self._queried:
                candidates.extend(self._search(provider, reference))
        if reference.publisher_url:
            candidates.append(CandidatePDF(url=reference.publisher_url, provider="Publisher page",
                landing_page=reference.publisher_url, is_direct_pdf=False))
        return candidates

    def find_candidates(self, reference: Reference) -> Tuple[List[CandidatePDF], Optional[str]]:
        """
        Executes waterfall search across providers.

        Returns:
            Tuple of (list of CandidatePDF sorted by priority, publisher landing page URL)
        """
        self._queried = set()
        self.errors = []
        candidates: List[CandidatePDF] = []
        seen_urls = set()

        publisher_url = reference.publisher_url

        # Helper to add unique candidates
        def add_candidates(found: List[CandidatePDF]):
            for c in found:
                if c.url and c.url not in seen_urls:
                    seen_urls.add(c.url)
                    candidates.append(c)

        def direct():
            return [c for c in candidates if c.is_direct_pdf]

        # 1. Check arXiv first if arXiv DOI or preprint
        if reference.doi and "arxiv" in reference.doi.lower():
            logger.debug(f"Querying arXiv provider for {reference.key}")
            add_candidates(self._search(self.arxiv, reference))
            if candidates:
                return candidates, publisher_url

        # 2. Check Unpaywall (best for DOI-based queries)
        if reference.clean_doi:
            logger.debug(f"Querying Unpaywall provider for {reference.key}")
            add_candidates(self._search(self.unpaywall, reference))

        # 3. Check OpenAlex (covers DOI + Title fallback + institutional repos)
        if len(direct()) < 2:
            logger.debug(f"Querying OpenAlex provider for {reference.key}")
            add_candidates(self._search(self.openalex, reference))

        # 4. Check Europe PMC (for biomedical / PMC works)
        if not direct() and reference.clean_doi:
            logger.debug(f"Querying Europe PMC provider for {reference.key}")
            add_candidates(self._search(self.europe_pmc, reference))

        # 5. Check arXiv by title/metadata if still no candidates
        if not direct():
            logger.debug(f"Querying arXiv search for {reference.key}")
            add_candidates(self._search(self.arxiv, reference))

        # 6. Check Semantic Scholar
        if not direct() and reference.clean_doi:
            logger.debug(f"Querying Semantic Scholar provider for {reference.key}")
            add_candidates(self._search(self.semantic_scholar, reference))

        # 7. Check Crossref direct links
        if not direct() and reference.clean_doi:
            logger.debug(f"Querying Crossref provider for {reference.key}")
            add_candidates(self._search(self.crossref, reference))

        # Last resort: the URL stored in Zotero (e.g. a Wiley /epdf/ viewer link) and its PDF form
        if reference.url and reference.url.startswith("http"):
            for u in publisher_pdf_variants(reference.url):
                add_candidates([CandidatePDF(url=u, provider="Zotero URL", landing_page=reference.url, is_direct_pdf=True)])
            add_candidates([CandidatePDF(url=reference.url, provider="Zotero URL", landing_page=reference.url, is_direct_pdf=False)])

        # Direct PDFs first, landing pages after
        candidates.sort(key=lambda c: not c.is_direct_pdf)
        return candidates, publisher_url

