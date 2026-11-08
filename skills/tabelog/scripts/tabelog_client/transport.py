"""One anonymous pooled HTTP client, bounded bodies, pacing and fail-closed denials."""
import http.client
import socket
import ssl
import urllib.error
import json
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from urllib.parse import urlsplit, urljoin

import httpx

from .core import CliError, public_url, safe_url

MAX_BYTES = 8 * 1024 * 1024


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


def request_headers(url):
    u = urlsplit(url)
    xhr = u.hostname == "tabelog.com" and re.search(r"/(?:suggest/|web-api/|booking/calendar/)", u.path)
    accept = "application/json, text/javascript, */*; q=0.01" if xhr or u.hostname in ("msearch.gsi.go.jp", 'photon.komoot.io') else (
        "application/xml, text/xml;q=0.9, */*;q=0.5" if u.path.startswith("/xml/") else
        "text/javascript, application/javascript;q=0.9, */*;q=0.5" if u.path.endswith(".js") else
        "text/html, application/xhtml+xml;q=0.9, */*;q=0.5")
    return {"User-Agent": f"japan-restaurant-skills/0.2.0 (Python/{sys.version_info.major}.{sys.version_info.minor})",
            "Accept": accept, "Accept-Language": "en,ja;q=0.9", "Accept-Encoding": "gzip, deflate",
            **({"X-Requested-With": "XMLHttpRequest", "Referer": "https://tabelog.com/en/"} if xhr else {})}


def retry_after(value, now=None):
    if not isinstance(value, str):
        return {}
    now = time.time() if now is None else now
    try:
        seconds = int(value) if re.fullmatch(r"\d+", value.strip()) else max(0, int(parsedate_to_datetime(value).timestamp()-now+0.999))
        if seconds < 0:
            return {}
        deadline = datetime.fromtimestamp(now+seconds, timezone.utc).isoformat().replace("+00:00", "Z")
        return {"retry_after_seconds": seconds, "retry_not_before": deadline}
    except (ValueError, TypeError, OverflowError, OSError):
        return {}


class RequestPacer:
    def __init__(self, min_ms=1000, max_ms=2500, now=time.monotonic, sleep=time.sleep, rng=random.random):
        self.min_ms, self.max_ms = min_ms, max_ms
        self.now, self.sleep, self.rng = now, sleep, rng
        self.finished, self.wait_ms, self.waits = {}, 0, 0

    @staticmethod
    def key(url):
        host = urlsplit(url).hostname
        return "tabelog" if host == "tabelog.com" or host.endswith(".tabelog.com") or host == "tblg.k-img.com" else host

    def before(self, url):
        previous = self.finished.get(self.key(url))
        if previous is None:
            return
        gap = self.min_ms + int(self.rng()*(self.max_ms-self.min_ms+1))
        wait = max(0, previous+gap/1000-self.now())
        if wait:
            started = self.now()
            self.sleep(wait)
            self.wait_ms += max(0, (self.now()-started)*1000)
            self.waits += 1

    def after(self, url):
        self.finished[self.key(url)] = self.now()


