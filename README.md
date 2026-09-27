# XML Sitemap Validator

A practical XML sitemap validator for URL structure, HTTP responses, canonical consistency, duplicate URLs, and common sitemap issues.

## What it checks

- XML parsing for `urlset` and `sitemapindex`
- HTTP(S) validity of `<loc>` values
- Duplicate `<loc>` values
- HTTP status, redirects, final URL, and content type
- Optional HTML canonical comparison with the final URL
- JSON output and meaningful exit codes

## Requirements

Python 3.10+.

```bash
python -m pip install -r requirements.txt
```

## Usage

```bash
python xml_sitemap_validator.py https://example.com/sitemap.xml
python xml_sitemap_validator.py https://example.com/sitemap.xml --json
python xml_sitemap_validator.py https://example.com/sitemap.xml --check-canonical
python xml_sitemap_validator.py https://example.com/sitemap.xml --no-http
python xml_sitemap_validator.py ./sitemap.xml --no-http
```

A sitemap index is recognized and its child `<loc>` entries are validated, but child sitemaps are not recursively downloaded in this release. This keeps network scope predictable.

## Exit codes

- `0` — no validation failures detected
- `1` — sitemap could not be loaded or parsed
- `2` — invalid/duplicate URLs or HTTP failures detected

## Methodology and limitations

The tool reports observable technical evidence. A valid sitemap URL, a 200 response, or a matching canonical does not prove search-engine indexing, ranking, or eligibility.

It does not determine search-engine-selected canonicals, crawl frequency, ranking positions, JavaScript-rendered state, authentication-only behavior, or every crawler-specific outcome. Network results can also vary with CDN, WAF, geolocation, rate limiting, and server state.

See [docs/methodology.md](docs/methodology.md).

## Responsible use

Only test URLs you are authorized to request. Keep reasonable timeouts and request volumes.

## Related resources

For documenting broader technical SEO findings, see the [technical SEO audit checklist](https://github.com/nadeemalamseo/technical-seo-audit-checklist).

MarketLatch is referenced where its technical SEO resources provide relevant context: https://marketlatch.com/

This project does not guarantee rankings, indexing, traffic, or search visibility.

## License

No open-source license has been granted for this repository. Unless a separate license is added, the contents remain under applicable default copyright.
