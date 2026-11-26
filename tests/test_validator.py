import unittest
from unittest.mock import Mock, patch

import requests

from xml_sitemap_validator import (
    DEFAULT_MAX_HTTP_CHECKS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MAX_URLS,
    MAX_CANONICAL_BYTES,
    build_report,
    canonical_from_html,
    check_url,
    fetch_text,
    normalize_url,
    parse_sitemap,
    validate_locations,
)


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def response_mock(
    *,
    status=200,
    url="https://example.com/sitemap.xml",
    body=b"",
    headers=None,
    history=None,
    chunks=None,
):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.url = url
    response.encoding = "utf-8"
    response.headers = requests.structures.CaseInsensitiveDict(headers or {})
    response.history = history or []
    response.reason = "OK"
    response.iter_content.return_value = chunks if chunks is not None else [body]
    response.raise_for_status.return_value = None
    return response


class URLValidationTests(unittest.TestCase):
    def test_normalizes_scheme_host_and_default_port(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.COM:443/path#part"),
            "https://example.com/path#part",
        )

    def test_preserves_non_default_port_and_query(self):
        self.assertEqual(
            normalize_url("https://Example.com:8443/path?a=1"),
            "https://example.com:8443/path?a=1",
        )

    def test_supports_ipv6_authorities(self):
        self.assertEqual(
            normalize_url("https://[2001:db8::1]:443/path"),
            "https://[2001:db8::1]/path",
        )

    def test_rejects_non_http_relative_and_malformed_urls(self):
        values = (
            "ftp://example.com/file.xml",
            "/relative/path",
            "//example.com/path",
            "https:///missing-host",
            "https://example.com:99999/",
            "https://example.com:bad/",
            "https://example.com/a b",
            "https://user:secret@example.com/",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_url(value)

    def test_duplicates_are_reported_and_invalid_urls_rejected(self):
        result = validate_locations(
            ["https://example.com/a", "https://example.com/a", "/relative", "not-a-url"]
        )
        self.assertEqual(result["duplicate_urls"], ["https://example.com/a"])
        self.assertEqual(result["valid_url_count"], 2)
        self.assertEqual(len(result["invalid_urls"]), 2)


class SitemapParsingTests(unittest.TestCase):
    def test_parses_urlset_with_namespace(self):
        xml = (
            f'<urlset xmlns="{SITEMAP_NS}">'
            "<url><loc>https://example.com/</loc></url>"
            "<url><loc>https://example.com/about</loc></url>"
            "</urlset>"
        )
        result = parse_sitemap(xml, "local.xml")
        self.assertEqual(result["type"], "urlset")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["namespace"], SITEMAP_NS)
        self.assertEqual(result["warnings"], [])

    def test_parses_sitemap_index(self):
        xml = (
            f'<sitemapindex xmlns="{SITEMAP_NS}">'
            "<sitemap><loc>https://example.com/child.xml</loc></sitemap>"
            "</sitemapindex>"
        )
        result = parse_sitemap(xml, "index.xml")
        self.assertEqual(result["type"], "sitemapindex")
        self.assertEqual(result["locations"], ["https://example.com/child.xml"])

    def test_does_not_mistake_nested_image_loc_for_page_url(self):
        xml = (
            f'<urlset xmlns="{SITEMAP_NS}" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            "<url><loc>https://example.com/page</loc>"
            "<image:image><image:loc>https://example.com/photo.jpg</image:loc></image:image>"
            "</url></urlset>"
        )
        result = parse_sitemap(xml, "images.xml")
        self.assertEqual(result["locations"], ["https://example.com/page"])

    def test_rejects_wrong_root(self):
        with self.assertRaisesRegex(ValueError, "Unsupported root"):
            parse_sitemap("<rss><channel /></rss>", "local.xml")

    def test_rejects_malformed_xml(self):
        with self.assertRaisesRegex(ValueError, "Invalid or unsafe XML"):
            parse_sitemap("<urlset>", "local.xml")

    def test_rejects_doctype_and_entity_declarations(self):
        xml = (
            '<!DOCTYPE urlset [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<urlset><url><loc>&xxe;</loc></url></urlset>'
        )
        with self.assertRaisesRegex(ValueError, "Invalid or unsafe XML"):
            parse_sitemap(xml, "untrusted.xml")

    def test_rejects_entries_without_exactly_one_direct_loc(self):
        xml = "<urlset><url><lastmod>2026-01-01</lastmod></url></urlset>"
        with self.assertRaisesRegex(ValueError, "exactly one direct"):
            parse_sitemap(xml, "local.xml")

    def test_rejects_unexpected_direct_children(self):
        with self.assertRaisesRegex(ValueError, "unexpected direct child"):
            parse_sitemap("<urlset><sitemap><loc>https://example.com/a.xml</loc></sitemap></urlset>", "local.xml")

    def test_location_limit_is_enforced(self):
        xml = (
            "<urlset><url><loc>https://example.com/1</loc></url>"
            "<url><loc>https://example.com/2</loc></url></urlset>"
        )
        with self.assertRaisesRegex(ValueError, "safety limit"):
            parse_sitemap(xml, "local.xml", max_urls=1)

    def test_empty_sitemap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No valid"):
            parse_sitemap("<urlset />", "empty.xml")

    def test_nonstandard_namespace_is_reported(self):
        result = parse_sitemap(
            "<urlset><url><loc>https://example.com/</loc></url></urlset>",
            "local.xml",
        )
        self.assertTrue(any("standard Sitemap XML namespace" in x for x in result["warnings"]))

    def test_default_limits_are_bounded(self):
        self.assertEqual(DEFAULT_MAX_URLS, 50_000)
        self.assertEqual(DEFAULT_MAX_HTTP_CHECKS, 100)
        self.assertEqual(DEFAULT_MAX_REDIRECTS, 10)
        self.assertEqual(MAX_CANONICAL_BYTES, 2 * 1024 * 1024)


