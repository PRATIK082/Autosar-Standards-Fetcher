#!/usr/bin/env python3
"""Minimal MCP (Model Context Protocol) server for the AUTOSAR Standards Fetcher.

It exposes discovery, search, version listing, download and status tools so AI
assistants can fetch AUTOSAR standards on demand. Transport is stdio JSON-RPC,
which works with Claude Desktop, Cursor, Cline, Continue and other MCP clients.

Run directly:
    py -3 autosar_mcp_server.py
or, after installation:
    autosar-fetcher-mcp
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import download_autosar_standards as das  # noqa: E402

DEFAULT_OUTPUT = Path("AUTOSAR_Standards_Library")
DEFAULT_MAX_PAGES = 10000
DEFAULT_DELAY = 0.2


def _output_dir(value: Optional[str]) -> Path:
    return Path(value).expanduser().resolve() if value else DEFAULT_OUTPUT.resolve()


def _normalize_platform(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    aliases = {
        "CP": "Classic_Platform",
        "CLASSIC": "Classic_Platform",
        "CLASSIC_PLATFORM": "Classic_Platform",
        "AP": "Adaptive_Platform",
        "ADAPTIVE": "Adaptive_Platform",
        "ADAPTIVE_PLATFORM": "Adaptive_Platform",
        "FO": "Foundation",
        "FOUNDATION": "Foundation",
        "AI": "Application_Interfaces",
        "APPLICATION_INTERFACES": "Application_Interfaces",
        "SHARED": "Shared",
        "UNCLASSIFIED": "Unclassified",
    }
    key = value.strip().upper().replace("-", "_").replace(" ", "_")
    return aliases.get(key, value.strip())


def _normalize_release(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().upper().replace(".", "_")


def discover(output_dir: Path, max_pages: int = DEFAULT_MAX_PAGES, delay: float = DEFAULT_DELAY,
            force: bool = False) -> Dict[str, Any]:
    cache_file = output_dir / "autosar_assets_cache.json"
    if not force and cache_file.is_file():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    output_dir.mkdir(parents=True, exist_ok=True)
    downloader = das.AutosarDownloader(output_dir, delay, max_pages, 2048, False, False, "auto", None)
    downloader.create_scaffold()
    downloader.load_existing_manifest()
    downloader.configure_robots()
    downloader.crawl()

    assets: List[Dict[str, Any]] = []
    for item in downloader.assets.values():
        url = item["url"]
        platform = das.infer_platform(url, item.get("context_platform") or None)
        release = das.infer_release(url, item.get("context_release") or None)
        assets.append({
            "url": url,
            "platform": platform,
            "release": release,
            "category": das.file_category(url),
            "filename": Path(urlparse(url).path).name,
            "referrer": item.get("referrer", ""),
        })

    cache = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages_visited": len(downloader.visited),
        "assets": assets,
    }
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def search_assets(cache: Dict[str, Any], query: Optional[str] = None, platform: Optional[str] = None,
                  release: Optional[str] = None, category: Optional[str] = None,
                  filename: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    platform = _normalize_platform(platform)
    release = _normalize_release(release)
    results: List[Dict[str, Any]] = []
    for asset in cache.get("assets", []):
        if platform and asset["platform"] != platform:
            continue
        if release and asset["release"] != release:
            continue
        if category and asset["category"] != category:
            continue
        if filename and filename.lower() not in asset["filename"].lower():
            continue
        if query:
            haystack = " ".join(str(asset.get(k, "")) for k in ("url", "filename", "platform", "release", "category")).lower()
            if query.lower() not in haystack:
                continue
        results.append(asset)
        if len(results) >= limit:
            break
    return results


def list_versions(cache: Dict[str, Any], platform: Optional[str] = None) -> List[str]:
    platform = _normalize_platform(platform)
    releases = {a["release"] for a in cache.get("assets", [])
                if not platform or a["platform"] == platform}
    return sorted(releases)


def download_assets(output_dir: Path, assets: List[Dict[str, Any]], dry_run: bool = False,
                    delay: float = DEFAULT_DELAY, max_pages: int = DEFAULT_MAX_PAGES) -> List[Dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloader = das.AutosarDownloader(output_dir, delay, max_pages, 2048, dry_run, False, "auto", None)
    downloader.create_scaffold()
    downloader.load_existing_manifest()
    results: List[Dict[str, Any]] = []
    for asset in assets:
        record = {
            "url": asset["url"],
            "referrer": asset.get("referrer", ""),
            "context_platform": asset.get("platform", ""),
            "context_release": asset.get("release", ""),
        }
        downloader.download_one(record)
        results.append(downloader.rows_by_url.get(asset["url"], {}))
    downloader.write_manifest()
    return results


# ---------------------------------------------------------------------------
# MCP protocol implementation (stdio JSON-RPC)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "autosar_versions",
        "description": "List available AUTOSAR releases, optionally filtered by platform.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "Classic_Platform, Adaptive_Platform, Foundation, ..."},
                "output_dir": {"type": "string"},
                "max_pages": {"type": "integer", "default": DEFAULT_MAX_PAGES},
                "delay": {"type": "number", "default": DEFAULT_DELAY},
                "refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "autosar_search",
        "description": "Search discovered AUTOSAR artifacts by keyword, platform, release, category or filename.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "platform": {"type": "string"},
                "release": {"type": "string", "description": "e.g. R25-11 or R4.4.0"},
                "category": {"type": "string"},
                "filename": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "output_dir": {"type": "string"},
                "max_pages": {"type": "integer", "default": DEFAULT_MAX_PAGES},
                "delay": {"type": "number", "default": DEFAULT_DELAY},
                "refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "autosar_download",
        "description": "Download one or more AUTOSAR artifacts. If multiple match and download_all is false, returns candidates instead of downloading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Exact artifact URL to download"},
                "query": {"type": "string"},
                "platform": {"type": "string"},
                "release": {"type": "string"},
                "category": {"type": "string"},
                "filename": {"type": "string"},
                "download_all": {"type": "boolean", "default": False},
                "dry_run": {"type": "boolean", "default": False},
                "output_dir": {"type": "string"},
                "max_pages": {"type": "integer", "default": DEFAULT_MAX_PAGES},
                "delay": {"type": "number", "default": DEFAULT_DELAY},
                "refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "autosar_status",
        "description": "Return manifest counts and TLS/page error information for an output directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
            },
        },
    },
]


def _tool_result(payload: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}]}


def handle_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    output_dir = _output_dir(args.get("output_dir"))
    max_pages = int(args.get("max_pages", DEFAULT_MAX_PAGES))
    delay = float(args.get("delay", DEFAULT_DELAY))
    refresh = bool(args.get("refresh", False))

    if name == "autosar_versions":
        cache = discover(output_dir, max_pages, delay, refresh)
        return _tool_result({"platform": args.get("platform"), "releases": list_versions(cache, args.get("platform"))})

    if name == "autosar_search":
        cache = discover(output_dir, max_pages, delay, refresh)
        limit = int(args.get("limit", 50))
        matches = search_assets(cache, args.get("query"), args.get("platform"), args.get("release"),
                                args.get("category"), args.get("filename"), limit)
        return _tool_result({"count": len(matches), "matches": matches})

    if name == "autosar_download":
        if args.get("url"):
            cache_assets = [{"url": args["url"], "platform": args.get("platform") or "",
                            "release": args.get("release") or "", "category": args.get("category") or "",
                            "filename": Path(urlparse(args["url"]).path).name, "referrer": ""}]
        else:
            cache = discover(output_dir, max_pages, delay, refresh)
            matches = search_assets(cache, args.get("query"), args.get("platform"), args.get("release"),
                                    args.get("category"), args.get("filename"), 1000)
            if not matches:
                return _tool_result({"status": "no_matches", "message": "No artifacts matched the supplied filters."})
            if not args.get("download_all") and len(matches) > 1:
                return _tool_result({"status": "multiple_matches", "count": len(matches),
                                    "candidates": matches[:50],
                                    "hint": "Set download_all=true or narrow filters to download."})
            cache_assets = matches if args.get("download_all") else [matches[0]]

        dry_run = bool(args.get("dry_run", False))
        results = download_assets(output_dir, cache_assets, dry_run, delay, max_pages)
        return _tool_result({"status": "ok", "dry_run": dry_run, "results": results})

    if name == "autosar_status":
        manifest_path = output_dir / "download_manifest.csv"
        counts: Dict[str, int] = {}
        if manifest_path.is_file():
            import csv
            for row in csv.DictReader(manifest_path.open(encoding="utf-8-sig")):
                counts[row.get("status", "")] = counts.get(row.get("status", ""), 0) + 1
        summary_path = output_dir / "DOWNLOAD_SUMMARY.txt"
        summary = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else ""
        return _tool_result({"output_dir": str(output_dir), "manifest_counts": counts, "summary": summary})

    raise ValueError(f"Unknown tool: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AUTOSAR Standards Fetcher MCP server (stdio).")
    parser.add_argument("--output-dir", default=None, help="Default output directory")
    args = parser.parse_args()
    global DEFAULT_OUTPUT
    if args.output_dir:
        DEFAULT_OUTPUT = Path(args.output_dir).expanduser().resolve()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            reply = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "autosar-standards-fetcher", "version": "1.0.0"},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            reply = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        elif method == "tools/list":
            reply = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        elif method == "tools/call":
            try:
                result = handle_tool(params.get("name"), params.get("arguments") or {})
                reply = {"jsonrpc": "2.0", "id": msg_id, "result": result}
            except Exception as exc:  # noqa: BLE001
                reply = {"jsonrpc": "2.0", "id": msg_id,
                         "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}}
        else:
            if msg_id is not None:
                reply = {"jsonrpc": "2.0", "id": msg_id,
                         "error": {"code": -32601, "message": f"Method not found: {method}"}}
            else:
                continue

        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