class Client:
    def __init__(self, timeout=15, max_requests=80, delay_min_ms=1000, delay_max_ms=2500,
                 reader=None, session=None, now=time.monotonic, sleep=time.sleep, rng=random.random):
        if not 0 <= delay_min_ms <= delay_max_ms:
            raise CliError("invalid_argument", "Invalid request delay range.")
        self.timeout, self.max_requests = timeout, max_requests
        self.reader, self.session = reader, session
        self.pacer = RequestPacer(delay_min_ms, delay_max_ms, now, sleep, rng)
        self.started, self.now = now(), now
        self.trace, self.attempts, self.cache = [], [], {}
        self.cache_hits, self.blocked, self.streams = 0, None, []
        self.lock = threading.RLock()
        self.network_requests = 0

    def close(self):
        if self.session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _http(self, url):
        if self.session is None:
            self.session = httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=True,
                                        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1, keepalive_expiry=30))
        metrics = {"network_requests_started": 0, "browser_launches": 0, "response_body_bytes": 0, "connection_reuses": 0}
        final, status, retry = url, None, None
        deadline = self.now()+self.timeout
        try:
            for redirect in range(6):
                if redirect:
                    self.pacer.before(final)
                remaining = deadline-self.now()
                if remaining <= 0:
                    raise httpx.TimeoutException("bounded retrieval timed out")
                request_url = final
                try:
                    if self.network_requests >= self.max_requests:
                        raise CliError("request_budget", "Request budget reached, including redirects.")
                    self.network_requests += 1
                    metrics["network_requests_started"] += 1
                    with self.session.stream("GET", final, headers=request_headers(final), timeout=remaining,
                                             follow_redirects=False) as response:
                        status, retry = response.status_code, response.headers.get("Retry-After")
                        if status in (401, 403, 429, 503) or retry is not None:
                            raise CliError("http_error", "Source denied or deferred access; data is unknown.")
                        stream = response.extensions.get("network_stream")
                        if stream is None:
                            metrics["connection_reuses"] = None
                        elif any(stream is previous for previous in self.streams):
                            if metrics["connection_reuses"] is not None:
                                metrics["connection_reuses"] += 1
                        else:
                            self.streams.append(stream)
                        parts, size = [], 0
                        for part in response.iter_bytes():
                            if self.now() >= deadline:
                                raise httpx.TimeoutException("bounded retrieval timed out")
                            size += len(part)
                            metrics["response_body_bytes"] += len(part)
                            if size > MAX_BYTES:
                                raise CliError("unexpected_response", "Response exceeded size limit.")
                            parts.append(part)
                        length = response.headers.get("Content-Length")
                        if response.headers.get("Content-Encoding", "identity").strip().lower() in ("", "identity") and length is not None and (
                            not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(size)
                        ):
                            raise CliError("incomplete_response", "Body size does not match Content-Length.")
                        body = b"".join(parts).decode("utf-8", errors="replace")
                        if status in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                            if redirect == 5:
                                raise CliError("http_error", "Too many redirects.")
                            if retry:
                                raise CliError("retry_later", "Redirect requested a cooldown.")
                            final = public_url(urljoin(final, response.headers["Location"]))
                            continue
                        return {"http_status": status, "url": final, "body": body, "retry_after": retry,
                                "metrics": metrics, "version": version("httpx")}
                finally:
                    # The outer read records the initial URL too; redirects remain paced.
                    self.pacer.after(request_url)
        except (httpx.HTTPError, CliError, ValueError, OSError) as error:
            code = "rate_limited" if status == 429 else "access_denied" if status in (401, 403) else "service_unavailable" if status == 503 else "retry_later" if retry_after(retry) else error.code if isinstance(error, CliError) else "network_error"
            return {"error": code, "message": str(error) if isinstance(error, CliError) else "HTTP retrieval failed; data is unknown.", "http_status": status,
                    "exception_type": type(error).__name__,
                    **({"network_reason": network_reason(error, timeout_types=(httpx.TimeoutException,),
                                                        protocol_types=(httpx.ProtocolError, httpx.DecodingError))}
                       if code == "network_error" else {}),
                    "retry_after": retry, "metrics": metrics, "version": version("httpx")}

    def read(self, url, format="html", parse=None):
        with self.lock:
            public_url(url)
            if self.blocked:
                raise self.blocked
            attempt = None
            try:
                result = self.cache.get(url)
                if result is None:
                    if len(self.attempts) >= self.max_requests:
                        raise CliError("request_budget", "Request budget reached; coverage is partial.")
                    attempt = {"status": "error"}
                    self.attempts.append(attempt)
                    self.pacer.before(url)
                    started = self.now()
                    try:
                        result = self.reader(url) if self.reader else self._http(url)
                    finally:
                        self.pacer.after(url)
                    attempt.update(metrics=result.get("metrics"), version=result.get("version"), elapsed_ms=round((self.now()-started)*1000))
                    cooldown = retry_after(result.get("retry_after"))
                    status = result.get("http_status")
                    if result.get("error"):
                        code = result["error"]
                        if cooldown and code not in ("rate_limited", "access_denied", "service_unavailable"):
                            code = "retry_later"
                        raise CliError(code, result.get("message", "Retrieval failed."), **cooldown, **({"http_status": status} if status else {}),
                                       **({'exception_type': result['exception_type']} if result.get('exception_type') else {}),
                                       **({'network_reason': result['network_reason']} if code == 'network_error' and result.get('network_reason') else {}))
                    public_url(result["url"])
                    if status != 200:
                        code = "rate_limited" if status == 429 else "access_denied" if status in (401, 403) else "service_unavailable" if status == 503 else "retry_later" if cooldown else "http_error"
                        raise CliError(code, f"HTTP {status}; data is unknown.", http_status=status, **cooldown)
                    if re.search(r'<title>\s*(?:Just a moment|Attention Required)|id=["\'](?:challenge-form|cf-challenge-running)|window\._cf_chl_opt', result["body"], re.I):
                        raise CliError("verification_required", "Upstream verification is required; data is unknown.")
                    self.cache[url] = self.cache[result["url"]] = result
                    self.trace.append({"url": safe_url(url), "final_url": safe_url(result["url"]), "method": "GET", "source_format": format,
                                       "transport": "http", "status": "ok", "http_status": status, "version": result.get("version"),
                                       "elapsed_ms": attempt["elapsed_ms"], "metrics": result.get("metrics")})
                else:
                    self.cache_hits += 1
                value = result["body"]
                if format == "json":
                    try:
                        def reject_constant(_value):
                            raise ValueError("Non-finite JSON number")
                        value = json.loads(value, parse_constant=reject_constant)
                    except (ValueError, TypeError):
                        raise CliError("unexpected_response", "Expected JSON, received an unrecognized response.") from None
                value = parse(value, result["url"]) if parse else value
                if attempt is not None:
                    attempt["status"] = "ok"
                return value
            except Exception as error:
                e = error if isinstance(error, CliError) else CliError("parse_error", "Parser rejected the response.",
                                                                     exception_type=type(error).__name__)
                if e.code in {"rate_limited", "access_denied", "verification_required", "service_unavailable", "retry_later"}:
                    e.details["next_action"] = "Stop this command. Honor retry_not_before. Any real-browser handoff requires explicit authorization."
                    self.blocked = e
                self.trace.append({"url": safe_url(url), "method": "GET", "source_format": format, "transport": "http", "status": "error", **e.as_dict()})
                raise e from None

    def usage(self):
        def total(key):
            values = [(a.get("metrics") or {}).get(key) for a in self.attempts]
            return sum(values) if all(isinstance(v, (int, float)) for v in values) else None
        return {"runtime": {"python": sys.version.split()[0]}, "elapsed_ms": round((self.now()-self.started)*1000),
                "transport_attempts": len(self.attempts), "attempts_by_transport": {"http": len(self.attempts)},
                "cache_hits": self.cache_hits, "network_requests_started": total("network_requests_started"), "browser_launches": 0,
                "response_body_bytes": total("response_body_bytes"), "metrics_complete": all(a.get("metrics") is not None for a in self.attempts),
                "connection_reuses": total("connection_reuses"), "throttle_wait_ms": round(self.pacer.wait_ms), "throttle_waits": self.pacer.waits,
                "dependencies": ([{"transport": "http", "tool": "Python HTTPX (pooled Client)", "versions": sorted({a["version"] for a in self.attempts if a.get("version")}),
                                   "tool_versions": [], "attempts": len(self.attempts), "successful_reads": sum(a["status"] == "ok" for a in self.attempts)}] if self.attempts else []),
                "parser": {"name": "Beautiful Soup + html.parser", "version": version("beautifulsoup4"), "external_process": False},
                'holiday_calendar': {'name': 'jpholiday', 'version': version('jpholiday'), 'network_requests': 0},
                "limits": {"max_transport_attempts": self.max_requests, "timeout_seconds_per_transport": self.timeout,
                           "max_network_requests": self.max_requests,
                           "delay_min_ms": self.pacer.min_ms, "delay_max_ms": self.pacer.max_ms, "concurrency": 1,
                           "scope": "one CLI command; coordinate separate processes explicitly"},
                "measurement_scope": "Counts are client-observed request starts, not confirmed server receipts. Bytes cover decoded response bodies, not wire traffic. Missing measurements are null. No CPU, peak memory, LLM tokens or monetary cost measured."}
