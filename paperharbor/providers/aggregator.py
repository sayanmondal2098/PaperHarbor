"""Aggregator for multi-provider Open Access paper search."""

import logging
from typing import List, Optional, Tuple
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.arxiv import ArxivProvider
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

    def find_candidates(self, reference: Reference) -> Tuple[List[CandidatePDF], Optional[str]]:
        """
        Executes waterfall search across providers.
        
        Returns:
            Tuple of (list of CandidatePDF sorted by priority, publisher landing page URL)
        """
        candidates: List[CandidatePDF] = []
        seen_urls = set()

        publisher_url = reference.publisher_url

        # Helper to add unique candidates
        def add_candidates(found: List[CandidatePDF]):
            for c in found:
                if c.url and c.url not in seen_urls:
                    seen_urls.add(c.url)
                    candidates.append(c)

        # 1. Check arXiv first if arXiv DOI or preprint
        if reference.doi and "arxiv" in reference.doi.lower():
            logger.debug(f"Querying arXiv provider for {reference.key}")
            add_candidates(self.arxiv.search(reference))
            if candidates:
                return candidates, publisher_url

        # 2. Check Unpaywall (best for DOI-based queries)
        if reference.clean_doi:
            logger.debug(f"Querying Unpaywall provider for {reference.key}")
            add_candidates(self.unpaywall.search(reference))

        # 3. Check OpenAlex (covers DOI + Title fallback + institutional repos)
        if not candidates or len(candidates) < 2:
            logger.debug(f"Querying OpenAlex provider for {reference.key}")
            add_candidates(self.openalex.search(reference))

        # 4. Check Europe PMC (for biomedical / PMC works)
        if not candidates and reference.clean_doi:
            logger.debug(f"Querying Europe PMC provider for {reference.key}")
            add_candidates(self.europe_pmc.search(reference))

        # 5. Check arXiv by title/metadata if still no candidates
        if not candidates:
            logger.debug(f"Querying arXiv search for {reference.key}")
            add_candidates(self.arxiv.search(reference))

        # 6. Check Semantic Scholar
        if not candidates and reference.clean_doi:
            logger.debug(f"Querying Semantic Scholar provider for {reference.key}")
            add_candidates(self.semantic_scholar.search(reference))

        # 7. Check Crossref direct links
        if not candidates and reference.clean_doi:
            logger.debug(f"Querying Crossref provider for {reference.key}")
            add_candidates(self.crossref.search(reference))

        return candidates, publisher_url
