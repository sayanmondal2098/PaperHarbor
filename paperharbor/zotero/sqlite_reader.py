"""Zotero local SQLite database reader.

Reads references directly from zotero.sqlite in a non-destructive, read-only
manner using a temporary snapshot to ensure safety even when Zotero is running.
"""

import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from paperharbor.models import Reference
from paperharbor.zotero.reader_base import ZoteroReaderBase

logger = logging.getLogger(__name__)

YEAR_REGEX = re.compile(r"\b(18\d\d|19\d\d|20\d\d)\b")
DOI_EXTRA_REGEX = re.compile(r"(?:DOI|doi):\s*([10]\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")


def find_default_zotero_db() -> Optional[Path]:
    """Attempts to locate the default zotero.sqlite file across common OS locations."""
    candidates: List[Path] = []
    
    # Standard standalone Zotero data dir (Zotero 5, 6, 7)
    home = Path.home()
    candidates.append(home / "Zotero" / "zotero.sqlite")
    
    # Windows AppData profiles
    appdata = os.environ.get("APPDATA")
    if appdata:
        appdata_path = Path(appdata) / "Zotero" / "Zotero" / "Profiles"
        if appdata_path.exists():
            for prof in appdata_path.glob("*.default*"):
                candidates.append(prof / "zotero" / "zotero.sqlite")
                
    # macOS Application Support profiles
    mac_profiles = home / "Library" / "Application Support" / "Zotero" / "Profiles"
    if mac_profiles.exists():
        for prof in mac_profiles.glob("*.default*"):
            candidates.append(prof / "zotero" / "zotero.sqlite")
            
    # Linux ~/.zotero
    linux_profiles = home / ".zotero" / "zotero"
    if linux_profiles.exists():
        for prof in linux_profiles.glob("*.default*"):
            candidates.append(prof / "zotero" / "zotero.sqlite")
            
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
            
    return None


