"""Zotero export file reader (CSL-JSON and BibTeX).

Allows loading exported references from Zotero when direct database
access is not available or when processing a specific exported collection.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from paperharbor.models import Reference
from paperharbor.zotero.reader_base import ZoteroReaderBase

logger = logging.getLogger(__name__)

YEAR_REGEX = re.compile(r"\b(18\d\d|19\d\d|20\d\d)\b")


def _bibtex_entries(content):
    """Read nested braced/quoted fields and bare values without splitting at @ in URLs."""
    position = 0
    entry_pattern = re.compile(r"@(\w+)\s*([{(])")
    while True:
        match = entry_pattern.search(content, position)
        if not match:
            return
        kind = match.group(1)
        opener = match.group(2)
        closer = "}" if opener == "{" else ")"
        start = match.end()
        depth, quoted, escaped = 0, False, False
        end = start
        while end < len(content):
            char = content[end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"' and depth == 0:
                quoted = not quoted
            elif not quoted:
                if char == closer and depth == 0:
                    break
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
            end += 1
        if end == len(content):
            raise ValueError("Incomplete BibTeX entry. Check closing braces or quotes.")
        position = end + 1
        if kind.lower() in ("comment", "preamble", "string"):
            continue
        body = content[start:end]
        key, separator, body = body.partition(",")
        if not separator or not key.strip():
            continue
        fields = {}
        index = 0
        while index < len(body):
            if body[index].isspace() or body[index] == ",":
                index += 1
                continue
            if body[index] == "%":
                newline = body.find("\n", index)
                index = len(body) if newline < 0 else newline + 1
                continue
            field = re.match(r"(\w+)\s*=\s*", body[index:])
            if not field:
                break
            index += field.end()
            if index >= len(body):
                break
            delimiter = body[index]
            if delimiter in ('{', '"'):
                index += 1
                value_start = index
                nesting, escaped = 0, False
                while index < len(body):
                    char = body[index]
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == "{":
                        nesting += 1
                    elif char == "}" and nesting:
                        nesting -= 1
                    elif nesting == 0 and char == ("}" if delimiter == "{" else '"'):
                        break
                    index += 1
                value = body[value_start:index]
                index += 1
            else:
                value_start = index
                while index < len(body) and body[index] != ",":
                    index += 1
                value = body[value_start:index]
            fields[field.group(1).lower()] = value.strip()
        yield kind, key.strip(), fields


class ZoteroExportReader(ZoteroReaderBase):
    """Parses references from CSL-JSON or BibTeX files exported from Zotero."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path).resolve()
        if not self.file_path.is_file():
            raise FileNotFoundError(f"Export file not found: {self.file_path}")

    def get_references(
        self,
        collection_filter: Optional[str] = None,
        only_missing_pdf: bool = True
    ) -> List[Reference]:
        ext = self.file_path.suffix.lower()
        if ext == ".json":
            return self._parse_csl_json(only_missing_pdf)
        elif ext in (".bib", ".bibtex"):
            return self._parse_bibtex(only_missing_pdf)
        else:
            raise ValueError(f"Unsupported file extension: {ext}. Expected .json or .bib")

    def _parse_csl_json(self, only_missing_pdf: bool) -> List[Reference]:
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            data = [data]

        references: List[Reference] = []
        for item in data:
            key = str(item.get("id", ""))
            item_type = item.get("type", "article-journal")
            title = item.get("title", "").strip()
            doi = item.get("DOI", "") or item.get("doi", "")
            url = item.get("URL", "") or item.get("url", "")
            
            # Authors
            authors = []
            first_author_last = ""
            for a in item.get("author", []):
                last = a.get("family", "")
                first = a.get("given", "")
                full = f"{last}, {first}".strip(" ,") if last or first else ""
                if full:
                    authors.append(full)
                if not first_author_last and last:
                    first_author_last = last

            # Year from issued date-parts
            year = None
            issued = item.get("issued", {})
            date_parts = issued.get("date-parts", [])
            if date_parts and date_parts[0] and isinstance(date_parts[0][0], int):
                year = date_parts[0][0]

            # In CSL JSON, custom attachments might be in extra or custom keys
            # By default CSL JSON doesn't include attachments unless exported with them
            has_pdf = False
            attachments = []
            if "file" in item:
                file_str = str(item["file"])
                if ".pdf" in file_str.lower():
                    has_pdf = True
                    attachments.append(file_str)

            if only_missing_pdf and has_pdf:
                continue

            ref = Reference(
                key=key,
                item_type=item_type,
                title=title,
                authors=authors,
                first_author=first_author_last,
                year=year,
                doi=doi.strip() if doi else None,
                url=url.strip() if url else None,
                has_zotero_pdf=has_pdf,
                zotero_attachments=attachments
            )
            references.append(ref)

        return references

    def _parse_bibtex(self, only_missing_pdf: bool) -> List[Reference]:
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        references: List[Reference] = []

        for item_type, key, fields in _bibtex_entries(content):

            title = fields.get("title", "")
            # Clean bibtex braces from title
            title = re.sub(r"[{}]", "", title).strip()

            doi = fields.get("doi", "")
            url = fields.get("url", "")
            file_field = fields.get("file", "")

            # Year
            year_val = fields.get("year", "")
            year = None
            if year_val:
                y_match = YEAR_REGEX.search(year_val)
                if y_match:
                    year = int(y_match.group(1))

            # Authors
            author_str = fields.get("author", "")
            authors = []
            first_author_last = ""
            if author_str:
                for a in author_str.split(" and "):
                    a_clean = re.sub(r"[{}]", "", a).strip()
                    if a_clean:
                        authors.append(a_clean)
                        if not first_author_last:
                            if "," in a_clean:
                                first_author_last = a_clean.split(",")[0].strip()
                            else:
                                first_author_last = a_clean.split()[-1].strip()

            has_pdf = ".pdf" in file_field.lower()
            if only_missing_pdf and has_pdf:
                continue

            ref = Reference(
                key=key,
                item_type=item_type,
                title=title,
                authors=authors,
                first_author=first_author_last,
                year=year,
                doi=doi if doi else None,
                url=url if url else None,
                has_zotero_pdf=has_pdf,
                zotero_attachments=[file_field] if has_pdf else []
            )
            references.append(ref)

        return references
