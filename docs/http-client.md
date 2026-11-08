# HTTP client contract

This is a development contract, not an installed runtime dependency. Each skill keeps its
implementation and source policy inside its own directory. Standard-library and HTTPX clients
are both supported. Do not add a shared package, generated copies or cross-skill imports just
to satisfy this contract. A separate repository can adopt the same behavior independently.

## Requests and source policy

- Validate supported HTTPS destinations and read operations before opening a connection.
  POST is allowed only for specifically implemented read-only queries, not arbitrary writes.
  Preserve TLS verification and do not import credentials or authenticated browser sessions.
- Requests are serial. Each source defines its request budget, pacing bucket and interval,
  timeout, response cap, cache policy and failure stopping scope. Preserve those differences.
  A failed network attempt consumes budget. Cache hits do not. Redirect hops consume network
  budget and pacing when following redirects is explicitly supported.
- Reject redirects by default. Tabelog alone follows a bounded chain, revalidating every
  destination. Preselected curl for JAPAN RAIL PASS is a source requirement, not a failure
  fallback. Never automatically retry, rotate identities or switch transports after failure.
- Expose Retry-After when provided on a denial. Source adapters/callers honor cooldowns and
  stop at the documented scope; that may be a host, provider or entire invocation. Reading an
  independently requested provider is not retrying the failed provider. Cached successful
  documents may be retained without more network requests.

## Complete and bounded responses

- These integrations expect HTTP 200 documents. Do not parse 204, 206, denial or redirect
  responses as successful documents. Preserve the observed HTTP status in the error.
- Apply a finite transport/socket timeout and a finite body cap. Do not advertise a socket
  timeout as a guaranteed whole-command deadline. Streaming clients also check elapsed time
  while consuming chunks. The source-specific limits remain documented in each skill.
- Reject oversized bodies, interrupted reads and malformed or inconsistent Content-Length.
  Check length against the same representation: HTTPX yields decoded bytes, so do not compare
  those bytes to a compressed Content-Length. Its HTTP framing/decoder failures remain errors;
  its decoded body cap still applies. urllib clients read undecoded bodies.
- Do not cache failed or truncated transfers. Decode and parse only after transport checks.
  Parsers retain their own encoding, source identity, schema and freshness validation.

## Errors and measurements

- Translate expected connection, timeout and HTTP protocol errors into the skill's structured
  error type. Include a safe exception class name when useful, never the raw backend message
  or credentials. `network_error` identifies transport failure; HTTP failures carry
  `http_status`; `incomplete_response` identifies an observed length mismatch. Existing
  source-specific budget/size codes and CLI exit codes need not be renamed.
- Transport errors add `network_reason` when typed evidence is available: `dns`, `tls`,
  `timeout`, `connection_refused`, `connection_lost`, `protocol` or `unknown`. The preselected
  curl adapter can additionally identify `connection_failed` from exit code 7. This classifies
  the observed failure, not its server-side root cause or whether a proxy was involved.
  Follow at most eight explicit exception causes or exception-valued `URLError.reason` links,
  with cycle detection. Never infer a reason from message text or unrelated implicit context.
  Unknown cases stay `unknown`; HTTP denials retain their existing status/cooldown semantics.
  curl maps only documented codes 5/6, 7, 28, 35/60; other exits remain unknown. No stderr is parsed.
- Transport failure means unknown data. Business code decides whether the complete result is
  an error, unavailable or partial. The HTTP client cannot infer sold-out seats, no trains or
  good weather from an unsuccessful request.
- Count client-observed request starts, consumed response body bytes, cache hits where caching
  exists, pacing and elapsed time. Preserve known consumed bytes on failure, including
  `IncompleteRead.partial`. Bytes are not wire traffic; unavailable measurements stay unknown.
  Do not claim model-token, monetary, CPU or memory measurements.

## Offline verification

`tests/test_http_contract.py` exercises the actual clients through small test adapters. The
matrix covers successful reads, caching where supported, finite timeouts, request budgets,
connection/protocol failures, denial metadata, redirects, partial statuses, body limits,
length mismatches and usage after failure. HTTPX tests also cover compressed responses and
partially consumed streams. Source-specific tests retain endpoint, pacing, stopping and
business-result checks. The tests are development resources and are not shipped with skills.

When changing a client, run this matrix and the affected source tests, then one small explicit
live read if network behavior changed. Keep live captures and validation records outside the
repository. Live success does not replace the offline failure cases.