class NetworkSafetyTests(unittest.TestCase):
    @patch("xml_sitemap_validator.requests.Session")
    def test_remote_sitemap_uses_streaming_and_redirect_limit(self, session_factory):
        session = session_factory.return_value
        response = response_mock(
            body=b"<urlset><url><loc>https://example.com/</loc></url></urlset>",
            headers={"Content-Length": "64"},
        )
        session.get.return_value = response

        text, final_url = fetch_text("https://example.com/sitemap.xml")

        self.assertIn("<urlset>", text)
        self.assertEqual(final_url, response.url)
        self.assertEqual(session.max_redirects, DEFAULT_MAX_REDIRECTS)
        self.assertTrue(session.get.call_args.kwargs["stream"])
        response.close.assert_called_once()
        session.close.assert_called_once()

    @patch("xml_sitemap_validator.requests.Session")
    def test_remote_sitemap_body_limit_is_enforced(self, session_factory):
        session = session_factory.return_value
        response = response_mock(chunks=[b"a" * 8, b"b" * 8])
        session.get.return_value = response

        with self.assertRaisesRegex(ValueError, "16-byte safety limit"):
            fetch_text("https://example.com/sitemap.xml", max_bytes=10)
        response.close.assert_called_once()
        session.close.assert_called_once()

    @patch("xml_sitemap_validator.requests.Session")
    def test_non_success_sitemap_response_raises(self, session_factory):
        session = session_factory.return_value
        response = response_mock()
        response.raise_for_status.side_effect = requests.HTTPError("404")
        session.get.return_value = response

        with self.assertRaises(requests.HTTPError):
            fetch_text("https://example.com/sitemap.xml")
        response.close.assert_called_once()
        session.close.assert_called_once()

    @patch("xml_sitemap_validator.requests.Session")
    def test_http_check_reports_status_and_closes_response(self, session_factory):
        session = session_factory.return_value
        response = response_mock(
            url="https://example.com/page",
            headers={"Content-Type": "text/html"},
        )
        session.get.return_value = response

        result = check_url("https://example.com/page")

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["redirects"], 0)
        self.assertEqual(session.max_redirects, DEFAULT_MAX_REDIRECTS)
        self.assertTrue(session.get.call_args.kwargs["stream"])
        response.close.assert_called_once()
        session.close.assert_called_once()

    @patch("xml_sitemap_validator.requests.Session")
    def test_http_check_rejects_credentials_before_request(self, session_factory):
        result = check_url("https://user:pass@example.com/")
        self.assertIn("error", result)
        session_factory.assert_not_called()

    @patch("xml_sitemap_validator.requests.Session")
    def test_canonical_check_is_bounded_and_compares_exact_normalized_urls(self, session_factory):
        session = session_factory.return_value
        html = (
            '<html><head><link rel="canonical" href="https://EXAMPLE.com/page">'
            "</head></html>"
        ).encode()
        response = response_mock(
            url="https://example.com/page",
            body=html,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        session.get.return_value = response

        result = check_url("https://example.com/page", check_canonical=True)

        self.assertEqual(result["canonical"], "https://EXAMPLE.com/page")
        self.assertTrue(result["canonical_matches_final"])
        response.close.assert_called_once()

    @patch("xml_sitemap_validator.requests.Session")
    def test_canonical_check_does_not_equate_different_paths(self, session_factory):
        session = session_factory.return_value
        html = (
            '<html><head><link rel="canonical" href="https://example.com/a//">'
            "</head></html>"
        ).encode()
        response = response_mock(
            url="https://example.com/a/",
            body=html,
            headers={"Content-Type": "text/html"},
        )
        session.get.return_value = response

        result = check_url("https://example.com/a/", check_canonical=True)
        self.assertFalse(result["canonical_matches_final"])

    def test_canonical_link_rel_list_and_relative_resolution(self):
        html = '<html><head><link rel="alternate canonical" href="/preferred"></head></html>'
        self.assertEqual(
            canonical_from_html(html, "https://example.com/current"),
            "https://example.com/preferred",
        )

    @patch("xml_sitemap_validator.fetch_text")
    @patch("xml_sitemap_validator.check_url")
    def test_sitemap_index_does_not_recursively_fetch_child_sitemaps(self, check, fetch):
        fetch.return_value = (
            f'<sitemapindex xmlns="{SITEMAP_NS}">'
            "<sitemap><loc>https://example.com/child.xml</loc></sitemap>"
            "</sitemapindex>",
            "https://example.com/index.xml",
        )
        report = build_report(
            "https://example.com/index.xml", 10, True, False
        )
        check.assert_not_called()
        self.assertEqual(report["sitemap_type"], "sitemapindex")
        self.assertTrue(any("not recursively downloaded" in x for x in report["warnings"]))

    @patch("xml_sitemap_validator.fetch_text")
    @patch("xml_sitemap_validator.check_url")
    def test_http_checks_are_capped(self, check, fetch):
        locs = "".join(
            f"<url><loc>https://example.com/{i}</loc></url>" for i in range(3)
        )
        fetch.return_value = (
            f'<urlset xmlns="{SITEMAP_NS}">{locs}</urlset>',
            "https://example.com/sitemap.xml",
        )
        check.return_value = {"status": 200}
        report = build_report(
            "https://example.com/sitemap.xml",
            10,
            True,
            False,
            max_http_checks=2,
        )
        self.assertEqual(check.call_count, 2)
        self.assertTrue(any("capped at 2" in x for x in report["warnings"]))

    def test_invalid_build_report_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            build_report("local.xml", 0, False, False)
        with self.assertRaises(ValueError):
            build_report("local.xml", 10, False, False, max_http_checks=-1)


if __name__ == "__main__":
    unittest.main()
