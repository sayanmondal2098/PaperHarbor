"""Read unresolved report rows and explain practical recovery actions."""

import csv
from pathlib import Path
from urllib.parse import quote, urlsplit

from paperharbor.models import Reference
from paperharbor.zotero.reader_base import ZoteroReaderBase

RETRY_STATUSES = {"DOWNLOAD_FAILED", "OA_BLOCKED_MANUAL", "ERROR"}


class ReportReader(ZoteroReaderBase):
    """Retry report metadata without needing the original Zotero library."""

    def __init__(self, path, include_not_found=False):
        self.path = Path(path)
        self.include_not_found = include_not_found

    def get_references(self, collection_filter=None, only_missing_pdf=True):
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"Status", "Title", "DOI", "Item_Key"}.issubset(reader.fieldnames or []):
                raise ValueError("Choose a PaperHarbor report with Status, Title, DOI, and Item_Key columns.")
            allowed = RETRY_STATUSES | ({"PAYWALLED_OR_OA_NOT_FOUND"} if self.include_not_found else set())
            references = []
            for index, row in enumerate(reader):
                if row["Status"] not in allowed:
                    continue
                year = row.get("Year", "")
                # Retain the original article page, not an expired failed PDF download URL.
                references.append(Reference(
                    key=row["Item_Key"] or f"report-{index + 1}",
                    title=row["Title"], doi=row["DOI"] or None,
                    item_type=row.get("Item_Type") or "journalArticle",
                    first_author=row.get("First_Author", ""),
                    year=int(year) if year.isdigit() else None,
                    url=row.get("Original_URL") or row.get("Publisher_Or_Landing_URL") or None,
                ))
        return references


def recovery_links(reference):
    if web_resource_kind(reference):
        return [{"label": "Open documentation / dataset", "url": reference.url}]
    query = quote(reference.clean_doi or reference.title)
    links = [
        {"label": "Search Scholar", "url": f"https://scholar.google.com/scholar?q={query}"},
        {"label": "Search OpenAlex", "url": f"https://openalex.org/works?search={quote(reference.title)}"},
    ]
    if reference.publisher_url:
        links.insert(0, {"label": "Publisher / repository", "url": reference.publisher_url})
    if reference.clean_doi and reference.clean_doi.lower().startswith("10.1145/"):
        links.insert(0, {"label": "ACM Digital Library", "url": f"https://dl.acm.org/doi/{reference.clean_doi}"})
    return links


def recovery_action(status, errors=""):
    if status == "WITHDRAWN":
        return "The source marks this work withdrawn. Read the withdrawal notice before using or citing it; automatic recovery stopped."
    if status == "WEB_RESOURCE":
        return "Open the documentation or dataset page. This reference is a web resource, not a missing research PDF."
    if status == "DOWNLOADED":
        return "PDF saved. Verify its title/version before citing."
    if status.startswith("SKIPPED"):
        return "Existing file or Zotero attachment retained."
    if status != "OA_BLOCKED_MANUAL" and ("429" in errors or "503" in errors):
        return "Service busy or rate limited. Wait and retry this entry later."
    if "401" in errors or "403" in errors or "not a valid PDF" in errors or "202" in errors:
        return ("Open the article/repository link in your browser. Complete any normal sign-in or site interaction, "
                "then save the PDF to the destination using the suggested filename. Alternatively paste a verified "
                "author/repository PDF URL into the reference's alternate-link field and retry.")
    if status == "PAYWALLED_OR_OA_NOT_FOUND":
        return "Verify DOI/title, search for an author manuscript, or request the paper through your library or author."
    return "Inspect the attempt details, retry later, or use a verified repository PDF URL. Check destination permissions if saving failed."


def web_resource_kind(reference):
    """Recognize explicit datasets/documentation without declaring article pages non-PDF."""
    parsed = urlsplit(reference.url or "")
    if parsed.scheme not in ("http", "https") or parsed.path.lower().endswith(".pdf"):
        return None
    host = (parsed.hostname or "").lower()
    if host == "archive.ics.uci.edu" and parsed.path.startswith("/dataset/"):
        return "Dataset"
    if reference.item_type.lower() == "dataset" and not reference.clean_doi:
        return "Dataset"
    if ((host == "flower.ai" and parsed.path.startswith("/docs/"))
            or (host == "kafka.apache.org" and ("/operations/" in parsed.path or "/documentation" in parsed.path))):
        return "Documentation"
    return None
