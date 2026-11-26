import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from xml_sitemap_validator import (
    DEFAULT_MAX_HTTP_CHECKS,
    DEFAULT_MAX_URLS,
    canonical_from_html,
    normalize_url,
    parse_sitemap,
    validate_locations,
)


class SitemapValidatorTests(unittest.TestCase):
    def test_normalize_url_accepts_http_and_https(self):
        self.assertEqual(normalize_url("https://example.com/"), "https://example.com/")
        self.assertEqual(normalize_url("http://example.com/path"), "http://example.com/path")

    def test_normalize_url_rejects_non_http(self):
        for value in ("ftp://example.com/file.xml", "/relative/path", "//example.com/path",
                      "https:///missing-host", "https://example.com:99999/"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_url(value)

    def test_validate_locations_rejects_relative_and_protocol_relative_values(self):
        result = validate_locations([
            "https://example.com/page",
            "/relative/page",
            "//other.example/page",
            "page.html",
        ])
        self.assertEqual(result["valid_url_count"], 1)
        self.assertEqual(
            {item["url"] for item in result["invalid_urls"]},
            {"/relative/page", "//other.example/page", "page.html"},
        )

    def test_parse_urlset(self):
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url><url><loc>https://example.com/about</loc></url></urlset>'
        result = parse_sitemap(xml, "https://example.com/sitemap.xml")
        self.assertEqual(result["type"], "urlset")
        self.assertEqual(result["count"], 2)

    def test_parse_sitemap_index(self):
        xml = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>'
        result = parse_sitemap(xml, "https://example.com/sitemap_index.xml")
        self.assertEqual(result["type"], "sitemapindex")

    def test_location_limit_is_enforced(self):
        xml = '<urlset><url><loc>https://example.com/1</loc></url><url><loc>https://example.com/2</loc></url></urlset>'
        with self.assertRaisesRegex(ValueError, "safety limit"):
            parse_sitemap(xml, "local.xml", max_urls=1)

    def test_invalid_xml(self):
        with self.assertRaises(ValueError):
            parse_sitemap("<urlset>", "local.xml")

    def test_duplicate_and_invalid_locations(self):
        result = validate_locations(["https://example.com/a", "https://example.com/a", "not-a-url"])
        self.assertEqual(result["duplicate_urls"], ["https://example.com/a"])
        self.assertEqual(len(result["invalid_urls"]), 1)

    def test_canonical_resolution(self):
        html = '<html><head><link rel="canonical" href="/page"></head></html>'
        self.assertEqual(canonical_from_html(html, "https://example.com/current"), "https://example.com/page")

    @patch("xml_sitemap_validator.requests.get")
    def test_http_check_uses_streaming_and_closes_response(self, mock_get):
        response = Mock(status_code=200, url="https://example.com/", encoding="utf-8")
        response.headers = {"Content-Type": "text/html"}
        response.history = []
        mock_get.return_value = response
        from xml_sitemap_validator import check_url
        result = check_url("https://example.com/")
        self.assertEqual(result["status"], 200)
        self.assertTrue(mock_get.call_args.kwargs["stream"])
        response.close.assert_called_once()

    def test_default_http_check_budget_is_bounded(self):
        self.assertEqual(DEFAULT_MAX_HTTP_CHECKS, 100)
        self.assertEqual(DEFAULT_MAX_URLS, 50_000)

    def test_local_file_source(self):
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url></urlset>'
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as handle:
            handle.write(xml)
            path = handle.name
        try:
            self.assertEqual(parse_sitemap(xml, path)["count"], 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
