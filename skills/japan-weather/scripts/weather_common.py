"""Shared errors, timestamps and bounded anonymous HTTP reads."""
import ssl
import datetime as dt
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9), "Asia/Tokyo")
MAX_BYTES = 2 * 1024 * 1024


def network_reason(error, *, timeout_types=(), protocol_types=()):
    """Classify typed evidence only; never inspect exception messages or implicit context."""
    seen = set()
    for _ in range(8):
        if not isinstance(error, BaseException) or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, (TimeoutError,) + timeout_types):
            return "timeout"
        if isinstance(error, socket.gaierror):
            return "dns"
        if isinstance(error, ssl.SSLError):
            return "tls"
        if isinstance(error, ConnectionRefusedError):
            return "connection_refused"
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return "connection_lost"
        if isinstance(error, (http.client.HTTPException,) + protocol_types):
            return "protocol"
        reason = error.reason if isinstance(error, urllib.error.URLError) else None
        error = reason if isinstance(reason, BaseException) else error.__cause__
    return "unknown"


class WeatherError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise WeatherError("source_schema_changed", "Boolean supplied as a forecast number.")
    try:
        parsed = float(value)
        if parsed != int(parsed):
            raise ValueError()
        return int(parsed)
    except (TypeError, ValueError, OverflowError):
        raise WeatherError("source_schema_changed", "Unexpected numeric forecast value.") from None


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise WeatherError("source_schema_changed", "Source timestamp has no timezone.")
    return parsed.astimezone(JST)


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WeatherError("unexpected_redirect", "Source redirect rejected; no alternate client was used.", http_status=code)


class Client:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(RejectRedirect())
        self.requests = 0
        self.response_bytes = 0
        self.cache_hits = 0
        self.cache = {}
        self.started = time.monotonic()
        self.last_started = {}
        self.pacing_ms = 0

    def read(self, url):
        if url in self.cache:
            self.cache_hits += 1
            return self.cache[url]
        if self.requests >= 30:
            raise WeatherError("request_budget_exhausted", "Stopped at the 30-request invocation limit.")
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or parsed.netloc != host or parsed.fragment or host not in ("www.jma.go.jp", "weathernews.jp", "site.weathernews.jp", "wxtech.weathernews.com"):
            raise WeatherError("unsupported_host", "Only the configured public weather hosts may be queried.")
        # Both Weathernews hosts share one pacing bucket.
        bucket = "weathernews" if host.endswith("weathernews.jp") else host
        delay = max(0, 1 - (time.monotonic() - self.last_started.get(bucket, 0)))
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay * 1000)
        self.last_started[bucket] = time.monotonic()
        request = urllib.request.Request(url, headers={
            "User-Agent": "japan-travel-skills/0.2 (anonymous weather reader)",
            "Accept": "application/json,text/html;q=0.8",
        })
        self.requests += 1
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise WeatherError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes += len(raw)
                if len(raw) > MAX_BYTES:
                    raise WeatherError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise WeatherError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as exc:
            details = {"http_status": exc.code}
            if exc.headers and exc.headers.get("Retry-After"):
                details["retry_after"] = exc.headers["Retry-After"]
            raise WeatherError("http_error", "Weather source returned HTTP " + str(exc.code) + "; no retry was attempted.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            if isinstance(exc, http.client.IncompleteRead):
                self.response_bytes += len(exc.partial)
            raise WeatherError("network_error", "Could not read weather source; no retry was attempted.", exception_type=type(exc).__name__, network_reason=network_reason(exc)) from None
        self.cache[url] = raw
        return raw

    def get_json(self, url):
        try:
            return json.loads(self.read(url).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise WeatherError("invalid_response", "Weather source did not return valid UTF-8 JSON.") from None

    def get(self, office):
        return self.get_json("https://www.jma.go.jp/bosai/forecast/data/forecast/" + office + ".json")

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "memory_cache_hits": self.cache_hits, "pacing_ms": self.pacing_ms,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "scope": "This invocation only; body bytes exclude HTTP/TLS overhead. No token or monetary estimate."}
