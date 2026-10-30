"""Unit tests for CSL-JSON and BibTeX export readers."""

import json
import tempfile
import unittest
from pathlib import Path

from paperharbor.zotero.export_reader import ZoteroExportReader


class TestExportReader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_csl_json_reader(self):
        csl_data = [
            {
                "id": "item1",
                "type": "article-journal",
                "title": "Phishing Detection",
                "author": [{"family": "Smith", "given": "John"}],
                "issued": {"date-parts": [[2025, 4, 1]]},
                "DOI": "10.1145/123",
                "file": "path/to/paper.pdf"  # has PDF
            },
            {
                "id": "item2",
                "type": "paper-conference",
                "title": "Adversarial Machine Learning",
                "author": [{"family": "Doe", "given": "Jane"}],
                "issued": {"date-parts": [[2024]]},
                "DOI": "10.1109/456"
                # missing PDF
            }
        ]
        json_file = self.dir_path / "export.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(csl_data, f)

        reader = ZoteroExportReader(json_file)
        
        # All items
        all_refs = reader.get_references(only_missing_pdf=False)
        self.assertEqual(len(all_refs), 2)
        self.assertTrue(all_refs[0].has_zotero_pdf)
        self.assertFalse(all_refs[1].has_zotero_pdf)

        # Only missing PDF
        missing_refs = reader.get_references(only_missing_pdf=True)
        self.assertEqual(len(missing_refs), 1)
        self.assertEqual(missing_refs[0].key, "item2")
        self.assertEqual(missing_refs[0].display_author, "Doe")
        self.assertEqual(missing_refs[0].display_year, "2024")

    def test_bibtex_reader(self):
        bib_content = """
@article{smith2025phishing,
  title = {Phishing Detection},
  author = {Smith, John and Doe, Jane},
  year = {2025},
  doi = {10.1145/123},
  file = {C:\\Users\\User\\Zotero\\storage\\ABC\\smith.pdf}
}

@inproceedings{williams2023malware,
  title = {Malware Analysis},
  author = {Williams, Clara},
  year = {2023},
  doi = {10.1109/999}
}
"""
        bib_file = self.dir_path / "export.bib"
        bib_file.write_text(bib_content, encoding="utf-8")

        reader = ZoteroExportReader(bib_file)
        
        all_refs = reader.get_references(only_missing_pdf=False)
        self.assertEqual(len(all_refs), 2)
        self.assertTrue(all_refs[0].has_zotero_pdf)
        self.assertFalse(all_refs[1].has_zotero_pdf)

        missing_refs = reader.get_references(only_missing_pdf=True)
        self.assertEqual(len(missing_refs), 1)
        self.assertEqual(missing_refs[0].key, "williams2023malware")
        self.assertEqual(missing_refs[0].display_author, "Williams")
        self.assertEqual(missing_refs[0].display_year, "2023")


if __name__ == "__main__":
    unittest.main()
