"""Read one paper from a DOI or article URL using public bibliographic metadata."""

from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from paperharbor.models import Reference
from paperharbor.providers.matching import normalize_identifier, doi_from_url
from paperharbor.zotero.reader_base import ZoteroReaderBase


class SinglePaperReader(ZoteroReaderBase):
    def __init__(self, identifier, title="", email=None):
        self.doi, self.url = normalize_identifier(identifier)
        self.title = title.strip()
        self.email = email or "paperharbor.downloader@gmail.com"
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"PaperHarbor/1.0 (mailto:{self.email})"
        self._reference = None

    def get_references(self, collection_filter=None, only_missing_pdf=True):
        if self._reference is not None:
            return [self._reference]
        title, authors, year = self.title, [], None
        doi = self.doi
        try:
            if not doi:
                page = self.session.get(self.url, timeout=(10, 20))
                page.raise_for_status()
                soup = BeautifulSoup(page.text, "html.parser")
                meta = soup.find("meta", attrs={"name": "citation_doi"})
                raw = meta.get("content", "") if meta else ""
                if raw:
                    doi, _ = normalize_identifier(raw)
                doi = doi or doi_from_url(page.url)
                meta = soup.find("meta", attrs={"name": "citation_title"})
                title = title or (meta.get("content", "") if meta else "")
            if doi:
                response = self.session.get(
                    "https://api.crossref.org/works/" + quote(doi, safe=""),
                    params={"mailto": self.email}, timeout=(10, 20))
                response.raise_for_status()
                work = response.json().get("message", {})
                reported = work.get("DOI", doi)
                if reported.lower() != doi.lower():
                    raise ValueError("Bibliographic metadata returned a conflicting DOI.")
                title = title or " ".join(work.get("title", []))
                authors = [", ".join(filter(None, [a.get("family"), a.get("given")]))
                           for a in work.get("author", [])]
                for field in ("published", "published-print", "published-online", "issued"):
                    parts = work.get(field, {}).get("date-parts", [])
                    if parts and parts[0] and isinstance(parts[0][0], int):
                        year = parts[0][0]
                        break
        except requests.RequestException as exc:
            if not title:
                raise ValueError("Could not load this paper's metadata. Add its title (--title on the CLI), or upload its BibTeX/CSL-JSON export.") from exc
        if not title:
            raise ValueError("No paper title found. Enter the title or upload a bibliography with its metadata.")
        self._reference = Reference(
            key=doi or self.url, title=title.strip(), doi=doi,
            url=self.url or (f"https://doi.org/{doi}" if doi else None),
            authors=authors, first_author=authors[0].split(",")[0] if authors else "", year=year)
        return [self._reference]
