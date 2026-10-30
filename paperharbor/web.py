"""Local web UI for PaperHarbor (stdlib only, bound to localhost)."""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from paperharbor.app import PaperHarborApp
from paperharbor.zotero.api_reader import ZoteroApiReader
from paperharbor.zotero.export_reader import ZoteroExportReader
from paperharbor.zotero.reader_base import ZoteroReaderBase
from paperharbor.zotero.sqlite_reader import ZoteroSqliteReader, find_default_zotero_db

MAX_LOG_LINES = 500
MAX_REQUEST_BYTES = 8 * 1024 * 1024


class UploadedReferenceReader(ZoteroReaderBase):
    """Keep parsed upload references in memory after the temporary file is removed."""

    def __init__(self, references):
        self.references = references

    def get_references(self, collection_filter=None, only_missing_pdf=True):
        return [r for r in self.references if not only_missing_pdf or not r.has_zotero_pdf]


class JobState:
    """Thread-safe state of the single running download job."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.running = False
        self.done = False
        self.error = ""
        self.current = 0
        self.total = 0
        self.title = ""
        self.report_path = ""
        self.dest = ""
        self.logs = []
        self.app = None

    def snapshot(self):
        with self.lock:
            results = []
            if self.app:
                for r in list(self.app.reporter.results):
                    results.append({
                        "status": r.status.value,
                        "year": r.reference.display_year,
                        "author": r.reference.display_author,
                        "title": r.reference.title,
                        "doi": r.reference.clean_doi or "",
                        "provider": r.provider or "",
                        "file": r.saved_filename or "",
                        "url": r.publisher_url or r.reference.publisher_url or "",
                    })
            return {
                "running": self.running, "done": self.done, "error": self.error,
                "current": self.current, "total": self.total, "title": self.title,
                "report": self.report_path, "dest": self.dest,
                "logs": self.logs[-MAX_LOG_LINES:], "results": results,
                "summary": self.app.reporter.get_summary() if self.app else {},
            }


STATE = JobState()


class _LogHandler(logging.Handler):
    def emit(self, record):
        with STATE.lock:
            STATE.logs.append(self.format(record))


def _build_reader(cfg):
    if "upload_content" in cfg:
        name = cfg.get("upload_name", "")
        content = cfg["upload_content"]
        if not isinstance(name, str) or not isinstance(content, str):
            raise ValueError("Upload a BibTeX or CSL-JSON text file.")
        suffix = Path(name).suffix.lower()
        if suffix not in (".bib", ".bibtex", ".json"):
            raise ValueError("Supported uploads: .bib, .bibtex, and .json.")
        if not content.strip():
            raise ValueError("The uploaded file is empty.")
        if len(content.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("The uploaded file is too large (maximum 8 MB).")
        with tempfile.TemporaryDirectory(prefix="paperharbor_upload_") as folder:
            path = Path(folder) / ("references" + suffix)
            path.write_text(content.lstrip("\ufeff"), encoding="utf-8")
            refs = ZoteroExportReader(path).get_references(only_missing_pdf=False)
        if not refs or not any(r.title or r.doi or r.url for r in refs):
            raise ValueError("No usable references found. Check the file's BibTeX or CSL-JSON format.")
        # Selection must identify individual entries even with absent/duplicate export IDs.
        for index, ref in enumerate(refs):
            ref.key = f"upload-{index + 1}:{ref.key}"
        return UploadedReferenceReader(refs)
    if cfg.get("export_file"):
        return ZoteroExportReader(Path(cfg["export_file"]))
    if cfg.get("api_key"):
        return ZoteroApiReader(api_key=cfg["api_key"], user_id=cfg.get("user_id") or None,
                               group_id=cfg.get("group_id") or None)
    db = Path(cfg["zotero_path"]) if cfg.get("zotero_path") else find_default_zotero_db()
    if not db:
        raise RuntimeError("Could not auto-detect zotero.sqlite; provide its path.")
    return ZoteroSqliteReader(db_path=Path(db))


def _pick_folder(initial=""):
    """Open the native folder dialog on this machine (the server runs locally)."""
    script = (
        "import tkinter as tk\nfrom tkinter import filedialog\n"
        "r=tk.Tk();r.withdraw();r.attributes('-topmost',True)\n"
        "print(filedialog.askdirectory(initialdir=%r or None,title='Select destination folder',mustexist=False))"
    ) % initial
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    return os.path.normpath(out.stdout.strip()) if out.stdout.strip() else ""


def _load_library(cfg):
    refs = _build_reader(cfg).get_references(only_missing_pdf=False)
    counts = {}
    for r in refs:
        for c in r.collections:
            counts[c] = counts.get(c, 0) + 1
    return {
        "collections": [{"name": n, "count": c} for n, c in sorted(counts.items(), key=lambda x: x[0].lower())],
        "items": [{
            "key": r.key, "title": r.title, "authors": "; ".join(r.authors) or r.display_author, "year": r.display_year,
            "doi": r.clean_doi or "", "has_pdf": r.has_zotero_pdf, "collections": r.collections,
        } for r in refs],
    }


def _run_job(cfg):
    handler = _LogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        if not cfg.get("dest_folder"):
            raise ValueError("Destination folder is required.")

        def progress(idx, total, ref, _msg):
            with STATE.lock:
                STATE.current, STATE.total, STATE.title = idx, total, ref.title

        app = PaperHarborApp(
            reader=_build_reader(cfg),
            dest_folder=Path(cfg["dest_folder"]),
            email=cfg.get("email") or "paperharbor.downloader@gmail.com",
            skip_zotero_has_pdf=not cfg.get("include_zotero_has_pdf"),
            skip_existing_dest=not cfg.get("force_redownload"),
            filename_template=cfg.get("template") or "{year}_{author}_{title}.pdf",
            progress_callback=progress,
        )
        with STATE.lock:
            STATE.app = app
            STATE.dest = str(app.dest_folder)
        limit = int(cfg["limit"]) if cfg.get("limit") else None
        report = app.run(collection_filter=cfg.get("collection") or None, limit=limit,
                         item_keys=cfg.get("item_keys"))
        with STATE.lock:
            STATE.report_path = str(report)
    except Exception as e:  # surfaced to the UI
        with STATE.lock:
            STATE.error = str(e)
    finally:
        root.removeHandler(handler)
        with STATE.lock:
            STATE.running, STATE.done = False, True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE, "text/html")
        elif self.path == "/api/status":
            self._send(200, json.dumps(STATE.snapshot()))
        elif self.path == "/api/defaults":
            db = find_default_zotero_db()
            self._send(200, json.dumps({"zotero_path": str(db) if db else ""}))
        elif self.path in ("/static/style.css", "/static/app.js"):
            name = self.path.rsplit("/", 1)[-1]
            ctype = "text/css" if name.endswith(".css") else "application/javascript"
            self._send(200, (WEB_ASSETS / name).read_text(encoding="utf-8"), ctype)
        elif self.path == "/logo.svg":
            logo = Path(__file__).resolve().parent.parent / "assets" / "paperharbor-logo.svg"
            self._send(200, logo.read_text(encoding="utf-8"), "image/svg+xml")
        else:
            self._send(404, "{}")

    def do_POST(self):
        # Reject cross-site requests (browser pages cannot set this header cross-origin without CORS)
        if self.headers.get("X-PaperHarbor") != "1":
            return self._send(403, json.dumps({"error": "forbidden"}))
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, json.dumps({"error": "Invalid request length."}))
        if length < 0 or length > MAX_REQUEST_BYTES:
            return self._send(413, json.dumps({"error": "Request too large. Choose a smaller file (maximum 8 MB including request data)."}))
        try:
            cfg = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, json.dumps({"error": "bad json"}))
        if not isinstance(cfg, dict):
            return self._send(400, json.dumps({"error": "Expected a JSON object."}))
        if self.path == "/api/pick-folder":
            return self._send(200, json.dumps({"path": _pick_folder(cfg.get("initial", ""))}))
        if self.path == "/api/library":
            try:
                return self._send(200, json.dumps(_load_library(cfg)))
            except Exception as e:
                return self._send(400, json.dumps({"error": str(e)}))
        if self.path != "/api/start":
            return self._send(404, "{}")
        with STATE.lock:
            if STATE.running:
                return self._send(409, json.dumps({"error": "A job is already running."}))
            STATE.reset()
            STATE.running = True
        threading.Thread(target=_run_job, args=(cfg,), daemon=True).start()
        self._send(200, json.dumps({"ok": True}))


WEB_ASSETS = Path(__file__).with_name("web_assets")
PAGE = (WEB_ASSETS / "index.html").read_text(encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="PaperHarbor web UI")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"PaperHarbor web UI running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    main()
