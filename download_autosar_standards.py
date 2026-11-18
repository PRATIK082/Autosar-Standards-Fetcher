#!/usr/bin/env python3
"""Download publicly linked AUTOSAR standards artifacts into a release-oriented library.

Uses only Python's standard library. It does not log in, bypass access controls,
probe private endpoints, or crawl outside the official autosar.org standards area.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple

BASE = "https://www.autosar.org"
SEEDS = [
    f"{BASE}/standards",
    f"{BASE}/standards/classic-platform",
    f"{BASE}/standards/adaptive-platform",
    f"{BASE}/standards/foundation",
    f"{BASE}/standards/classic-platform/application-interfaces",
    f"{BASE}/standards/R25-11",
    f"{BASE}/search",
]
OFFICIAL_HOSTS = {"autosar.org", "www.autosar.org"}
USER_AGENT = "AUTOSAR-Standards-Downloader/1.0 (public-link archival; low-rate; no authentication)"

# AUTOSAR standards files can include PDF specifications and ZIP packages containing
# XML schemas, ARXML examples, spreadsheets, or other supplementary artifacts.
DOCUMENT_EXTS = {
    ".pdf", ".zip", ".7z", ".rar", ".gz", ".tgz", ".tar",
    ".xls", ".xlsx", ".xlsm", ".ods", ".csv",
    ".xml", ".xsd", ".arxml", ".json", ".yaml", ".yml", ".txt",
    ".sha256", ".sha512", ".md5", ".asc",
    ".doc", ".docx", ".ppt", ".pptx", ".rtf", ".odt", ".odp",
    ".html", ".htm", ".md", ".drawio", ".vsdx", ".sch", ".dtd",
}
PLATFORM_DIRS = {
    "Classic_Platform": "CP",
    "Adaptive_Platform": "AP",
    "Foundation": "FO",
    "Shared": "SHARED",
    "Application_Interfaces": "AI",
    "Unclassified": "UNKNOWN",
}
PLATFORM_NAME_MAP = {
    "CP": "Classic_Platform",
    "AP": "Adaptive_Platform",
    "FO": "Foundation",
    "AI": "Application_Interfaces",
}
RELEASE_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])(R\d{2}-\d{2})(?![A-Za-z0-9])", re.I),
    re.compile(r"(?<![A-Za-z0-9])(R?\d+\.\d+(?:\.\d+)?)(?![A-Za-z0-9])", re.I),
]

RELEASE_CATALOG = {
    "Classic_Platform": ["R26-11", "R25-11", "R24-11", "R23-11", "R22-11", "R21-11", "R20-11", "R19-11", "R4.4.0", "R4.3.1", "4.2", "4.1", "4.0", "3.2", "3.1", "3.0", "2.0"],
    "Adaptive_Platform": ["R26-11", "R25-11", "R24-11", "R23-11", "R22-11", "R21-11", "R20-11", "R19-11", "R18-10", "R19-03", "R18-03", "R17-10", "R17-03"],
    "Foundation": ["R26-11", "R25-11", "R24-11", "R23-11", "R22-11", "R21-11", "R20-11", "R19-11", "R1.5.1", "R1.5.0", "R1.4.0", "R1.3.0", "R1.2.0", "R1.1.0"],
}
CATEGORIES = ["PDF", "Archives", "Spreadsheets", "XML_XSD_ARXML", "Office_Documents", "Text_and_Data", "Other"]

MANIFEST_FIELDS = [
    "url", "status", "relative_path", "bytes", "sha256", "content_type",
    "http_status", "referrer", "error", "downloaded_at_utc",
]


def official_host(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return host in OFFICIAL_HOSTS or host.endswith(".autosar.org")
    except Exception:
        return False


def normalize_url(url: str, base_url: Optional[str] = None) -> Optional[str]:
    """Resolve, canonicalize and reject non-HTTPS/non-official URLs."""
    if base_url:
        url = urllib.parse.urljoin(base_url, url)
    url = html.unescape(url.strip())
    if not url or url.startswith(("mailto:", "javascript:", "tel:", "data:")):
        return None
    p = urllib.parse.urlsplit(url)
    if p.scheme.lower() not in {"http", "https"} or not p.netloc:
        return None
    if not official_host(url):
        return None
    scheme = "https"
    host = (p.hostname or "").lower()
    if host not in OFFICIAL_HOSTS and not host.endswith(".autosar.org"):
        return None
    # Official site is canonicalized to www; preserve non-standard subdomains only when present.
    netloc = "www.autosar.org" if host in OFFICIAL_HOSTS else host
    path = p.path or "/"
    # Keep search query parameters because the website may use them for pagination/filtering.
    query = p.query
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def in_scope_page(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    path = p.path.lower()
    if path == "/search" or path.startswith("/search/"):
        # The search endpoint exposes many faceted-filter combinations. Crawling all of
        # them is combinatorially explosive and only duplicates documents already present
        # in the unfiltered search results. Keep the base search and its pagination, but
        # skip URLs that add category/platform/architecture-element filters.
        query = urllib.parse.unquote(p.query).lower()
        if "tx_solr[filter]" in query or "tx_solr%5bfilter%5d" in query:
            return False
        return True
    return path == "/standards" or path.startswith("/standards/")


def is_document_url(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    path = p.path.lower()
    # CMS sitemap endpoints are crawl navigation, not downloadable artifacts.
    if path == "/sitemap.xml" or path.startswith("/sitemap.xml/"):
        return False
    if "/fileadmin/standards/" in path:
        # Only files with document-like extensions are treated as artifacts. Avoid accidentally
        # downloading stylesheets/scripts/images if a CMS link is malformed.
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in DOCUMENT_EXTS or not suffix
    return PurePosixPath(path).suffix.lower() in DOCUMENT_EXTS


def release_from_text(text: str) -> Optional[str]:
    for pattern in RELEASE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).upper()
            if not value.startswith("R") and re.match(r"\d{2}-\d{2}$", value):
                value = "R" + value
            return value
    return None


def infer_release(url: str, context_release: Optional[str] = None) -> str:
    releases = infer_all_releases(url)
    if releases:
        return releases[0]
    if context_release:
        return context_release.replace(".", "_")
    return "Unversioned"


def infer_all_releases(url: str) -> List[str]:
    """Return every release token in the URL path (e.g. combined R18-10_R4.4.0_R1.5.0 folders)."""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    found: List[str] = []
    for pattern in RELEASE_PATTERNS:
        for match in pattern.finditer(path):
            value = match.group(1).upper()
            if not value.startswith("R") and re.match(r"\d{2}-\d{2}$", value):
                value = "R" + value
            value = value.replace(".", "_")
            if value not in found:
                found.append(value)
    return found


def infer_platform(url: str, context_platform: Optional[str] = None) -> str:
    p = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(p.path)
    name = PurePosixPath(path).name
    upper_path = path.upper()
    upper_name = name.upper()
    for token, folder in PLATFORM_NAME_MAP.items():
        if f"/{token}/" in upper_path or upper_name.startswith(f"AUTOSAR_{token}_"):
            return folder
    lower_path = path.lower()
    if "application-interfaces" in lower_path or upper_name.startswith("AUTOSAR_AI_"):
        return "Application_Interfaces"
    if "classic-platform" in lower_path:
        return "Classic_Platform"
    if "adaptive-platform" in lower_path:
        return "Adaptive_Platform"
    if "/foundation" in lower_path or "foundation" in upper_name:
        return "Foundation"
    if context_platform:
        return context_platform
    return "Shared" if "/standards/" in lower_path or "/fileadmin/standards/" in lower_path else "Unclassified"


def file_category(url: str) -> str:
    suffix = PurePosixPath(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix == ".pdf": return "PDF"
    if suffix in {".zip", ".7z", ".rar", ".gz", ".tgz", ".tar"}: return "Archives"
    if suffix in {".xls", ".xlsx", ".xlsm", ".ods", ".csv"}: return "Spreadsheets"
    if suffix in {".xml", ".xsd", ".arxml", ".dtd"}: return "XML_XSD_ARXML"
    if suffix in {".doc", ".docx", ".ppt", ".pptx", ".rtf", ".odt", ".odp"}: return "Office_Documents"
    if suffix in {".json", ".yaml", ".yml", ".txt", ".html", ".htm", ".md"}: return "Text_and_Data"
    if suffix in {".sha256", ".sha512", ".md5", ".asc"}: return "Text_and_Data"
    return "Other"


def safe_filename(name: str) -> str:
    name = urllib.parse.unquote(name).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.rstrip(" .")
    if not name or name in {".", ".."}:
        name = "unnamed_download"
    # Windows reserved filenames are invalid even when they have extensions.
    stem = name.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"COM[1-9]", stem) or re.fullmatch(r"LPT[1-9]", stem):
        name = "_" + name
    if len(name) > 180:
        suffix = PurePosixPath(name).suffix
        name = name[: max(1, 180 - len(suffix))] + suffix
    return name


class LinkParser(HTMLParser):
    ATTRS = ("href", "src", "data-href", "data-src", "data-url", "data-document-url", "data-download-url", "data-file", "formaction")
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []
    def handle_starttag(self, tag: str, attrs) -> None:
        for key, value in attrs:
            if key and value and key.lower() in self.ATTRS:
                self.links.append(value)


@dataclass
class PageJob:
    url: str
    context_platform: Optional[str] = None
    context_release: Optional[str] = None
    depth: int = 0
    referrer: str = ""


class AutosarDownloader:
    def __init__(self, output_dir: Path, delay: float, max_pages: int, max_file_mb: int,
                 dry_run: bool = False, ignore_robots: bool = False,
                 tls_backend: str = "auto", ca_bundle: Optional[Path] = None,
                 selected_platforms: Optional[Set[str]] = None,
                 selected_releases: Optional[Set[str]] = None,
                 selected_categories: Optional[Set[str]] = None) -> None:
        self.output_dir = output_dir.resolve()
        self.delay = max(0.0, delay)
        self.max_pages = max_pages
        self.max_file_bytes = max_file_mb * 1024 * 1024
        self.dry_run = dry_run
        self.ignore_robots = ignore_robots
        self.ssl_context, self.tls_backend_used = self.make_ssl_context(tls_backend, ca_bundle)
        self.selected_platforms = selected_platforms
        self.selected_releases = selected_releases
        self.selected_categories = selected_categories
        self.page_errors = 0
        self.tls_error = ""
        self.queue: deque[PageJob] = deque()
        self.queued_keys: Set[str] = set()
        self.visited: Set[str] = set()
        self.assets: Dict[str, Dict[str, str]] = {}
        self.last_request_at = 0.0
        self.robot_parser = None
        self.sitemap_urls: List[str] = []
        self.manifest_path = self.output_dir / "download_manifest.csv"
        self.rows_by_url: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def make_ssl_context(tls_backend: str, ca_bundle: Optional[Path]):
        """Build a certificate-verifying TLS context; never disable verification.

        On Windows, truststore uses the native Windows certificate store. It is preferred
        in auto mode because corporate/managed root certificates may be installed there.
        Certifi is the next choice for a maintained public CA bundle. The OpenSSL default
        context is the final fallback. An explicit CA bundle always takes precedence.
        """
        if ca_bundle is not None:
            bundle = ca_bundle.expanduser().resolve()
            if not bundle.is_file():
                raise RuntimeError(f"CA bundle does not exist: {bundle}")
            context = ssl.create_default_context()
            # Add the approved CA to the normal trust roots rather than replacing public roots.
            context.load_verify_locations(cafile=str(bundle))
            return context, f"system roots + custom CA bundle ({bundle})"

        if tls_backend in {"auto", "truststore"}:
            try:
                import truststore  # type: ignore
                return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), "Windows/OS trust store (truststore)"
            except ImportError:
                if tls_backend == "truststore":
                    raise RuntimeError(
                        "TLS backend 'truststore' was selected but is not installed. Run: "
                        "py -3 -m pip install --user truststore"
                    )

        if tls_backend in {"auto", "certifi"}:
            try:
                import certifi  # type: ignore
                return ssl.create_default_context(cafile=certifi.where()), "certifi CA bundle"
            except ImportError:
                if tls_backend == "certifi":
                    raise RuntimeError(
                        "TLS backend 'certifi' was selected but is not installed. Run: "
                        "py -3 -m pip install --user certifi"
                    )

        # 'openssl' deliberately uses the configured Python/OpenSSL default CA paths.
        return ssl.create_default_context(), "Python/OpenSSL default CA paths"

    @staticmethod
    def is_certificate_verification_error(exc: BaseException) -> bool:
        text = str(exc).lower()
        reason = getattr(exc, "reason", None)
        return (
            isinstance(exc, ssl.SSLCertVerificationError)
            or isinstance(reason, ssl.SSLCertVerificationError)
            or "certificate_verify_failed" in text
            or "unable to get local issuer certificate" in text
            or "certificate verify failed" in text
        )

    def log(self, message: str) -> None:
        print(message, flush=True)

    def request(self, url: str, timeout: int = 40, retries: int = 3):
        """Perform a polite, certificate-verifying HTTP request with small retries.

        Transient network failures (timeouts, dropped connections, temporary DNS/TLS
        handshake issues) are retried a few times so a long unattended download run
        is not aborted by a single flaky connection. Certificate verification errors
        are not retried silently forever; they surface normally.
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(max(1, retries)):
            wait = self.delay - (time.monotonic() - self.last_request_at)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,application/zip,*/*;q=0.8"})
            self.last_request_at = time.monotonic()
            try:
                return urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context)
            except Exception as exc:  # noqa: BLE001 - retry transient network failures
                last_exc = exc
                if self.is_certificate_verification_error(exc):
                    raise
                if attempt + 1 >= retries:
                    break
                self.log(f"[retry {attempt + 1}/{retries - 1}] {url}: {exc}")
                time.sleep(min(2 ** attempt, 8))
        assert last_exc is not None
        raise last_exc

    def configure_robots(self) -> None:
        robots_url = f"{BASE}/robots.txt"
        try:
            with self.request(robots_url, timeout=15) as response:
                body = response.read(1_000_000).decode("utf-8", errors="replace")
            from urllib.robotparser import RobotFileParser
            self.robot_parser = RobotFileParser()
            self.robot_parser.set_url(robots_url)
            self.robot_parser.parse(body.splitlines())
            for line in body.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap = normalize_url(line.split(":", 1)[1].strip())
                    if sitemap:
                        self.sitemap_urls.append(sitemap)
            self.log("[robots] robots.txt loaded.")
        except Exception as exc:
            self.robot_parser = None
            if self.is_certificate_verification_error(exc):
                self.tls_error = str(exc)
                self.log(f"[TLS ERROR] Certificate verification failed while connecting to {robots_url}: {exc}")
                self.log_tls_help()
            else:
                self.log(f"[robots] Could not read robots.txt ({exc}). Staying limited to official standards URLs and low request rate.")

    def log_tls_help(self) -> None:
        self.log("[TLS help] The downloader intentionally does not disable TLS verification.")
        self.log("[TLS help] First check Windows date/time, then update Python and its certificates.")
        self.log("[TLS help] On Windows, try: py -3 -m pip install --user truststore certifi")
        self.log("[TLS help] Then rerun. The auto backend prefers the Windows/OS trust store when truststore is installed.")
        self.log(r"[TLS help] If your organization uses HTTPS inspection, install its approved root CA in Windows or pass --ca-bundle C:\path\to\approved-root.pem.")

    def allowed_by_robots(self, url: str) -> bool:
        if self.ignore_robots or self.robot_parser is None:
            return True
        try:
            return self.robot_parser.can_fetch(USER_AGENT, url)
        except Exception:
            return False

    def load_existing_manifest(self) -> None:
        if not self.manifest_path.exists():
            return
        try:
            with self.manifest_path.open("r", newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    if not row.get("url"):
                        continue
                    # Self-heal: drop CMS sitemap endpoints previously recorded as artifacts.
                    if urllib.parse.urlparse(row["url"]).path.lower() == "/sitemap.xml":
                        stale = (self.output_dir / Path(row.get("relative_path") or "")).resolve() \
                            if row.get("relative_path") else None
                        try:
                            if stale and stale.is_file() and self.output_dir.resolve() in stale.parents:
                                stale.unlink()
                        except OSError:
                            pass
                        continue
                    self.rows_by_url[row["url"]] = row
        except Exception as exc:
            self.log(f"[manifest] Existing manifest could not be read; a new one will be created: {exc}")

    def write_manifest(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Use a unique temp name plus retries so concurrent runs on the same
        # library cannot corrupt the manifest (previously WinError 5).
        for attempt in range(5):
            tmp = self.manifest_path.with_name(f"download_manifest.{os.getpid()}.{attempt}.csv.tmp")
            try:
                with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
                    writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
                    writer.writeheader()
                    for url in sorted(self.rows_by_url):
                        writer.writerow({field: self.rows_by_url[url].get(field, "") for field in MANIFEST_FIELDS})
                os.replace(tmp, self.manifest_path)
                return
            except PermissionError:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))
            except OSError:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                raise

    def offer_asset(self, url: str, referrer: str, context_platform: Optional[str], context_release: Optional[str]) -> None:
        normalized = normalize_url(url, referrer or None)
        if not normalized or not official_host(normalized):
            return
        if not is_document_url(normalized):
            return
        if not self.allowed_by_robots(normalized):
            self.log(f"[robots skip] {normalized}")
            return
        existing = self.assets.get(normalized)
        record = {
            "url": normalized,
            "referrer": referrer,
            "context_platform": context_platform or "",
            "context_release": context_release or "",
        }
        if existing:
            # Prefer explicit release/platform context over shared fallback.
            if existing.get("context_platform") in {"", "Shared", "Unclassified"} and record["context_platform"]:
                existing["context_platform"] = record["context_platform"]
            if not existing.get("context_release") and record["context_release"]:
                existing["context_release"] = record["context_release"]
        else:
            self.assets[normalized] = record

    def enqueue_page(self, job: PageJob) -> None:
        normalized = normalize_url(job.url)
        if not normalized or not in_scope_page(normalized) or not self.allowed_by_robots(normalized):
            return
        key = normalized
        if key not in self.queued_keys and key not in self.visited:
            self.queue.append(PageJob(normalized, job.context_platform, job.context_release, job.depth, job.referrer))
            self.queued_keys.add(key)

    def add_sitemap_content(self, url: str) -> None:
        try:
            with self.request(url, timeout=25) as response:
                body = response.read(20_000_000)
            root = ET.fromstring(body)
            locs = [node.text.strip() for node in root.iter() if node.tag.lower().endswith("loc") and node.text and node.text.strip()]
            for loc in locs:
                normalized = normalize_url(loc)
                if not normalized:
                    continue
                if is_document_url(normalized):
                    self.offer_asset(normalized, url, None, None)
                elif in_scope_page(normalized):
                    self.enqueue_page(PageJob(normalized, infer_platform(normalized), release_from_text(normalized), 0, url))
            self.log(f"[sitemap] {url}: inspected {len(locs)} entries")
        except Exception as exc:
            self.log(f"[sitemap] Skipped {url}: {exc}")

    def crawl(self) -> None:
        if self.tls_error:
            self.log("[crawl skipped] TLS certificate verification failed on the initial connection; no standards pages were crawled.")
            return
        for seed in SEEDS:
            self.enqueue_page(PageJob(seed, infer_platform(seed), release_from_text(seed), 0, "seed"))
        for sitemap in self.sitemap_urls:
            self.add_sitemap_content(sitemap)

        while self.queue and len(self.visited) < self.max_pages:
            job = self.queue.popleft()
            self.queued_keys.discard(job.url)
            if job.url in self.visited:
                continue
            self.visited.add(job.url)
            self.log(f"[page {len(self.visited)}/{self.max_pages}] {job.url}")
            try:
                with self.request(job.url) as response:
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    final_url = normalize_url(response.geturl()) or job.url
                    if not official_host(final_url):
                        self.log(f"[skip redirect outside AUTOSAR] {job.url} -> {response.geturl()}")
                        continue
                    payload = response.read(15_000_000)
                if "html" not in content_type and not payload.lstrip().startswith((b"<!doctype html", b"<html", b"<?xml")):
                    # It may be a linked non-HTML asset despite an extensionless URL.
                    if is_document_url(job.url):
                        self.offer_asset(job.url, job.referrer, job.context_platform, job.context_release)
                    continue
                text_body = payload.decode("utf-8", errors="replace")
                parser = LinkParser()
                parser.feed(text_body)
                page_platform = infer_platform(job.url, job.context_platform)
                page_release = infer_release(job.url, job.context_release)
                for link in parser.links:
                    normalized = normalize_url(link, final_url)
                    if not normalized:
                        continue
                    if is_document_url(normalized):
                        self.offer_asset(normalized, final_url, page_platform, page_release)
                    elif in_scope_page(normalized):
                        link_platform = infer_platform(normalized, page_platform)
                        link_release = infer_release(normalized, page_release)
                        self.enqueue_page(PageJob(normalized, link_platform, link_release, job.depth + 1, final_url))
                # Some CMS pages put public file URLs into simple JS/config strings.
                for candidate in re.findall(r"(?:https?://www\.autosar\.org)?/fileadmin/standards/[^\s\"'<>]+", text_body, flags=re.I):
                    normalized = normalize_url(candidate, final_url)
                    if normalized:
                        self.offer_asset(normalized, final_url, page_platform, page_release)
            except urllib.error.HTTPError as exc:
                self.page_errors += 1
                self.log(f"[page error] HTTP {exc.code}: {job.url}")
            except Exception as exc:
                self.page_errors += 1
                if self.is_certificate_verification_error(exc):
                    self.tls_error = str(exc)
                    self.log(f"[TLS ERROR] Certificate verification failed for {job.url}: {exc}")
                    self.log_tls_help()
                    break
                self.log(f"[page error] {job.url}: {exc}")
        if self.queue:
            self.log(f"[warning] Page limit reached ({self.max_pages}); {len(self.queue)} page(s) remain undiscovered.")
        self.log(f"[crawl complete] pages={len(self.visited)}, artifact_urls={len(self.assets)}")

    def choose_target(self, asset: Dict[str, str]) -> Path:
        url = asset["url"]
        p = urllib.parse.urlparse(url)
        remote_name = PurePosixPath(p.path).name
        if not remote_name:
            remote_name = "downloaded_artifact"
        filename = safe_filename(remote_name)
        platform = infer_platform(url, asset.get("context_platform") or None)
        release = infer_release(url, asset.get("context_release") or None)
        if platform not in PLATFORM_DIRS:
            platform = "Unclassified"
        relative = Path(platform) / release / file_category(url) / filename
        target = self.output_dir / relative
        if target.exists():
            row = self.rows_by_url.get(url, {})
            if row.get("relative_path") == relative.as_posix():
                return target
            # Avoid silently overwriting another official artifact with the same filename.
            suffix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
            target = target.with_name(f"{target.stem}__{suffix}{target.suffix}")
        return target

    def ensure_release_mirrors(self, url: str, primary_target: Path) -> None:
        """Mirror a downloaded file into every release folder named in its URL.

        Combined AUTOSAR folders (e.g. R18-10_R4.4.0_R1.5.0) serve several
        releases from one file. Mirroring keeps each per-version folder
        complete without re-downloading. Missing/stale copies are refreshed.
        """
        try:
            platform = infer_platform(url)
            if platform not in PLATFORM_DIRS:
                return
            category = file_category(url)
            try:
                primary_size = primary_target.stat().st_size
            except OSError:
                return
            for extra in infer_all_releases(url)[1:]:
                mirror = self.output_dir / platform / extra / category / primary_target.name
                try:
                    if mirror.is_file() and mirror.stat().st_size == primary_size:
                        continue
                    mirror.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(primary_target, mirror)
                    self.log(f"[mirror] {mirror.relative_to(self.output_dir).as_posix()}")
                except OSError as exc:
                    self.log(f"[mirror error] {mirror}: {exc}")
        except Exception as exc:  # noqa: BLE001 - mirrors must never fail a download
            self.log(f"[mirror error] {url}: {exc}")

    def download_one(self, asset: Dict[str, str]) -> None:
        url = asset["url"]
        row = self.rows_by_url.get(url, {})
        if row.get("status") == "downloaded" and row.get("relative_path"):
            existing = self.output_dir / Path(row["relative_path"])
            if existing.is_file() and existing.stat().st_size > 0:
                self.log(f"[already downloaded] {row['relative_path']}")
                if not self.dry_run:
                    self.ensure_release_mirrors(url, existing)
                return
        platform = infer_platform(url, asset.get("context_platform") or None)
        release = infer_release(url, asset.get("context_release") or None)
        category = file_category(url)
        if self.selected_platforms and platform not in self.selected_platforms:
            self.log(f"[skipped by platform filter] {url}")
            self.rows_by_url[url] = {
                "url": url, "status": "skipped", "relative_path": "", "bytes": "", "sha256": "",
                "content_type": "", "http_status": "", "referrer": asset.get("referrer", ""),
                "error": f"platform {platform} not selected", "downloaded_at_utc": "",
            }
            self.write_manifest()
            return
        if self.selected_releases and release not in self.selected_releases and not (
            any(r in self.selected_releases for r in infer_all_releases(url))
        ):
            self.log(f"[skipped by release filter] {url}")
            self.rows_by_url[url] = {
                "url": url, "status": "skipped", "relative_path": "", "bytes": "", "sha256": "",
                "content_type": "", "http_status": "", "referrer": asset.get("referrer", ""),
                "error": f"release {release} not selected", "downloaded_at_utc": "",
            }
            self.write_manifest()
            return
        if self.selected_categories and category not in self.selected_categories:
            self.log(f"[skipped by category filter] {url}")
            self.rows_by_url[url] = {
                "url": url, "status": "skipped", "relative_path": "", "bytes": "", "sha256": "",
                "content_type": "", "http_status": "", "referrer": asset.get("referrer", ""),
                "error": f"category {category} not selected", "downloaded_at_utc": "",
            }
            self.write_manifest()
            return
        target = self.choose_target(asset)
        relative = target.relative_to(self.output_dir).as_posix()
        if self.dry_run:
            self.log(f"[dry-run] {url} -> {relative}")
            self.rows_by_url[url] = {
                "url": url, "status": "planned", "relative_path": relative,
                "bytes": "", "sha256": "", "content_type": "", "http_status": "",
                "referrer": asset.get("referrer", ""), "error": "", "downloaded_at_utc": "",
            }
            return
        temp = target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        content_type = ""
        http_status = ""
        try:
            self.log(f"[download {len(self.rows_by_url)+1}] {url}")
            with self.request(url, timeout=90) as response:
                final_url = normalize_url(response.geturl()) or response.geturl()
                if not official_host(final_url):
                    raise RuntimeError(f"Redirected outside autosar.org: {response.geturl()}")
                http_status = str(getattr(response, "status", 200))
                content_type = response.headers.get("Content-Type", "")
                # Avoid saving an HTML error page under a PDF/XSD/ZIP name.
                if "text/html" in content_type.lower() and PurePosixPath(urllib.parse.urlparse(url).path).suffix.lower() in DOCUMENT_EXTS - {".html", ".htm"}:
                    sniff = response.read(1024)
                    if b"<html" in sniff.lower() or b"<!doctype html" in sniff.lower():
                        raise RuntimeError("Server returned HTML instead of a downloadable artifact")
                    first_chunk = sniff
                else:
                    first_chunk = b""
                with temp.open("wb") as fh:
                    if first_chunk:
                        fh.write(first_chunk)
                        digest.update(first_chunk)
                        total += len(first_chunk)
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > self.max_file_bytes:
                            raise RuntimeError(f"File exceeded configured limit of {self.max_file_bytes // (1024*1024)} MiB")
                        fh.write(chunk)
                        digest.update(chunk)
            if total == 0:
                raise RuntimeError("Downloaded file was empty")
            if target.exists():
                # Normally choose_target has created a hash-suffixed name for collisions.
                suffix = hashlib.sha256((url + str(time.time())).encode()).hexdigest()[:8]
                target = target.with_name(f"{target.stem}__{suffix}{target.suffix}")
                relative = target.relative_to(self.output_dir).as_posix()
            temp.replace(target)
            self.rows_by_url[url] = {
                "url": url, "status": "downloaded", "relative_path": relative,
                "bytes": str(total), "sha256": digest.hexdigest(), "content_type": content_type,
                "http_status": http_status, "referrer": asset.get("referrer", ""),
                "error": "", "downloaded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self.write_manifest()
            self.log(f"[saved] {relative} ({total:,} bytes)")
            self.ensure_release_mirrors(url, target)
        except Exception as exc:
            try:
                if temp.exists(): temp.unlink()
            except OSError:
                pass
            self.rows_by_url[url] = {
                "url": url, "status": "error", "relative_path": relative,
                "bytes": str(total), "sha256": "", "content_type": content_type,
                "http_status": http_status, "referrer": asset.get("referrer", ""),
                "error": str(exc), "downloaded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self.write_manifest()
            self.log(f"[download error] {url}: {exc}")

    def create_scaffold(self) -> None:
        """Create the known release folders even when some of those releases have no files online."""
        for platform, releases in RELEASE_CATALOG.items():
            for release in releases:
                release_folder = release.replace(".", "_")
                for category in CATEGORIES:
                    (self.output_dir / platform / release_folder / category).mkdir(parents=True, exist_ok=True)
        for platform in ("Shared", "Unclassified", "Application_Interfaces"):
            for release in ("Unversioned", "R25-11"):
                for category in CATEGORIES:
                    (self.output_dir / platform / release / category).mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.create_scaffold()
        self.load_existing_manifest()
        self.configure_robots()
        self.crawl()
        # Save a discovery manifest row for dry-run visibility, and before a potentially long run.
        self.write_manifest()
        assets = sorted(self.assets.values(), key=lambda item: (infer_platform(item["url"], item.get("context_platform") or None), infer_release(item["url"], item.get("context_release") or None), item["url"]))
        if self.dry_run:
            self.log("[dry-run] No files will be downloaded. Use without --dry-run to download.")
        for index, asset in enumerate(assets, start=1):
            self.log(f"[artifact {index}/{len(assets)}]")
            self.download_one(asset)
        self.write_manifest()
        downloaded = sum(1 for row in self.rows_by_url.values() if row.get("status") == "downloaded")
        errors = sum(1 for row in self.rows_by_url.values() if row.get("status") == "error")
        planned = sum(1 for row in self.rows_by_url.values() if row.get("status") == "planned")
        summary = (
            "AUTOSAR download run summary\n"
            f"Pages visited: {len(self.visited)}\n"
            f"Page errors this run: {self.page_errors}\n"
            f"TLS backend: {self.tls_backend_used}\n"
            f"TLS error: {self.tls_error or 'none'}\n"
            f"Public artifact URLs discovered this run: {len(self.assets)}\n"
            f"Downloaded artifacts recorded in manifest: {downloaded}\n"
            f"Errors recorded in manifest: {errors}\n"
            f"Dry-run planned rows: {planned}\n"
            f"Output directory: {self.output_dir}\n"
            f"Manifest: {self.manifest_path}\n"
        )
        (self.output_dir / "DOWNLOAD_SUMMARY.txt").write_text(summary, encoding="utf-8")
        self.log("\n" + summary)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Download linked public AUTOSAR standards artifacts (Classic, Adaptive, Foundation).")
    parser.add_argument("--output-dir", default="AUTOSAR_Standards_Library", help="Folder where the library and manifest will be created (default: ./AUTOSAR_Standards_Library)")
    parser.add_argument("--delay", type=float, default=0.6, help="Minimum seconds between HTTP requests (default: 0.6; be polite to the official website)")
    parser.add_argument("--max-pages", type=int, default=10000, help="Maximum standards/search HTML pages to inspect (default: 10000)")
    parser.add_argument("--max-file-mb", type=int, default=2048, help="Maximum size for one file in MiB (default: 2048)")
    parser.add_argument("--dry-run", action="store_true", help="Discover files and show target paths without downloading binaries")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt rules. Use only if you have confirmed this is permitted by AUTOSAR.")
    parser.add_argument("--tls-backend", choices=("auto", "truststore", "certifi", "openssl"), default="auto",
                        help="TLS trust source: auto prefers OS trust store (truststore), then certifi, then Python/OpenSSL defaults (default: auto)")
    parser.add_argument("--ca-bundle", type=Path, default=None,
                        help="Path to an approved PEM CA bundle, e.g. an organization root CA; TLS verification remains enabled")
    parser.add_argument("--platforms", default=None,
                        help="Comma-separated platforms to download (default: all): Classic_Platform, Adaptive_Platform, Foundation, Application_Interfaces, Shared, Unclassified. Short forms CP/AP/FO/AI are also accepted.")
    parser.add_argument("--releases", default=None,
                        help="Comma-separated AUTOSAR releases to download (default: all), e.g. R25-11,R24-11,R4_4_0")
    parser.add_argument("--categories", default=None,
                        help="Comma-separated file categories to download (default: all): PDF, Archives, Spreadsheets, XML_XSD_ARXML, Office_Documents, Text_and_Data, Other")
    args = parser.parse_args(argv)
    if args.delay < 0 or args.max_pages < 1 or args.max_file_mb < 1:
        parser.error("--delay must be >= 0, --max-pages and --max-file-mb must be >= 1")

    platform_aliases = {
        "CP": "Classic_Platform", "CLASSIC": "Classic_Platform", "CLASSIC_PLATFORM": "Classic_Platform",
        "AP": "Adaptive_Platform", "ADAPTIVE": "Adaptive_Platform", "ADAPTIVE_PLATFORM": "Adaptive_Platform",
        "FO": "Foundation", "FOUNDATION": "Foundation",
        "AI": "Application_Interfaces", "APPLICATION_INTERFACES": "Application_Interfaces",
        "SHARED": "Shared", "UNCLASSIFIED": "Unclassified",
    }
    selected_platforms = None
    if args.platforms:
        selected_platforms = set()
        for token in args.platforms.split(","):
            token = token.strip()
            if not token:
                continue
            key = token.upper().replace("-", "_").replace(" ", "_")
            selected_platforms.add(platform_aliases.get(key, token))

    selected_releases = None
    if args.releases:
        selected_releases = {token.strip().upper().replace(".", "_") for token in args.releases.split(",") if token.strip()}

    selected_categories = None
    if args.categories:
        selected_categories = {token.strip() for token in args.categories.split(",") if token.strip()}

    try:
        downloader = AutosarDownloader(
            Path(args.output_dir), args.delay, args.max_pages, args.max_file_mb,
            args.dry_run, args.ignore_robots, args.tls_backend, args.ca_bundle,
            selected_platforms, selected_releases, selected_categories,
        )
        print(f"[TLS] Using {downloader.tls_backend_used}; certificate verification is enabled.", flush=True)
        downloader.run()
        return 0
    except KeyboardInterrupt:
        if "downloader" in locals():
            downloader.write_manifest()
        print("\nInterrupted by user. Progress was saved to the manifest; rerun to resume.", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(f"[configuration error] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
