"""Bounded anonymous Yahoo transport; request policy stays local to this skill."""
import http.client
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from transit_network import network_reason
from transit_source import BASE, MAX_BYTES, TransitError


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransitError("unexpected_redirect", "Source redirected the request; no redirect or visitor setup was followed.", http_status=code)


class Client:
    def __init__(self):
        self.requests = self.response_bytes = self.cache_hits = self.pacing_ms = 0
        self.started = time.monotonic()
        self.last_started = None
        self.cache = {}
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "transit.yahoo.co.jp":
            raise TransitError("unsupported_host", "Only the configured public source may be queried.")
        if url in self.cache:
            self.cache_hits += 1
            return self.cache[url]
        if self.requests >= 6:
            raise TransitError("request_budget_exhausted", "Stopped at six reads per invocation.")
        if self.last_started is not None:
            delay = max(0, 1 - (time.monotonic() - self.last_started))
            if delay:
                time.sleep(delay)
                self.pacing_ms += round(delay * 1000)
        self.requests += 1
        self.last_started = time.monotonic()
        try:
            with self.opener.open(urllib.request.Request(url, headers={
                "User-Agent": "japan-travel-skills/0.1 (anonymous transit reader)",
                "Accept": "application/json,text/html;q=0.8",
            }), timeout=15) as response:
                if response.status != 200:
                    raise TransitError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes += len(raw)
                if len(raw) > MAX_BYTES:
                    raise TransitError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise TransitError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as exc:
            details = {"http_status": exc.code}
            if exc.headers and exc.headers.get("Retry-After"):
                details["retry_after"] = exc.headers["Retry-After"]
            raise TransitError("http_error", "Source denied or failed the request; no retry was attempted.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            if isinstance(exc, http.client.IncompleteRead):
                self.response_bytes += len(exc.partial)
            raise TransitError("network_error", "Could not read source; no retry was attempted.", exception_type=type(exc).__name__, network_reason=network_reason(exc)) from None
        self.cache[url] = raw
        return raw

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "memory_cache_hits": self.cache_hits, "pacing_ms": self.pacing_ms,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "scope": "This invocation; body bytes exclude HTTP/TLS overhead. No token or monetary estimate."}
