"""Provider modules for PaperHarbor."""

from paperharbor.providers.base import BaseProvider
from paperharbor.providers.unpaywall import UnpaywallProvider
from paperharbor.providers.openalex import OpenAlexProvider
from paperharbor.providers.arxiv import ArxivProvider
from paperharbor.providers.europe_pmc import EuropePmcProvider
from paperharbor.providers.semantic_scholar import SemanticScholarProvider
from paperharbor.providers.crossref import CrossrefProvider
from paperharbor.providers.aggregator import ProviderAggregator

__all__ = [
    "BaseProvider",
    "UnpaywallProvider",
    "OpenAlexProvider",
    "ArxivProvider",
    "EuropePmcProvider",
    "SemanticScholarProvider",
    "CrossrefProvider",
    "ProviderAggregator",
]
