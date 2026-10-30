"""Data models for PaperHarbor."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class PaperStatus(str, Enum):
    """Status of reference download process."""
    DOWNLOADED = "DOWNLOADED"
    SKIPPED_ALREADY_IN_ZOTERO = "SKIPPED_ALREADY_IN_ZOTERO"
    SKIPPED_ALREADY_IN_DEST = "SKIPPED_ALREADY_IN_DEST"
    PAYWALLED_OR_OA_NOT_FOUND = "PAYWALLED_OR_OA_NOT_FOUND"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    OA_BLOCKED_MANUAL = "OA_BLOCKED_MANUAL"
    ERROR = "ERROR"
    WEB_RESOURCE = "WEB_RESOURCE"
    WITHDRAWN = "WITHDRAWN"


@dataclass
class Reference:
    """Represents an academic work extracted from Zotero."""
    key: str
    item_id: Optional[int] = None
    item_type: str = "journalArticle"
    title: str = ""
    authors: List[str] = field(default_factory=list)
    first_author: str = ""
    year: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    extra: Optional[str] = None
    collections: List[str] = field(default_factory=list)
    has_zotero_pdf: bool = False
    zotero_attachments: List[str] = field(default_factory=list)

    @property
    def display_author(self) -> str:
        """Returns clean first author last name or 'UnknownAuthor'."""
        if self.first_author:
            return self.first_author
        if self.authors:
            # Authors often formatted as "LastName, FirstName"
            first = self.authors[0]
            if "," in first:
                return first.split(",")[0].strip()
            return first.strip()
        return "UnknownAuthor"

    @property
    def display_year(self) -> str:
        """Returns 4-digit year as string or 'UnknownYear'."""
        if self.year:
            return str(self.year)
        return "UnknownYear"

    @property
    def clean_doi(self) -> Optional[str]:
        """Normalizes DOI to 10.xxxx/... format without URL prefix."""
        if not self.doi:
            return None
        doi = self.doi.strip()
        for prefix in [
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
            "doi:",
            "DOI:"
        ]:
            if doi.startswith(prefix):
                doi = doi[len(prefix):].strip()
        return doi if doi else None

    @property
    def publisher_url(self) -> Optional[str]:
        """Returns the official DOI URL or fallback item URL."""
        doi = self.clean_doi
        if doi:
            return f"https://doi.org/{doi}"
        if self.url and self.url.startswith("http"):
            return self.url
        return None


@dataclass
class CandidatePDF:
    """Represents a discovered Open Access PDF location."""
    url: str
    provider: str
    landing_page: Optional[str] = None
    oa_status: Optional[str] = None
    version: Optional[str] = None  # publishedVersion, acceptedVersion, submittedVersion
    is_direct_pdf: bool = True


@dataclass
class DownloadResult:
    """Represents the final outcome of processing a reference."""
    reference: Reference
    status: PaperStatus
    provider: Optional[str] = None
    pdf_url: Optional[str] = None
    saved_filename: Optional[str] = None
    saved_path: Optional[str] = None
    file_size_bytes: int = 0
    publisher_url: Optional[str] = None
    notes: str = ""
    attempts: List[dict] = field(default_factory=list)
    recovery_action: str = ""
    suggested_filename: Optional[str] = None
    auto_retry_count: int = 0
    auto_retry_url: Optional[str] = None
