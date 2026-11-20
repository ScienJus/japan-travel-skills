"""Bounded, anonymous reads of Hot Pepper Gourmet directory and restaurant pages."""
import http.client
import re
import time
import urllib.error
import urllib.request

from .network import network_reason

BASE = "https://www.hotpepper.jp"
SHOP_ID = r"J[0-9]{9}"
AREA = r"/SA[0-9]{2}/(?:Y[A-Z0-9]{3}/(?:X[A-Z0-9]{3}/)?)?(?:G[0-9]{3}/)?"
SHOP = rf"/str{SHOP_ID}/"
COURSE_ID = r"[a-zA-Z0-9_-]{1,64}"
STOCK = "/CSP/imrCourseCalendar/ajaxCourseFullDateStock"
STOCK_QUERY = (re.escape(STOCK) + rf"\?SP={SHOP_ID}&RDT=[0-9]{{8}}&CN={COURSE_ID}"
               + r"&CB=&RTM=(?:[01][0-9]|2[0-3])[0-5][0-9]&RPN=[1-9][0-9]{0,2}")
LIMIT = 2 * 1024 * 1024


class SourceError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError("unexpected_redirect", "Source redirected this page.", http_status=code)


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(RejectRedirect())
        self.requests = self.response_bytes = 0
        self.started = time.monotonic()

    def read(self, url):
        if not re.fullmatch(re.escape(BASE) + rf"(?:/|{AREA}|{SHOP}(?:course/)?|{STOCK_QUERY})", url):
            raise SourceError("unsupported_url", "Expected a public Hot Pepper Gourmet directory or shop URL.")
        if self.requests:
            raise SourceError("request_budget_exhausted", "One page per command.")
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": "japan-travel-skills (anonymous restaurant reader)", "Accept": "text/html"})
        try:
            with self.opener.open(req, timeout=15) as response:
                if response.status != 200:
                    raise SourceError("unexpected_status", "Expected a complete HTTP 200 page.", http_status=response.status)
                raw = response.read(LIMIT + 1)
                self.response_bytes += len(raw)
                if len(raw) > LIMIT:
                    raise SourceError("response_too_large", "Source page exceeds the body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise SourceError("incomplete_response", "Body size does not match Content-Length.")
                return raw
        except urllib.error.HTTPError as exc:
            details = {"http_status": exc.code}
            if exc.headers and exc.headers.get("Retry-After"):
                details["retry_after"] = exc.headers["Retry-After"]
            raise SourceError("http_error", "Source denied or failed the request.", **details) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            if isinstance(exc, http.client.IncompleteRead):
                self.response_bytes += len(exc.partial)
            raise SourceError("network_error", "Could not read the source page.",
                              exception_type=type(exc).__name__, network_reason=network_reason(exc)) from None

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000), "scope": "This invocation"}
