"""Abstract base class for Zotero library readers."""

from abc import ABC, abstractmethod
from typing import List, Optional
from paperharbor.models import Reference


class ZoteroReaderBase(ABC):
    """Base class for reading references and attachment metadata from Zotero."""

    @abstractmethod
    def get_references(
        self,
        collection_filter: Optional[str] = None,
        only_missing_pdf: bool = True
    ) -> List[Reference]:
        """
        Extract references from Zotero source.
        
        Parameters:
            collection_filter: Optional name or key of Zotero collection to restrict to.
            only_missing_pdf: If True, only returns references that don't have a PDF in Zotero.
        """
        pass
