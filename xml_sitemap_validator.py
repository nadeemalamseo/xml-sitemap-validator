#!/usr/bin/env python3
"""Validate XML sitemaps and optionally check referenced URLs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

USER_AGENT = "xml-sitemap-validator/1.0 (+https://github.com/nadeemalamseo/xml-sitemap-validator)"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid HTTP(S) URL: {url}")
    return value


def fetch_text(source: str, timeout: float = 15.0) -> tuple[str, str]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(
            source,
            headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,text/plain,*/*"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.text, response.url
    path = Path(source)
    return path.read_text(encoding="utf-8"), str(path)


def parse_sitemap(xml_text: str, source: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    kind = local_name(root.tag)
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError(f"Unsupported root element: {kind}. Expected urlset or sitemapindex.")

    entries = [
        element.text.strip()
        for element in root.iter()
        if local_name(element.tag) == "loc" and element.text
    ]
    return {"source": source, "type": kind, "count": len(entries), "locations": entries}


def validate_locations(locations: list[str], source_url: str | None = None) -> dict[str, Any]:
    invalid = []
    duplicates = sorted([url for url, count in Counter(locations).items() if count > 1])

    for value in locations:
        try:
            candidate = urljoin(source_url, value) if source_url and not urlparse(value).scheme else value
            normalize_url(candidate)
        except ValueError as exc:
            invalid.append({"url": value, "reason": str(exc)})

    return {
        "invalid_urls": invalid,
        "duplicate_urls": duplicates,
        "valid_url_count": len(locations) - len(invalid),
    }


def canonical_from_html(html: str, page_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    if not link or not link.get("href"):
        return None
    return urljoin(page_url, link["href"].strip())


def check_url(url: str, timeout: float = 15.0, check_canonical: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url}
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        result.update(
            {
                "status": response.status_code,
                "final_url": response.url,
                "redirects": len(response.history),
                "content_type": response.headers.get("Content-Type", ""),
            }
        )
        if check_canonical and "text/html" in response.headers.get("Content-Type", "").lower():
            canonical = canonical_from_html(response.text, response.url)
            result["canonical"] = canonical
            result["canonical_matches_final"] = (
                normalize_url(canonical).rstrip("/") == normalize_url(response.url).rstrip("/")
                if canonical else None
            )
    except (requests.RequestException, ValueError) as exc:
        result["error"] = str(exc)
    return result


def build_report(source: str, timeout: float, check_http: bool, check_canonical: bool) -> dict[str, Any]:
    xml_text, effective_source = fetch_text(source, timeout)
    parsed = parse_sitemap(xml_text, effective_source)
    validation = validate_locations(
        parsed["locations"],
        effective_source if effective_source.startswith("http") else None,
    )

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
        report["http_checks"] = [
            check_url(url, timeout, check_canonical)
            for url in parsed["locations"]
            if url not in invalid_set
        ]

    if parsed["type"] == "sitemapindex":
        report["warnings"].append(
            "Sitemap indexes are validated for their child <loc> entries; child sitemaps are not recursively downloaded."
        )
    if validation["duplicate_urls"]:
        report["warnings"].append("Duplicate <loc> values were found.")
    if validation["invalid_urls"]:
        report["warnings"].append("One or more <loc> values are not valid HTTP(S) URLs.")

    return report


def exit_code(report: dict[str, Any]) -> int:
    if report["invalid_urls"] or report["duplicate_urls"]:
        return 2
    if any(item.get("error") or item.get("status", 0) >= 400 for item in report["http_checks"]):
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an XML sitemap or sitemap index.")
    parser.add_argument("source", help="Sitemap URL or local XML file")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    parser.add_argument("--no-http", action="store_true", help="Skip HTTP checks for URLs in a urlset")
    parser.add_argument("--check-canonical", action="store_true", help="Check HTML canonical against the final URL")
    args = parser.parse_args()

    try:
        report = build_report(args.source, args.timeout, not args.no_http, args.check_canonical)
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
