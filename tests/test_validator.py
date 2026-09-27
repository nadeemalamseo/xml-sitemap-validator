import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from xml_sitemap_validator import canonical_from_html, normalize_url, parse_sitemap, validate_locations


class SitemapValidatorTests(unittest.TestCase):
    def test_normalize_url_accepts_http_and_https(self):
        self.assertEqual(normalize_url("https://example.com/"), "https://example.com/")

    def test_normalize_url_rejects_non_http(self):
        with self.assertRaises(ValueError):
            normalize_url("ftp://example.com/file.xml")

    def test_parse_urlset(self):
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url><url><loc>https://example.com/about</loc></url></urlset>'
        result = parse_sitemap(xml, "https://example.com/sitemap.xml")
        self.assertEqual(result["type"], "urlset")
        self.assertEqual(result["count"], 2)

    def test_parse_sitemap_index(self):
        xml = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>'
        result = parse_sitemap(xml, "https://example.com/sitemap_index.xml")
        self.assertEqual(result["type"], "sitemapindex")

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
    def test_http_check(self, mock_get):
        response = Mock(status_code=200, url="https://example.com/", text="<html></html>")
        response.headers = {"Content-Type": "text/html"}
        response.history = []
        mock_get.return_value = response
        from xml_sitemap_validator import check_url
        self.assertEqual(check_url("https://example.com/")["status"], 200)

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
