"""Zotero Web API reader.

Fetches references and checks attachment metadata via the official Zotero Web API.
"""

import logging
import re
from typing import Dict, List, Optional
import requests

from paperharbor.models import Reference
from paperharbor.zotero.reader_base import ZoteroReaderBase

logger = logging.getLogger(__name__)

YEAR_REGEX = re.compile(r"\b(18\d\d|19\d\d|20\d\d)\b")


class ZoteroApiReader(ZoteroReaderBase):
    """Fetches references via the Zotero Web API."""

    def __init__(
        self,
        api_key: str,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        base_url: str = "https://api.zotero.org"
    ):
        self.api_key = api_key
        self.user_id = user_id
        self.group_id = group_id
        self.base_url = base_url.rstrip("/")

        if not self.user_id and not self.group_id:
            raise ValueError("Either user_id or group_id must be provided for Zotero Web API.")

        self.endpoint_prefix = (
            f"{self.base_url}/users/{self.user_id}"
            if self.user_id
            else f"{self.base_url}/groups/{self.group_id}"
        )

        self.session = requests.Session()
        self.session.headers.update({
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
            "User-Agent": "PaperHarbor/1.0"
        })

    def get_references(
        self,
        collection_filter: Optional[str] = None,
        only_missing_pdf: bool = True
    ) -> List[Reference]:
        """Fetch all items from the Zotero Web API."""
        url = f"{self.endpoint_prefix}/items"
        params = {
            "format": "json",
            "include": "data",
            "limit": 100,
            "start": 0
        }

        all_items: List[dict] = []
        while True:
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_items.extend(batch)
            if len(batch) < params["limit"]:
                break
            params["start"] += len(batch)

        # Separate regular items and attachments
        regular_items = []
        attachments_by_parent: Dict[str, List[str]] = {}

        for item in all_items:
            data = item.get("data", {})
            item_type = data.get("itemType", "")
            if item_type == "attachment":
                parent = data.get("parentItem")
                content_type = data.get("contentType", "")
                filename = data.get("filename", "")
                if parent and (content_type == "application/pdf" or filename.lower().endswith(".pdf")):
                    attachments_by_parent.setdefault(parent, []).append(filename or content_type)
            elif item_type not in ("note", "annotation"):
                regular_items.append(data)

        references: List[Reference] = []
        for data in regular_items:
            key = data.get("key", "")
            item_type = data.get("itemType", "journalArticle")
            title = data.get("title", "").strip()
            doi = data.get("DOI", "").strip()
            url_field = data.get("url", "").strip()
            extra = data.get("extra", "").strip()
            date_str = data.get("date", "").strip()

            attachments = attachments_by_parent.get(key, [])
            has_pdf = len(attachments) > 0

            if only_missing_pdf and has_pdf:
                continue

            year = None
            if date_str:
                match = YEAR_REGEX.search(date_str)
                if match:
                    try:
                        year = int(match.group(1))
                    except ValueError:
                        pass

            # Creators
            authors = []
            first_author_last = ""
            for c in data.get("creators", []):
                last = c.get("lastName", "")
                first = c.get("firstName", "")
                name = c.get("name", "")  # single field
                if last or first:
                    full = f"{last}, {first}".strip(" ,")
                    authors.append(full)
                    if not first_author_last and last:
                        first_author_last = last
                elif name:
                    authors.append(name)
                    if not first_author_last:
                        first_author_last = name

            ref = Reference(
                key=key,
                item_type=item_type,
                title=title,
                authors=authors,
                first_author=first_author_last,
                year=year,
                doi=doi or None,
                url=url_field or None,
                extra=extra or None,
                has_zotero_pdf=has_pdf,
                zotero_attachments=attachments
            )
            references.append(ref)

        return references
