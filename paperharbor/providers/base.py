"""Base class for Open Access paper search providers."""

from abc import ABC, abstractmethod
from typing import List, Optional
import requests

from paperharbor.models import CandidatePDF, Reference


class BaseProvider(ABC):
    """Abstract base class for paper search providers."""

    def __init__(self, email: Optional[str] = None, session: Optional[requests.Session] = None):
        self.email = email or "paperharbor.downloader@gmail.com"
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": f"PaperHarbor/1.0 (mailto:{self.email})"
        })

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @abstractmethod
    def search(self, reference: Reference) -> List[CandidatePDF]:
        """
        Search for full-text PDF links for a given reference.
        
        Returns a list of CandidatePDF objects ordered by relevance/confidence.
        """
        pass
