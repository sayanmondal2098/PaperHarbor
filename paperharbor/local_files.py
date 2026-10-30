"""Recognize manually saved PDFs without trusting their filenames alone."""

import logging
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)


def normalized_text(value):
    value = unicodedata.normalize("NFKD", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


class LocalPdfIndex:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.entries = None

    def find(self, reference):
        """Require a title plus DOI evidence; unknown identities remain unresolved."""
        doi = reference.clean_doi
        title = normalized_text(reference.title)
        if not doi or len(title.split()) < 4:
            return None
        if self.entries is None:
            self.entries = []
            for path in sorted(self.folder.glob("*.pdf")):
                try:
                    if path.stat().st_size <= 1024:
                        continue
                    with path.open("rb") as handle:
                        if b"%PDF-" not in handle.read(1024):
                            continue
                        reader = PdfReader(handle)
                        if reader.is_encrypted or not reader.pages:
                            continue
                        metadata = reader.metadata or {}
                        first_page = reader.pages[0].extract_text() or ""
                        self.entries.append((path, normalized_text(metadata.get("/Title", "")),
                                             normalized_text(first_page[:2000]),
                                             first_page.casefold() + " " + str(metadata).casefold()))
                except Exception as exc:
                    logger.debug("Cannot identify local PDF %s: %s", path.name, exc)
        for path, metadata_title, page_title, evidence in self.entries:
            if title != metadata_title and title not in page_title:
                continue
            if re.search(re.escape(doi.casefold()) + r"(?=$|[\s<>\"'\)\]}.,])", evidence):
                return path
            # Older ACM PDFs predate embedded DOI metadata. The exact numeric
            # DOI suffix filename is accepted only with a matching printed title.
            suffix = doi.split("/", 1)[-1]
            if doi.lower().startswith("10.1145/") and re.fullmatch(r"\d+\.\d+", suffix) and path.stem == suffix:
                return path
        return None
