"""Unit tests for Zotero SQLite database reader."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paperharbor.zotero.sqlite_reader import ZoteroSqliteReader


def create_mock_zotero_db(db_path: Path):
    """Creates a mock Zotero SQLite database matching official schema."""
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # 1. Schema setup
    c.execute("""
        CREATE TABLE itemTypes (
            itemTypeID INTEGER PRIMARY KEY,
            typeName TEXT
        )
    """)
    c.executemany("INSERT INTO itemTypes VALUES (?, ?)", [
        (1, "journalArticle"),
        (2, "conferencePaper"),
        (3, "book"),
        (14, "attachment"),
        (15, "note"),
        (16, "annotation"),
    ])

    c.execute("""
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER,
            key TEXT,
            libraryID INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE deletedItems (
            itemID INTEGER PRIMARY KEY,
            dateDeleted TEXT
        )
    """)

    c.execute("""
        CREATE TABLE itemAttachments (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            contentType TEXT,
            path TEXT
        )
    """)

    c.execute("""
        CREATE TABLE fields (
            fieldID INTEGER PRIMARY KEY,
            fieldName TEXT
        )
    """)
    c.executemany("INSERT INTO fields VALUES (?, ?)", [
        (1, "title"),
        (2, "DOI"),
        (3, "date"),
        (4, "url"),
        (5, "extra"),
    ])

    c.execute("""
        CREATE TABLE itemData (
            itemID INTEGER,
            fieldID INTEGER,
            valueID INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE itemDataValues (
            valueID INTEGER PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("""
        CREATE TABLE creators (
            creatorID INTEGER PRIMARY KEY,
            firstName TEXT,
            lastName TEXT
        )
    """)

    c.execute("""
        CREATE TABLE creatorTypes (
            creatorTypeID INTEGER PRIMARY KEY,
            creatorType TEXT
        )
    """)
    c.executemany("INSERT INTO creatorTypes VALUES (?, ?)", [
        (1, "author"),
        (2, "editor"),
    ])

    c.execute("""
        CREATE TABLE itemCreators (
            itemID INTEGER,
            creatorID INTEGER,
            creatorTypeID INTEGER,
            orderIndex INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT
        )
    """)
    c.execute("INSERT INTO collections VALUES (1, 'Cybersecurity')")

    c.execute("""
        CREATE TABLE collectionItems (
            collectionID INTEGER,
            itemID INTEGER
        )
    """)

    # 2. Insert test items
    # Item 101: Has PDF attachment in Zotero
    c.execute("INSERT INTO items VALUES (101, 1, 'KEY101', 1)")
    # Item 102: Missing PDF in Zotero (target for download!)
    c.execute("INSERT INTO items VALUES (102, 1, 'KEY102', 1)")
    # Item 103: In Trash (deleted)
    c.execute("INSERT INTO items VALUES (103, 1, 'KEY103', 1)")
    c.execute("INSERT INTO deletedItems VALUES (103, '2026-01-01')")
    # Item 104: Standalone attachment (should be excluded)
    c.execute("INSERT INTO items VALUES (104, 14, 'KEY104', 1)")
    # Item 105: Missing PDF in Zotero, inside collection 'Cybersecurity'
    c.execute("INSERT INTO items VALUES (105, 2, 'KEY105', 1)")
    c.execute("INSERT INTO collectionItems VALUES (1, 105)")

    # Attachments:
    # Item 101 has an attached PDF:
    c.execute("INSERT INTO itemAttachments VALUES (201, 101, 'application/pdf', 'storage:paper.pdf')")

    # Item metadata values
    # Value IDs:
    # 1: "Phishing Detection in 2025"
    # 2: "10.1145/123456"
    # 3: "2025-05-12"
    # 4: "Zero-Day Exploit Analysis"
    # 5: "10.1109/987654"
    # 6: "2024"
    # 7: "Network Intrusion Benchmark"
    # 8: "10.1000/netbench"
    # 9: "2023"
    c.executemany("INSERT INTO itemDataValues VALUES (?, ?)", [
        (1, "Phishing Detection in 2025"),
        (2, "10.1145/123456"),
        (3, "2025-05-12"),
        (4, "Zero-Day Exploit Analysis"),
        (5, "10.1109/987654"),
        (6, "2024"),
        (7, "Network Intrusion Benchmark"),
        (8, "10.1000/netbench"),
        (9, "2023"),
    ])

    # Connect fields to items
    # Item 101
    c.executemany("INSERT INTO itemData VALUES (?, ?, ?)", [
        (101, 1, 1),
        (101, 2, 2),
        (101, 3, 3),
    ])
    # Item 102
    c.executemany("INSERT INTO itemData VALUES (?, ?, ?)", [
        (102, 1, 4),
        (102, 2, 5),
        (102, 3, 6),
    ])
    # Item 105
    c.executemany("INSERT INTO itemData VALUES (?, ?, ?)", [
        (105, 1, 7),
        (105, 2, 8),
        (105, 3, 9),
    ])

    # Creators
    # Creator 1: Alice Smith
    # Creator 2: Bob Jones
    c.executemany("INSERT INTO creators VALUES (?, ?, ?)", [
        (1, "Alice", "Smith"),
        (2, "Bob", "Jones"),
    ])
    c.execute("INSERT INTO itemCreators VALUES (101, 1, 1, 0)")
    c.execute("INSERT INTO itemCreators VALUES (102, 2, 1, 0)")
    c.execute("INSERT INTO itemCreators VALUES (105, 1, 1, 0)")

    conn.commit()
    conn.close()


class TestZoteroSqliteReader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "zotero.sqlite"
        create_mock_zotero_db(self.db_path)
        self.reader = ZoteroSqliteReader(db_path=self.db_path, use_snapshot=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extract_all_references(self):
        refs = self.reader.get_references(only_missing_pdf=False)
        keys = [r.key for r in refs]
        
        # KEY101 (has PDF), KEY102 (no PDF), KEY105 (no PDF)
        self.assertIn("KEY101", keys)
        self.assertIn("KEY102", keys)
        self.assertIn("KEY105", keys)
        
        # KEY103 is deleted, KEY104 is attachment item
        self.assertNotIn("KEY103", keys)
        self.assertNotIn("KEY104", keys)

    def test_detect_existing_pdf(self):
        refs = self.reader.get_references(only_missing_pdf=False)
        ref_map = {r.key: r for r in refs}

        self.assertTrue(ref_map["KEY101"].has_zotero_pdf)
        self.assertEqual(len(ref_map["KEY101"].zotero_attachments), 1)

        self.assertFalse(ref_map["KEY102"].has_zotero_pdf)
        self.assertEqual(len(ref_map["KEY102"].zotero_attachments), 0)

    def test_filter_only_missing_pdf(self):
        refs = self.reader.get_references(only_missing_pdf=True)
        keys = [r.key for r in refs]
        
        # KEY101 should be skipped because it already has a PDF!
        self.assertNotIn("KEY101", keys)
        self.assertIn("KEY102", keys)
        self.assertIn("KEY105", keys)

    def test_filter_by_collection(self):
        refs = self.reader.get_references(collection_filter="Cybersecurity", only_missing_pdf=False)
        keys = [r.key for r in refs]
        self.assertEqual(keys, ["KEY105"])

    def test_metadata_extraction(self):
        refs = self.reader.get_references(only_missing_pdf=False)
        ref_map = {r.key: r for r in refs}

        r101 = ref_map["KEY101"]
        self.assertEqual(r101.title, "Phishing Detection in 2025")
        self.assertEqual(r101.doi, "10.1145/123456")
        self.assertEqual(r101.year, 2025)
        self.assertEqual(r101.display_author, "Smith")


if __name__ == "__main__":
    unittest.main()
