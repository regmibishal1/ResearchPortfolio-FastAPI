# Security

## Reporting a problem

Please report security problems privately, not in a public issue: open the repository's
**Security** tab on GitHub and choose **Report a vulnerability**. If you cannot use GitHub,
email contact@bishalregmi.com.

Useful to include: the endpoint, the request you sent (without any real tokens), and what
came back.

## Scope

- The API at api.bishalregmi.com, built from this repository.
- Sign-in at auth.bishalregmi.com is a separate service whose code is private; report
  problems with it through
  [ResearchPortfolio-UI](https://github.com/regmibishal1/ResearchPortfolio-UI/security/policy).

## What the API does with data

- It serves public, read-only data: the World Cup 2026 archive, the stocks signals behind
  a hidden page, and a statistics sampler. It stores nothing about the people who call it.
- The `X-API-Key` header is not a secret: the key ships in the site's public code and only
  keeps casual bots out. Cloudflare rate limiting and CORS do the real work.
- New data is written only through the ingest routes, which need an admin token that never
  reaches a browser. The public routes read through a SELECT-only database role; only the
  ingest routes have a connection that can write.
- Each request is logged with its method, path, status, time taken, client IP and a request
  id. Request bodies, tokens and API keys are never logged.
