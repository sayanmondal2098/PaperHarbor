"""Exercise uploads, selection handoff, and the local HTTP interface without network providers."""

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from paperharbor import web


BIB = """
@article{first,
  title = {Learning with {Nested} Models},
  author = {Smith, Jane and Doe, Alex},
  year = 2025,
  doi = {10.1234/first},
  url = {https://example.org/user@example/paper}
}
@article{second,
  title = "Another paper",
  author = {Doe, Alex},
  year = {2024},
  file = {paper.pdf}
}
"""


class TestWebUpload(unittest.TestCase):
    def config(self, content=BIB, name="references.bib"):
        return {"upload_name": name, "upload_content": content}

    def test_upload_reads_metadata_and_survives_temporary_file_cleanup(self):
        reader = web._build_reader(self.config())
        refs = reader.get_references(only_missing_pdf=False)
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0].title, "Learning with Nested Models")
        self.assertEqual(refs[0].year, 2025)
        self.assertEqual(refs[0].first_author, "Smith")
        self.assertEqual(refs[0].url, "https://example.org/user@example/paper")
        self.assertEqual(refs[0].doi, "10.1234/first")
        self.assertEqual(web._load_library(self.config())["items"][0]["authors"],
                         "Smith, Jane; Doe, Alex")
        self.assertEqual(len(reader.get_references()), 1)
        # Re-parsing for the download job must preserve the selection IDs.
        self.assertEqual(refs[0].key, web._build_reader(self.config()).get_references()[0].key)

    def test_invalid_uploads(self):
        for content, name in [("", "empty.bib"), ("not bibtex", "invalid.bib"),
                              (BIB, "wrong.txt"), ("@article{broken, title={unfinished}", "bad.bib")]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                web._build_reader(self.config(content, name))

    def test_json_upload_with_duplicate_or_missing_ids_is_selectable(self):
        content = json.dumps([{"title": "First"}, {"title": "Second"}])
        library = web._load_library(self.config(content, "references.json"))
        self.assertEqual(len({r["key"] for r in library["items"]}), 2)

    def test_selected_upload_entries_reach_download_pipeline(self):
        cfg = self.config()
        selected = web._load_library(cfg)["items"][0]["key"]
        with tempfile.TemporaryDirectory() as folder, patch.object(web, "STATE", web.JobState()):
            cfg.update(dest_folder=folder, item_keys=[selected])
            with patch("paperharbor.providers.aggregator.ProviderAggregator.find_candidates",
                       return_value=([], None)) as find:
                web._run_job(cfg)
            self.assertTrue(web.STATE.done)
            self.assertEqual(web.STATE.error, "")
            self.assertEqual(find.call_count, 1)
            self.assertEqual(find.call_args.args[0].title, "Learning with Nested Models")
            self.assertTrue(Path(web.STATE.report_path).is_file())
            self.assertEqual(len(web.STATE.app.reporter.results), 1)


class TestWebHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            conn.close()

    def test_assets_and_content_types(self):
        for path, mime in [("/", "text/html"), ("/static/app.js", "application/javascript"),
                           ("/static/style.css", "text/css"), ("/logo.svg", "image/svg+xml")]:
            with self.subTest(path=path):
                status, content_type, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(mime, content_type)
                self.assertTrue(body)

    def test_upload_endpoint_and_request_validation(self):
        headers = {"X-PaperHarbor": "1", "Content-Type": "application/json"}
        status, _, body = self.request("POST", "/api/library", json.dumps({
            "upload_name": "paper.bib", "upload_content": BIB
        }), headers)
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["items"]), 2)
        self.assertEqual(self.request("POST", "/api/library", "{}", {})[0], 403)
        self.assertEqual(self.request("POST", "/api/library", "[]", headers)[0], 400)
        oversized = dict(headers, **{"Content-Length": str(web.MAX_REQUEST_BYTES + 1)})
        self.assertEqual(self.request("POST", "/api/library", "", oversized)[0], 413)


if __name__ == "__main__":
    unittest.main()
