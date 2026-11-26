# Security

## Supported use

This project is a local command-line sitemap diagnostic. It accepts a sitemap URL or local XML file path and can make additional HTTP requests to URLs listed in a sitemap.

The XML parser uses `defusedxml` and rejects DTD/entity declarations. Remote sitemap downloads, local file reads, and optional canonical HTML reads have explicit byte ceilings. HTTP requests have a timeout and redirect-hop ceiling.

## SSRF warning for server-side integrations

The CLI accepts operator-supplied URLs and may request every valid page URL in a sitemap up to the configured HTTP-check limit. If this code is embedded in a website, API, worker, or other server-side service that accepts untrusted input, attackers may attempt to make the server request loopback, private-network, link-local, or cloud metadata endpoints (server-side request forgery / SSRF).

The built-in URL syntax checks and redirect limit are **not** a complete SSRF defense. A server deployment must, at minimum:

- Restrict destinations with a strict allowlist wherever possible.
- Block loopback, private, link-local, multicast, reserved, and cloud metadata address ranges for both IPv4 and IPv6.
- Validate DNS answers and bind validation to the actual connection to reduce DNS-rebinding risk.
- Revalidate every redirect target, or disable automatic redirects.
- Restrict outbound network access at the infrastructure layer.
- Require authentication, enforce per-user quotas and rate limits, and monitor abuse.
- Avoid returning raw internal response details to untrusted callers.

Do not expose this CLI as an unauthenticated public URL-fetching endpoint.

## Safe use

- Only test URLs you are authorized to request.
- Respect site terms, access controls, and rate limits.
- Do not include credentials, private URLs, authentication headers, or sensitive website data in public issues.
- Keep request and sitemap-size limits conservative for your environment.

## Reporting a security issue

Do not publish exploitable details in a public issue. Contact the repository maintainer privately through the contact method available on the maintainer's GitHub profile.
