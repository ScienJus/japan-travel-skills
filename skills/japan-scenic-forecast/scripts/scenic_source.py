"""Bounded single-source reads for the two supported scenic forecasts."""
import datetime as dt
import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9), "Asia/Tokyo")
TATEYAMA = "https://homerun.wni.co.jp/TOKS/view.html"
TERRACE = "https://www.fuefuki-kanko.jp/scontents/fujiyamatwinterrace/index.html"
TERRACE_DATA = "https://www.fuefuki-kanko.jp/weathernews/ajax/forecast.cfm"
BODY_LIMIT = 128 * 1024


def network_reason(error):
    """Classify typed evidence only; never inspect exception messages or implicit context."""
    seen = set()
    for _ in range(8):
        if not isinstance(error, BaseException) or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, TimeoutError):
            return "timeout"
        if isinstance(error, socket.gaierror):
            return "dns"
        if isinstance(error, ssl.SSLError):
            return "tls"
        if isinstance(error, ConnectionRefusedError):
            return "connection_refused"
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return "connection_lost"
        if isinstance(error, http.client.HTTPException):
            return "protocol"
        reason = error.reason if isinstance(error, urllib.error.URLError) else None
        error = reason if isinstance(reason, BaseException) else error.__cause__
    return "unknown"


class SourceError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def fail(message):
    raise SourceError('source_schema_changed', message)


def now_jst():
    return dt.datetime.now(JST)


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError("unexpected_redirect", "Source redirect rejected.", http_status=code)


class Client:
    def __init__(self):
        self.started = time.monotonic()
        self.requests = self.bytes = 0
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url):
        if url not in (TATEYAMA, TERRACE_DATA):
            raise SourceError("unsupported_url", "Unsupported scenic forecast source.")
        if self.requests:
            raise SourceError("request_budget_exhausted", "One source read per command.")
        self.requests += 1
        headers = {"User-Agent": "japan-travel-skills (anonymous scenic forecast reader)"}
        if url == TERRACE_DATA:
            headers["X-Requested-With"] = "XMLHttpRequest"
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise SourceError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(BODY_LIMIT + 1)
                self.bytes += len(raw)
                if len(raw) > BODY_LIMIT:
                    raise SourceError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise SourceError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as error:
            details = {"http_status": error.code}
            if error.headers and error.headers.get("Retry-After"):
                details["retry_after"] = error.headers["Retry-After"]
            raise SourceError("http_error", "Source returned an HTTP error.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            if isinstance(error, http.client.IncompleteRead):
                self.bytes += len(error.partial)
            raise SourceError("network_error", "Source request failed.",
                              exception_type=type(error).__name__, network_reason=network_reason(error)) from None
        return raw

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.bytes,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000)}
