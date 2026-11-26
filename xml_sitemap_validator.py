#!/usr/bin/env python3
"""Validate XML sitemaps with bounded network and parsing work."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

USER_AGENT = "xml-sitemap-validator/1.1 (+https://github.com/nadeemalamseo/xml-sitemap-validator)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_URLS = 50_000
DEFAULT_MAX_HTTP_CHECKS = 100
MAX_CANONICAL_BYTES = 2 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_url(url: str) -> str:
    value = url.strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError(f"Invalid HTTP(S) URL: {url}")
    parsed = urlparse(value)
    try:
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        valid_port = False
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or not valid_port
    ):
        raise ValueError(f"Invalid absolute HTTP(S) URL: {url}")
    return value


def fetch_text(source: str, timeout: float = DEFAULT_TIMEOUT,
               max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, str]:
    parsed = urlparse(source)
    if parsed.scheme.lower() in {"http", "https"}:
        response = requests.get(
            source,
            headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,text/plain,*/*"},
            timeout=timeout,
            stream=True,
        )
        try:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError(f"Sitemap exceeds the {max_bytes}-byte safety limit.")
                except ValueError as exc:
                    if "safety limit" in str(exc):
                        raise
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Sitemap exceeds the {max_bytes}-byte safety limit.")
                chunks.append(chunk)
            text = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
            return text, response.url
        finally:
            response.close()

    path = Path(source)
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"Sitemap exceeds the {max_bytes}-byte safety limit.")
    return path.read_text(encoding="utf-8-sig"), str(path)


def parse_sitemap(xml_text: str, source: str,
                  max_urls: int = DEFAULT_MAX_URLS) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    kind = local_name(root.tag)
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError(f"Unsupported root element: {kind}. Expected urlset or sitemapindex.")

    entries = []
    for element in root.iter():
        if local_name(element.tag) == "loc" and element.text:
            entries.append(element.text.strip())
            if len(entries) > max_urls:
                raise ValueError(f"Sitemap contains more than the {max_urls:,}-location safety limit.")

    return {"source": source, "type": kind, "count": len(entries), "locations": entries}


def validate_locations(locations: list[str], source_url: str | None = None) -> dict[str, Any]:
    invalid = []
    duplicates = sorted([url for url, count in Counter(locations).items() if count > 1])

    for value in locations:
        try:
            normalize_url(value)
        except ValueError as exc:
            invalid.append({"url": value, "reason": str(exc)})

    return {
        "invalid_urls": invalid,
        "duplicate_urls": duplicates,
        "valid_url_count": len(locations) - len(invalid),
    }


def canonical_from_html(html: str, page_url: str) -> str | None:
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    if not link or not link.get("href"):
        return None
    return urljoin(page_url, link["href"].strip())


def check_url(url: str, timeout: float = DEFAULT_TIMEOUT,
              check_canonical: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url}
    response = None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
        result.update({
            "status": response.status_code,
            "final_url": response.url,
            "redirects": len(response.history),
            "content_type": response.headers.get("Content-Type", ""),
        })
        if check_canonical and "text/html" in result["content_type"].lower():
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_CANONICAL_BYTES:
                    result["canonical_check_error"] = (
                        f"HTML exceeded the {MAX_CANONICAL_BYTES}-byte canonical-inspection limit."
                    )
                    break
                chunks.append(chunk)
            else:
                html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                canonical = canonical_from_html(html, response.url)
                result["canonical"] = canonical
                result["canonical_matches_final"] = (
                    normalize_url(canonical).rstrip("/") == normalize_url(response.url).rstrip("/")
                    if canonical else None
                )
    except (requests.RequestException, ValueError) as exc:
        result["error"] = str(exc)
    finally:
        if response is not None:
            response.close()
    return result


def build_report(source: str, timeout: float, check_http: bool,
                 check_canonical: bool, max_bytes: int = DEFAULT_MAX_BYTES,
                 max_urls: int = DEFAULT_MAX_URLS,
                 max_http_checks: int = DEFAULT_MAX_HTTP_CHECKS) -> dict[str, Any]:
    xml_text, effective_source = fetch_text(source, timeout, max_bytes)
    parsed = parse_sitemap(xml_text, effective_source, max_urls)
    validation = validate_locations(parsed["locations"])

    report = {
        "source": source,
        "effective_source": effective_source,
        "sitemap_type": parsed["type"],
        "location_count": parsed["count"],
        "invalid_urls": validation["invalid_urls"],
        "duplicate_urls": validation["duplicate_urls"],
        "valid_url_count": validation["valid_url_count"],
        "http_checks": [],
        "warnings": [],
    }

    if parsed["type"] == "urlset" and check_http:
        invalid_set = {item["url"] for item in validation["invalid_urls"]}
        valid_urls = [url for url in parsed["locations"] if url not in invalid_set]
        selected_urls = valid_urls[:max_http_checks]
        report["http_checks"] = [
            check_url(url, timeout, check_canonical) for url in selected_urls
        ]
        if len(valid_urls) > len(selected_urls):
            report["warnings"].append(
                f"HTTP checks were capped at {max_http_checks}; "
                f"{len(valid_urls) - len(selected_urls)} valid URLs were not requested."
            )

    if parsed["type"] == "sitemapindex":
        report["warnings"].append(
            "Sitemap indexes are validated for their child <loc> entries; child sitemaps are not recursively downloaded."
        )
    if validation["duplicate_urls"]:
        report["warnings"].append("Duplicate <loc> values were found.")
    if validation["invalid_urls"]:
        report["warnings"].append("One or more <loc> values are not absolute HTTP(S) URLs.")

    return report


def exit_code(report: dict[str, Any]) -> int:
    if report["invalid_urls"] or report["duplicate_urls"]:
        return 2
    if any(item.get("error") or item.get("status", 0) >= 400
           for item in report["http_checks"]):
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an XML sitemap or sitemap index.")
    parser.add_argument("source", help="Sitemap URL or local XML file")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                        help="Maximum sitemap size in bytes (default: 50 MiB)")
    parser.add_argument("--max-urls", type=int, default=DEFAULT_MAX_URLS,
                        help="Maximum <loc> entries to parse (default: 50000)")
    parser.add_argument("--max-http-checks", type=int, default=DEFAULT_MAX_HTTP_CHECKS,
                        help="Maximum URL requests per run (default: 100)")
    parser.add_argument("--no-http", action="store_true", help="Skip HTTP checks for URLs in a urlset")
    parser.add_argument("--check-canonical", action="store_true", help="Check HTML canonical against the final URL")
    args = parser.parse_args()

    if args.timeout <= 0 or args.max_bytes <= 0 or args.max_urls <= 0 or args.max_http_checks < 0:
        parser.error("--timeout, --max-bytes and --max-urls must be positive; --max-http-checks cannot be negative")

    try:
        report = build_report(
            args.source, args.timeout, not args.no_http, args.check_canonical,
            args.max_bytes, args.max_urls, args.max_http_checks,
        )
    except (OSError, requests.RequestException, ValueError) as exc:
        if args.json:
            print(json.dumps({"source": args.source, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Sitemap: {report['effective_source']}")
        print(f"Type: {report['sitemap_type']}")
        print(f"Locations: {report['location_count']}")
        print(f"Valid URLs: {report['valid_url_count']}")
        print(f"Duplicate URLs: {len(report['duplicate_urls'])}")
        print(f"Invalid URLs: {len(report['invalid_urls'])}")
        if report["http_checks"]:
            failures = [x for x in report["http_checks"] if x.get("error") or x.get("status", 0) >= 400]
            print(f"HTTP failures: {len(failures)}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
