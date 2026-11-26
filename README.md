# XML Sitemap Validator

A practical XML sitemap validator for URL structure, HTTP responses, canonical consistency, duplicate URLs, and common sitemap issues.

## What it checks

- XML parsing for `urlset` and `sitemapindex`
- Strict validation that every `<loc>` is an absolute HTTP(S) URL
- Duplicate `<loc>` values
- Optional, bounded HTTP status, redirect, final URL, and content-type checks
- Optional HTML canonical comparison with the final URL
- JSON output and meaningful exit codes

## Requirements

Python 3.10+.

```bash
python -m pip install -r requirements.txt
```

## Usage

```bash
# Validate sitemap structure and check up to 100 listed URLs over HTTP
python xml_sitemap_validator.py https://example.com/sitemap.xml

# Validate structure only, without requesting each listed URL
python xml_sitemap_validator.py https://example.com/sitemap.xml --no-http

# Machine-readable output
python xml_sitemap_validator.py https://example.com/sitemap.xml --json

# Also inspect canonical links on HTML responses
python xml_sitemap_validator.py https://example.com/sitemap.xml --check-canonical

# Adjust safety budgets
python xml_sitemap_validator.py https://example.com/sitemap.xml --max-bytes 10485760 --max-urls 10000 --max-http-checks 50

# Local XML file
python xml_sitemap_validator.py ./sitemap.xml --no-http
```

## Resource limits

The default limits are 50 MiB for the sitemap document, 50,000 `<loc>` entries, and 100 HTTP checks per run. Remote downloads are streamed and capped; HTTP response bodies are not downloaded unless canonical inspection is requested, in which case inspection is capped at 2 MiB per page. Use `--no-http` when you only need to validate the XML and URL structure.

The sitemap protocol allows up to 50,000 URLs and an uncompressed sitemap file size of 50 MiB. This tool applies those limits by default. A smaller custom limit can be supplied for cautious local use.

A sitemap index is recognized and its child `<loc>` entries are validated, but child sitemaps are not recursively downloaded in this release. This keeps network scope predictable.

## Exit codes

- `0` — no validation failures detected
- `1` — sitemap could not be loaded or parsed
- `2` — invalid/duplicate URLs or HTTP failures detected

## Methodology and limitations

The tool requires absolute HTTP(S) URLs in `<loc>` values. It does not resolve relative values against the sitemap address because sitemap locations must be fully qualified URLs.

The tool reports observable technical evidence. A valid sitemap URL, a 200 response, or a matching canonical does not prove search-engine indexing, ranking, or eligibility.

It does not determine search-engine-selected canonicals, crawl frequency, ranking positions, JavaScript-rendered state, authentication-only behavior, or every crawler-specific outcome. Network results can also vary with CDN, WAF, geolocation, rate limiting, and server state.

See [docs/methodology.md](docs/methodology.md).

## Responsible use

Only test URLs you are authorized to request. Keep reasonable timeouts and request volumes. The default HTTP-check budget is capped at 100 URLs per run.

## Related resources

For documenting broader technical SEO findings, see the [technical SEO audit checklist](https://github.com/nadeemalamseo/technical-seo-audit-checklist).

This project does not guarantee rankings, indexing, traffic, or search visibility.

## Project links

- [Project landing page](https://nadeemalamseo.github.io/xml-sitemap-validator/)
- [v0.1.0 release](https://github.com/nadeemalamseo/xml-sitemap-validator/releases/tag/v0.1.0)
- [Download v0.1.0 ZIP](https://github.com/nadeemalamseo/xml-sitemap-validator/archive/refs/tags/v0.1.0.zip)

## License

This repository is licensed under the MIT License. See [LICENSE](LICENSE).
