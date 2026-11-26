#!/usr/bin/env python3
"""Validate XML sitemaps with bounded network and parsing work."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

USER_AGENT = "xml-sitemap-validator/1.2 (+https://github.com/nadeemalamseo/xml-sitemap-validator)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_URLS = 50_000
DEFAULT_MAX_HTTP_CHECKS = 100
DEFAULT_MAX_REDIRECTS = 10
MAX_CANONICAL_BYTES = 2 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_url(url: str) -> str:
    """Validate an absolute HTTP(S) URL and normalize only its authority."""
    value = url.strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError(f"Invalid HTTP(S) URL: {url}")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid HTTP(S) URL: {url}") from exc

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError(f"Invalid absolute HTTP(S) URL: {url}")

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = hostname
    elif port is not None:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment))


def _read_stream_limited(response: requests.Response, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise ValueError("Maximum response size must be positive.")
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError(f"Response exceeds the {max_bytes}-byte safety limit.")
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
            raise ValueError(f"Response exceeds the {max_bytes}-byte safety limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _read_local_file_limited(path: Path, max_bytes: int) -> str:
    if max_bytes <= 0:
        raise ValueError("Maximum response size must be positive.")
    chunks: list[bytes] = []
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"Sitemap exceeds the {max_bytes}-byte safety limit.")
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8-sig", errors="replace")


def _new_session() -> requests.Session:
    session = requests.Session()
    session.max_redirects = DEFAULT_MAX_REDIRECTS
    return session


def fetch_text(
    source: str,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[str, str]:
    if timeout <= 0:
        raise ValueError("Timeout must be greater than zero.")
    if max_bytes <= 0:
        raise ValueError("Maximum sitemap size must be positive.")

    parsed = urlsplit(source)
    if parsed.scheme.lower() in {"http", "https"}:
        source = normalize_url(source)
        session = _new_session()
        response = None
        try:
            response = session.get(
                source,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/xml,text/xml,text/plain,*/*",
                },
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )
            response.raise_for_status()
            body = _read_stream_limited(response, max_bytes)
            text = body.decode(response.encoding or "utf-8", errors="replace")
            return text, response.url
        finally:
            if response is not None:
                response.close()
            session.close()

    if parsed.scheme:
        raise ValueError("Source must be an HTTP(S) URL or a local XML file path.")
    path = Path(source)
    return _read_local_file_limited(path, max_bytes), str(path)


def parse_sitemap(
    xml_text: str,
    source: str,
    max_urls: int = DEFAULT_MAX_URLS,
) -> dict[str, Any]:
    if max_urls <= 0:
        raise ValueError("Maximum location count must be positive.")
    try:
        root = SafeET.fromstring(xml_text)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise ValueError(f"Invalid or unsafe XML: {exc}") from exc

    kind = local_name(root.tag)
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError(
            f"Unsupported root element: {kind}. Expected urlset or sitemapindex."
        )

    expected_child = "url" if kind == "urlset" else "sitemap"
    entries: list[str] = []
    malformed_entries = 0

    for element in list(root):
        if local_name(element.tag) != expected_child:
            malformed_entries += 1
            continue
        loc_values = [
            (child.text or "").strip()
            for child in list(element)
            if local_name(child.tag) == "loc" and (child.text or "").strip()
        ]
        if len(loc_values) != 1:
            malformed_entries += 1
            continue
        entries.append(loc_values[0])
        if len(entries) > max_urls:
            raise ValueError(
                f"Sitemap contains more than the {max_urls:,}-location safety limit."
            )

    if malformed_entries:
        raise ValueError(
            f"Found {malformed_entries} malformed or unexpected direct child "
            f"elements; expected <{expected_child}> entries with exactly one direct <loc>."
        )
    if not entries:
        raise ValueError(f"No valid <{expected_child}> location entries were found.")

    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else None
    return {
        "source": source,
        "type": kind,
        "count": len(entries),
        "locations": entries,
        "namespace": namespace,
        "warnings": (
            [] if namespace == "http://www.sitemaps.org/schemas/sitemap/0.9"
            else ["The root element does not use the standard Sitemap XML namespace."]
        ),
    }


def validate_locations(locations: list[str]) -> dict[str, Any]:
    invalid = []
    duplicates = sorted(
        [url for url, count in Counter(locations).items() if count > 1]
    )
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

    def has_canonical(value: Any) -> bool:
        rel_values = value if isinstance(value, list) else str(value or "").split()
        return any(str(item).lower() == "canonical" for item in rel_values)

    links = soup.find_all("link", attrs={"rel": has_canonical})
    for link in links:
        href = (link.get("href") or "").strip()
        if href:
            return urljoin(page_url, href)
    return None


def check_url(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    check_canonical: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url}
    response = None
    session = None
    try:
        url = normalize_url(url)
        if timeout <= 0:
            raise ValueError("Timeout must be greater than zero.")
        session = _new_session()
        response = session.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
        result.update(
            {
                "status": response.status_code,
                "final_url": response.url,
                "redirects": len(response.history),
                "content_type": response.headers.get("Content-Type", ""),
            }
        )

        content_type = result["content_type"].lower()
        if check_canonical and (
            "text/html" in content_type or "application/xhtml+xml" in content_type
        ):
            body = _read_stream_limited(response, MAX_CANONICAL_BYTES)
            html = body.decode(response.encoding or "utf-8", errors="replace")
            canonical = canonical_from_html(html, response.url)
            result["canonical"] = canonical
            if canonical:
                try:
                    result["canonical_matches_final"] = (
                        normalize_url(canonical) == normalize_url(response.url)
                    )
                except ValueError:
                    result["canonical_matches_final"] = False
                    result["canonical_error"] = "Canonical href is not a valid absolute HTTP(S) URL."
            else:
                result["canonical_matches_final"] = None
    except (requests.RequestException, OSError, ValueError) as exc:
        result["error"] = str(exc)
    finally:
        if response is not None:
            response.close()
        if session is not None:
            session.close()
    return result


def build_report(
    source: str,
    timeout: float,
    check_http: bool,
    check_canonical: bool,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_urls: int = DEFAULT_MAX_URLS,
    max_http_checks: int = DEFAULT_MAX_HTTP_CHECKS,
) -> dict[str, Any]:
    if timeout <= 0 or max_bytes <= 0 or max_urls <= 0 or max_http_checks < 0:
        raise ValueError("Timeout, byte limit and URL limit must be positive; HTTP check limit cannot be negative.")

    xml_text, effective_source = fetch_text(source, timeout, max_bytes)
    parsed = parse_sitemap(xml_text, effective_source, max_urls)
    validation = validate_locations(parsed["locations"])

    report: dict[str, Any] = {
        "source": source,
        "effective_source": effective_source,
        "sitemap_type": parsed["type"],
        "location_count": parsed["count"],
        "invalid_urls": validation["invalid_urls"],
        "duplicate_urls": validation["duplicate_urls"],
        "valid_url_count": validation["valid_url_count"],
        "http_checks": [],
        "warnings": list(parsed["warnings"]),
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
            "Sitemap indexes are validated for their child <loc> entries; "
            "child sitemaps are not recursively downloaded."
        )
    if validation["duplicate_urls"]:
        report["warnings"].append("Duplicate <loc> values were found.")
    if validation["invalid_urls"]:
        report["warnings"].append(
            "One or more <loc> values are not absolute HTTP(S) URLs."
        )
    if any(item.get("canonical_error") for item in report["http_checks"]):
        report["warnings"].append(
            "One or more canonical href values were invalid."
        )
    return report


def exit_code(report: dict[str, Any]) -> int:
    if report["invalid_urls"] or report["duplicate_urls"]:
        return 2
    if any(
        item.get("error") or item.get("status", 0) >= 400
        for item in report["http_checks"]
    ):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an XML sitemap or sitemap index."
    )
    parser.add_argument("source", help="Sitemap URL or local XML file")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Maximum sitemap size in bytes (default: 50 MiB)")
    parser.add_argument("--max-urls", type=int, default=DEFAULT_MAX_URLS, help="Maximum <loc> entries to parse (default: 50000)")
    parser.add_argument("--max-http-checks", type=int, default=DEFAULT_MAX_HTTP_CHECKS, help="Maximum URL requests per run (default: 100)")
    parser.add_argument("--no-http", action="store_true", help="Skip HTTP checks for URLs in a urlset")
    parser.add_argument("--check-canonical", action="store_true", help="Check HTML canonical against the final URL")
    args = parser.parse_args(argv)

    if (
        args.timeout <= 0
        or args.max_bytes <= 0
        or args.max_urls <= 0
        or args.max_http_checks < 0
    ):
        parser.error(
            "--timeout, --max-bytes and --max-urls must be positive; "
            "--max-http-checks cannot be negative"
        )

    try:
        report = build_report(
            args.source,
            args.timeout,
            not args.no_http,
            args.check_canonical,
            args.max_bytes,
            args.max_urls,
            args.max_http_checks,
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
            failures = [
                item for item in report["http_checks"]
                if item.get("error") or item.get("status", 0) >= 400
            ]
            print(f"HTTP failures: {len(failures)}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
