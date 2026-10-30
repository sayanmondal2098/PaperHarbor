"""Local web UI for PaperHarbor (stdlib only, bound to localhost)."""

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from paperharbor.app import PaperHarborApp
from paperharbor.zotero.api_reader import ZoteroApiReader
from paperharbor.zotero.export_reader import ZoteroExportReader
from paperharbor.zotero.sqlite_reader import ZoteroSqliteReader, find_default_zotero_db

MAX_LOG_LINES = 500


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
            "key": r.key, "title": r.title, "authors": r.display_author, "year": r.display_year,
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
        else:
            self._send(404, "{}")

    def do_POST(self):
        # Reject cross-site requests (browser pages cannot set this header cross-origin without CORS)
        if self.headers.get("X-PaperHarbor") != "1":
            return self._send(403, json.dumps({"error": "forbidden"}))
        length = int(self.headers.get("Content-Length") or 0)
        try:
            cfg = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, json.dumps({"error": "bad json"}))
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


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>PaperHarbor</title>
<style>
body{font-family:Segoe UI,sans-serif;max-width:1100px;margin:20px auto;padding:0 16px;background:#f5f7fa;color:#222}
h1{margin-bottom:0}.sub{color:#666;margin-top:4px}
.card{background:#fff;border-radius:8px;padding:16px;margin:14px 0;box-shadow:0 1px 3px #0002}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}
label{font-size:13px;font-weight:600;display:block}input[type=text],input[type=number],select,input[type=password]{width:100%;padding:6px;box-sizing:border-box}
.full{grid-column:1/3}button{background:#0b6bcb;color:#fff;border:0;padding:10px 22px;border-radius:6px;font-size:15px;cursor:pointer}
button:disabled{background:#999}
progress{width:100%;height:18px}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:5px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
.s{padding:2px 6px;border-radius:4px;font-size:12px;white-space:nowrap}
.DOWNLOADED{background:#d4f4dd}.PAYWALLED_OR_OA_NOT_FOUND{background:#fff0c2}.DOWNLOAD_FAILED{background:#fbd0d0}.OA_BLOCKED_MANUAL{background:#ffd9a8}.ERROR{background:#fbd0d0}
pre{background:#111;color:#cfc;padding:10px;max-height:220px;overflow:auto;font-size:12px}
.stats span{margin-right:16px;font-weight:600}
</style></head><body>
<h1>PaperHarbor</h1><div class="sub">Zotero is read-only; PDFs are saved to your own folder.</div>
<div class="card"><div class="grid">
<div class="full"><label>Destination folder</label><div style="display:flex;gap:6px"><input type="text" id="dest_folder" placeholder="D:\\Research\\Papers"><button type="button" onclick="pickFolder()">Browse...</button></div></div>
<div><label>Zotero source</label><select id="src" onchange="srcChange()">
<option value="sqlite">Local zotero.sqlite</option><option value="export">Exported .json / .bib file</option><option value="api">Zotero Web API</option></select></div>
<div id="f_sqlite"><label>zotero.sqlite path (blank = auto-detect)</label><input type="text" id="zotero_path"></div>
<div id="f_export" style="display:none"><label>Export file path</label><input type="text" id="export_file"></div>
<div id="f_api" style="display:none"><label>API key</label><input type="password" id="api_key"></div>
<div id="f_api2" style="display:none"><label>User ID</label><input type="text" id="user_id"></div>
<div id="f_api3" style="display:none"><label>Group ID (optional)</label><input type="text" id="group_id"></div>
<div><label>Contact email (for OpenAlex/Unpaywall)</label><input type="text" id="email"></div>
<div><label>Limit (optional)</label><input type="number" id="limit" min="1"></div>
<div><label>Filename template</label><input type="text" id="template" value="{year}_{author}_{title}.pdf"></div>
<div><label><input type="checkbox" id="include_zotero_has_pdf"> Also fetch items that already have a Zotero PDF</label>
<label><input type="checkbox" id="force_redownload"> Re-download existing files</label></div>
<div class="full"><button type="button" onclick="loadLib()">Connect &amp; browse library</button> <span id="libmsg" class="sub"></span></div>
<div class="full">
<div id="lib" style="display:none">
<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
<select id="coll" onchange="renderLib()" style="width:auto"></select>
<input type="text" id="q" placeholder="Search title / author / DOI" oninput="renderLib()">
<label style="white-space:nowrap"><input type="checkbox" id="onlymiss" checked onchange="renderLib()"> Only without Zotero PDF</label>
</div>
<div style="margin-bottom:6px"><button type="button" onclick="selVisible(true)">Select shown</button> <button type="button" onclick="selVisible(false)">Deselect shown</button> <b id="selcount"></b></div>
<div style="max-height:300px;overflow:auto;border:1px solid #ddd"><table><tbody id="librows"></tbody></table></div>
<div class="sub">Only selected papers are processed. Connect to browse and select; skip browsing to process the whole library.</div>
</div></div>
<div class="full"><button id="go" onclick="start()">Start download</button> <span id="msg" style="color:#b00"></span></div>
</div></div>
<div class="card"><progress id="bar" value="0" max="1"></progress>
<div id="cur" class="sub"></div><div class="stats" id="stats"></div><div id="rep"></div></div>
<div class="card"><table><thead><tr><th>Status</th><th>Year</th><th>Author</th><th>Title</th><th>Source / File / Link</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="card"><pre id="log"></pre></div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function srcChange(){const v=$('src').value;
$('f_sqlite').style.display=v=='sqlite'?'':'none';$('f_export').style.display=v=='export'?'':'none';
for(const i of ['f_api','f_api2','f_api3'])$(i).style.display=v=='api'?'':'none';}
function srcCfg(){const cfg={},v=$('src').value;
if(v=='sqlite')cfg.zotero_path=$('zotero_path').value;
if(v=='export')cfg.export_file=$('export_file').value;
if(v=='api'){cfg.api_key=$('api_key').value;cfg.user_id=$('user_id').value;cfg.group_id=$('group_id').value;}
return cfg;}
const H={'X-PaperHarbor':'1','Content-Type':'application/json'};
let LIB=null,SEL=new Set();
async function pickFolder(){const r=await fetch('/api/pick-folder',{method:'POST',headers:H,body:JSON.stringify({initial:$('dest_folder').value})});
const p=(await r.json()).path;if(p)$('dest_folder').value=p;}
async function loadLib(){$('libmsg').textContent='Loading...';
const r=await fetch('/api/library',{method:'POST',headers:H,body:JSON.stringify(srcCfg())});const d=await r.json();
if(!r.ok){$('libmsg').textContent='Error: '+d.error;return;}
LIB=d;SEL=new Set();$('libmsg').textContent=d.items.length+' items loaded';$('lib').style.display='';
$('coll').innerHTML='<option value="">All items</option>'+d.collections.map(c=>`<option value="${esc(c.name)}">${esc(c.name)} (${c.count})</option>`).join('');
renderLib();}
function shown(){const q=$('q').value.toLowerCase(),c=$('coll').value,m=$('onlymiss').checked;
return LIB.items.filter(i=>(!c||i.collections.includes(c))&&(!m||!i.has_pdf)&&(!q||(i.title+' '+i.authors+' '+i.doi).toLowerCase().includes(q)));}
function renderLib(){const items=shown();
$('librows').innerHTML=items.map(i=>`<tr><td><input type="checkbox" data-k="${esc(i.key)}" ${SEL.has(i.key)?'checked':''} onchange="tog(this)"></td><td>${esc(i.year)}</td><td>${esc(i.authors)}</td><td>${esc(i.title)}${i.has_pdf?' <span class="s" style="background:#e3e8ff">has PDF</span>':''}</td></tr>`).join('');
$('selcount').textContent=SEL.size+' selected / '+items.length+' shown';}
function tog(e){e.checked?SEL.add(e.dataset.k):SEL.delete(e.dataset.k);$('selcount').textContent=SEL.size+' selected';}
function selVisible(on){for(const i of shown())on?SEL.add(i.key):SEL.delete(i.key);renderLib();}
async function start(){
const cfg=srcCfg();for(const k of ['dest_folder','email','limit','template'])cfg[k]=$(k).value;
if(LIB){if(!SEL.size){$('msg').textContent='Select at least one paper (or reload page to process the whole library).';return;}cfg.item_keys=[...SEL];}
cfg.include_zotero_has_pdf=$('include_zotero_has_pdf').checked;cfg.force_redownload=$('force_redownload').checked;
const r=await fetch('/api/start',{method:'POST',headers:H,body:JSON.stringify(cfg)});
$('msg').textContent=r.ok?'':(await r.json()).error;}
async function poll(){try{const s=await (await fetch('/api/status')).json();
$('go').disabled=s.running;$('bar').max=s.total||1;$('bar').value=s.current;
$('cur').textContent=s.running?`(${s.current}/${s.total}) ${s.title}`:(s.done?'Finished.':'Idle.');
$('stats').innerHTML=Object.entries(s.summary).map(([k,v])=>`<span>${esc(k)}: ${v}</span>`).join('');
$('rep').innerHTML=(s.error?`<div style="color:#b00">Error: ${esc(s.error)}</div>`:'')+(s.report?`CSV report: ${esc(s.report)}`:'');
$('rows').innerHTML=s.results.slice().reverse().map(r=>`<tr><td><span class="s ${r.status}">${esc(r.status)}</span></td><td>${esc(r.year)}</td><td>${esc(r.author)}</td><td>${esc(r.title)}</td><td>${esc(r.provider)} ${esc(r.file)} ${/^https?:/.test(r.url)?`<a href="${esc(r.url)}" target="_blank" rel="noopener">link</a>`:''}</td></tr>`).join('');
const l=$('log');l.textContent=s.logs.join('\\n');l.scrollTop=l.scrollHeight;}catch(e){}
setTimeout(poll,1000);}
fetch('/api/defaults').then(r=>r.json()).then(d=>{$('zotero_path').placeholder=d.zotero_path||'not detected'});
poll();
</script></body></html>
"""


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