class ZoteroSqliteReader(ZoteroReaderBase):
    """
    Reads references from local zotero.sqlite file.
    
    Creates a temporary read-only snapshot before querying so that
    it never interferes with, modifies, or locks an active Zotero session.
    """

    def __init__(self, db_path: Optional[Path] = None, use_snapshot: bool = True):
        if db_path is None:
            detected = find_default_zotero_db()
            if not detected:
                raise FileNotFoundError(
                    "Could not automatically locate 'zotero.sqlite'. "
                    "Please specify the path using --zotero-path."
                )
            self.db_path = detected
        else:
            self.db_path = Path(db_path).resolve()
            if not self.db_path.is_file():
                raise FileNotFoundError(f"Zotero SQLite database not found at: {self.db_path}")

        self.use_snapshot = use_snapshot

    def _get_connection(self):
        """Creates a safe read-only connection, optionally via a temp snapshot."""
        if not self.use_snapshot:
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            return sqlite3.connect(uri, uri=True), None

        temp_dir = tempfile.mkdtemp(prefix="paperharbor_zotero_")
        temp_db = Path(temp_dir) / "zotero_snapshot.sqlite"
        
        # Copy main database
        shutil.copy2(self.db_path, temp_db)
        
        # Also copy WAL and SHM files if present for consistent read
        wal_file = self.db_path.with_name(self.db_path.name + "-wal")
        if wal_file.exists():
            try:
                shutil.copy2(wal_file, temp_db.with_name(temp_db.name + "-wal"))
            except Exception as e:
                logger.debug(f"Could not copy WAL file: {e}")
                
        shm_file = self.db_path.with_name(self.db_path.name + "-shm")
        if shm_file.exists():
            try:
                shutil.copy2(shm_file, temp_db.with_name(temp_db.name + "-shm"))
            except Exception as e:
                logger.debug(f"Could not copy SHM file: {e}")

        conn = sqlite3.connect(str(temp_db))
        return conn, temp_dir

    def get_references(
        self,
        collection_filter: Optional[str] = None,
        only_missing_pdf: bool = True
    ) -> List[Reference]:
        """
        Extract non-deleted references and detect which already have PDFs.
        """
        conn, temp_dir = self._get_connection()
        try:
            return self._query_database(conn, collection_filter, only_missing_pdf)
        finally:
            conn.close()
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _query_database(
        self,
        conn: sqlite3.Connection,
        collection_filter: Optional[str],
        only_missing_pdf: bool
    ) -> List[Reference]:
        cursor = conn.cursor()

        # 1. Fetch PDF attachment map: parentItemID -> list of attachment paths
        cursor.execute("""
            SELECT 
                parentItemID,
                path,
                contentType
            FROM itemAttachments
            WHERE parentItemID IS NOT NULL
              AND (
                  LOWER(COALESCE(contentType, '')) = 'application/pdf'
                  OR LOWER(COALESCE(path, '')) LIKE '%.pdf'
                  OR LOWER(COALESCE(path, '')) LIKE 'storage:%.pdf'
              )
        """)
        pdf_attachments: Dict[int, List[str]] = {}
        for parent_id, path_val, content_type in cursor.fetchall():
            pdf_attachments.setdefault(parent_id, []).append(path_val or content_type or "attachment.pdf")

        # 2. Fetch collection mappings
        cursor.execute("""
            SELECT 
                ci.itemID,
                c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
        """)
        item_collections: Dict[int, List[str]] = {}
        for item_id, coll_name in cursor.fetchall():
            item_collections.setdefault(item_id, []).append(coll_name)

        # 3. Fetch top-level items excluding deleted items, notes, attachments, annotations
        cursor.execute("""
            SELECT 
                i.itemID,
                i.key,
                it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note', 'annotation')
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
        """)
        items_raw = cursor.fetchall()

        # 4. Fetch field values (title, DOI, date, url, extra)
        cursor.execute("""
            SELECT 
                id.itemID,
                f.fieldName,
                idv.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE f.fieldName IN ('title', 'DOI', 'date', 'url', 'extra', 'publicationTitle')
        """)
        item_fields: Dict[int, Dict[str, str]] = {}
        for item_id, field_name, val in cursor.fetchall():
            item_fields.setdefault(item_id, {})[field_name] = val

        # 5. Fetch creators (authors, editors, etc.)
        cursor.execute("""
            SELECT 
                ic.itemID,
                c.firstName,
                c.lastName,
                ct.creatorType,
                ic.orderIndex
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            ORDER BY ic.itemID, ic.orderIndex ASC
        """)
        item_creators: Dict[int, List[Tuple[str, str, str]]] = {}
        for item_id, first, last, ctype, _ in cursor.fetchall():
            item_creators.setdefault(item_id, []).append((first or "", last or "", ctype or ""))

        references: List[Reference] = []

        for item_id, key, type_name in items_raw:
            colls = item_collections.get(item_id, [])
            if collection_filter:
                # Filter by collection if specified
                if not any(collection_filter.lower() in c.lower() for c in colls):
                    continue

            attachments = pdf_attachments.get(item_id, [])
            has_pdf = len(attachments) > 0

            if only_missing_pdf and has_pdf:
                continue

            fields = item_fields.get(item_id, {})
            title = fields.get("title", "").strip()
            raw_doi = fields.get("DOI", "").strip()
            date_str = fields.get("date", "").strip()
            url = fields.get("url", "").strip()
            extra = fields.get("extra", "").strip()

            # Extract year from date string
            year = None
            if date_str:
                match = YEAR_REGEX.search(date_str)
                if match:
                    try:
                        year = int(match.group(1))
                    except ValueError:
                        pass

            # Extract DOI from extra if missing in DOI field
            if not raw_doi and extra:
                doi_match = DOI_EXTRA_REGEX.search(extra)
                if doi_match:
                    raw_doi = doi_match.group(1).strip()

            # Process authors
            creators = item_creators.get(item_id, [])
            author_names = []
            first_author_last = ""

            for first, last, ctype in creators:
                # Prefer authors over other creator types if possible
                full_name = f"{last}, {first}".strip(" ,") if last or first else ""
                if full_name:
                    author_names.append(full_name)
                if not first_author_last and last:
                    first_author_last = last

            ref = Reference(
                key=key,
                item_id=item_id,
                item_type=type_name,
                title=title,
                authors=author_names,
                first_author=first_author_last,
                year=year,
                doi=raw_doi or None,
                url=url or None,
                extra=extra or None,
                collections=colls,
                has_zotero_pdf=has_pdf,
                zotero_attachments=attachments
            )
            references.append(ref)

        return references
