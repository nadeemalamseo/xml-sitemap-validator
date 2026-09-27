# Methodology

## XML validation

The parser requires well-formed XML and recognizes two root types: `urlset` and `sitemapindex`. It extracts `loc` values and checks whether they are valid HTTP(S) URLs.

## Duplicate detection

Duplicate `loc` strings are reported. The validator does not assume that two different URL strings represent the same resource merely because a server might normalize them.

## HTTP checks

For each valid URL in a `urlset`, optional checks record HTTP status, final URL after redirects, redirect count, content type, and request errors.

These observations come from the environment making the request and can vary because of CDN, WAF, authentication, geolocation, rate limiting, or server state.

## Canonical checks

With `--check-canonical`, HTML responses are inspected for a canonical link. The comparison is between the resolved canonical URL and the final URL after redirects. A missing canonical is reported as missing evidence rather than automatically labeled a search-engine error.

## Sitemap indexes

Sitemap indexes are parsed but child sitemaps are not recursively downloaded in this release. This keeps network activity explicit and predictable.

## Limitations

This tool does not determine whether a search engine has indexed a URL, ranking positions, crawl frequency, search-engine-selected canonicals, JavaScript-rendered DOM state, or every crawler-specific behavior.

A passing validation is evidence about the tested response, not a guarantee of search visibility.
