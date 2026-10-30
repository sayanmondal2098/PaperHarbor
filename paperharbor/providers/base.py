"""Base class for Open Access paper search providers."""

from abc import ABC, abstractmethod
from typing import List, Optional
import os
from urllib.parse import urlparse
import requests

from paperharbor.models import CandidatePDF, Reference


class BaseProvider(ABC):
    """Abstract base class for paper search providers."""

    def __init__(self, email: Optional[str] = None, session: Optional[requests.Session] = None):
        self.email = email or "paperharbor.downloader@gmail.com"
        self.last_error = ""
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": f"PaperHarbor/1.0 (mailto:{self.email})"
        })

    def get(self, url, **kwargs):
        """Retain provider failures even when an individual provider returns no candidates."""
        # Keep credentials on individual requests: providers share a Session.
        headers = dict(kwargs.pop("headers", {}))
        host = urlparse(url).hostname
        if host == "api.openalex.org" and os.environ.get("OPENALEX_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["OPENALEX_API_KEY"]
        if host == "api.semanticscholar.org" and os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
            headers["x-api-key"] = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
        if "x-api-key" in headers or "Authorization" in headers:
            kwargs.setdefault("allow_redirects", False)
        try:
            response = self.session.get(url, headers=headers, **kwargs)
        except requests.RequestException as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise
        if response.status_code not in (200, 404):
            self.last_error = f"HTTP {response.status_code} from metadata service"
        return response

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
