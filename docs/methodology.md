# Methodology

## XML document handling

The validator accepts a Sitemap Protocol `urlset` or `sitemapindex` root. XML is parsed with `defusedxml`; DTD and entity declarations are rejected to reduce XML external entity (XXE) and entity-expansion risks.

The parser examines direct sitemap entry children:

- A `urlset` must contain direct `url` entries.
- A `sitemapindex` must contain direct `sitemap` entries.
- Each entry must contain exactly one direct `loc` element with non-empty text.
- Nested extension elements (for example, image sitemap `image:loc`) are not treated as the page's sitemap location.

The standard Sitemap XML namespace is reported as expected. A missing or different root namespace is reported as a warning rather than silently rewritten.

## URL validation

Every `loc` value must be an absolute HTTP(S) URL with a hostname. Relative and protocol-relative values are rejected. URLs with embedded username/password credentials, malformed ports, whitespace, or unsupported schemes are rejected.

Duplicate detection compares the original `loc` strings. It does not assume two differently written URLs identify the same resource.

## Resource limits

Defaults:

- Remote sitemap and local file size: 50 MiB.
- Sitemap locations: 50,000.
- HTTP checks per run: 100.
- Redirect hops per HTTP request: 10.
- HTML bytes read for a canonical check: 2 MiB per page.
- Request timeout: 15 seconds.

Remote downloads and local file reads are consumed in bounded chunks. The response body for status-only checks is not downloaded. Canonical inspection reads a bounded HTML response.

Requests' timeout is a connection/read inactivity timeout; it is not a strict total wall-clock deadline for the entire operation. The byte and URL ceilings bound resource use but do not constitute a complete execution-time guarantee.

## HTTP checks

For a `urlset`, optional checks record:

- HTTP status
- final URL after redirects
- redirect count
- response Content-Type
- request errors

A dedicated Requests session applies the configured redirect ceiling. HTTP checks are limited to the first configured number of valid `loc` entries. A sitemap index is not recursively downloaded in this release; its child sitemap URLs are validated as entries only.

These observations can vary with CDN, WAF, authentication, geolocation, rate limiting, DNS, and server state.

## Canonical checks

With `--check-canonical`, HTML and XHTML responses are read up to the 2 MiB canonical-inspection ceiling. The first canonical link with a non-empty href is resolved relative to the final response URL.

Comparison normalizes scheme and hostname case and default ports, but preserves path, query, and fragment. It does not collapse repeated slashes or otherwise rewrite URL paths. A missing or invalid canonical is reported as missing or invalid evidence, not as proof of a search-engine canonical decision.

## Interpretation and limitations

The validator reports implementation evidence from the environment making the request. It does not determine:

- whether Google or another search engine indexed a URL
- which canonical a search engine selected
- crawl frequency or ranking positions
- JavaScript-rendered page state
- behavior under every crawler user agent or network location
- whether a sitemap submission has been processed by a search engine

A successful response, structurally valid sitemap, or matching canonical does not guarantee indexing, ranking, or search visibility.

## Responsible use

Only check websites and URLs you are authorized to request. This CLI makes outbound requests to the sitemap source and, when enabled, to URLs listed inside a sitemap. Do not expose it as an unauthenticated public URL-fetching service. Server-side integration requires additional SSRF controls, outbound network restrictions, DNS-rebinding-aware destination validation, authentication, rate limiting, and abuse monitoring.
