#!/usr/bin/env python3
"""Small web UI and JSON API for the AUTOSAR Standards Fetcher.

Run:
    py -3 autosar_web.py --port 8080
Then open http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import autosar_mcp_server as mcp  # noqa: E402

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AUTOSAR Standards Fetcher</title>
<style>
body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; background:#f5f7fa; }
.card { background:#fff; padding:16px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,.08); margin-bottom:16px; }
input, select { padding:6px; margin:4px; }
button { padding:8px 14px; margin:4px; cursor:pointer; }
pre { background:#111; color:#eee; padding:12px; border-radius:6px; overflow:auto; max-height:420px; }
</style>
</head>
<body>
<h1>AUTOSAR Standards Fetcher</h1>
<div class="card">
<label>Output dir <input id="output_dir" value="AUTOSAR_Standards_Library" size="32"></label>
<label>Platform <input id="platform" placeholder="CP / Adaptive_Platform" size="22"></label>
<label>Release <input id="release" placeholder="R25-11" size="12"></label>
<label>Category <input id="category" placeholder="PDF" size="14"></label>
<label>Query <input id="query" placeholder="COM" size="14"></label>
<label><input type="checkbox" id="dry_run"> dry run</label>
<label><input type="checkbox" id="download_all"> download all matches</label>
<br>
<button onclick="versions()">Versions</button>
<button onclick="search()">Search</button>
<button onclick="download()">Download</button>
<button onclick="status()">Status</button>
</div>
<pre id="out">Ready.</pre>
<script>
function params() {
  return {
    output_dir: document.getElementById('output_dir').value,
    platform: document.getElementById('platform').value,
    release: document.getElementById('release').value,
    category: document.getElementById('category').value,
    query: document.getElementById('query').value,
    dry_run: document.getElementById('dry_run').checked,
    download_all: document.getElementById('download_all').checked
  };
}
async function call(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const t = await r.text();
  document.getElementById('out').textContent = t;
}
function versions() { call('/api/versions', params()); }
function search() { call('/api/search', params()); }
function download() { call('/api/download', params()); }
function status() { call('/api/status', params()); }
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, HTML)
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            body = {}
        try:
            if self.path == "/api/versions":
                od = mcp._output_dir(body.get("output_dir"))
                cache = mcp.discover(od, int(body.get("max_pages", mcp.DEFAULT_MAX_PAGES)),
                                     float(body.get("delay", mcp.DEFAULT_DELAY)), bool(body.get("refresh", False)))
                res = {"releases": mcp.list_versions(cache, body.get("platform"))}
            elif self.path == "/api/search":
                od = mcp._output_dir(body.get("output_dir"))
                cache = mcp.discover(od, int(body.get("max_pages", mcp.DEFAULT_MAX_PAGES)),
                                     float(body.get("delay", mcp.DEFAULT_DELAY)), bool(body.get("refresh", False)))
                limit = int(body.get("limit", 50))
                matches = mcp.search_assets(cache, body.get("query"), body.get("platform"),
                                           body.get("release"), body.get("category"), body.get("filename"), limit)
                res = {"count": len(matches), "matches": matches}
            elif self.path == "/api/download":
                od = mcp._output_dir(body.get("output_dir"))
                if body.get("url"):
                    assets = [{"url": body["url"], "platform": body.get("platform") or "",
                               "release": body.get("release") or "", "category": body.get("category") or "",
                               "filename": "", "referrer": ""}]
                else:
                    cache = mcp.discover(od, int(body.get("max_pages", mcp.DEFAULT_MAX_PAGES)),
                                         float(body.get("delay", mcp.DEFAULT_DELAY)), bool(body.get("refresh", False)))
                    matches = mcp.search_assets(cache, body.get("query"), body.get("platform"),
                                               body.get("release"), body.get("category"), body.get("filename"), 1000)
                    if not matches:
                        res = {"status": "no_matches"}
                        self._send(200, json.dumps(res), "application/json")
                        return
                    if not body.get("download_all") and len(matches) > 1:
                        res = {"status": "multiple_matches", "count": len(matches), "candidates": matches[:50]}
                        self._send(200, json.dumps(res), "application/json")
                        return
                    assets = matches if body.get("download_all") else [matches[0]]
                results = mcp.download_assets(od, assets, bool(body.get("dry_run", False)),
                                             float(body.get("delay", mcp.DEFAULT_DELAY)),
                                             int(body.get("max_pages", mcp.DEFAULT_MAX_PAGES)))
                res = {"status": "ok", "results": results}
            elif self.path == "/api/status":
                od = mcp._output_dir(body.get("output_dir"))
                manifest_path = od / "download_manifest.csv"
                counts = {}
                if manifest_path.is_file():
                    import csv
                    for row in csv.DictReader(manifest_path.open(encoding="utf-8-sig")):
                        counts[row.get("status", "")] = counts.get(row.get("status", ""), 0) + 1
                res = {"output_dir": str(od), "manifest_counts": counts}
            else:
                self._send(404, "not found", "text/plain")
                return
            self._send(200, json.dumps(res, default=str), "application/json")
        except Exception as exc:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(exc)}), "application/json")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="AUTOSAR Standards Fetcher web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AUTOSAR Standards Fetcher web UI: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
