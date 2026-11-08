"""Bounded anonymous official-document transport and loss-aware HTML records."""
import socket
import ssl

import datetime as dt
import http.client
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse as urls
import urllib.request

LIMIT = 2 * 1024 * 1024
JST = dt.timezone(dt.timedelta(hours=9))


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


class Error(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def fail(message):
    raise Error("source_schema_changed", message)


def text(value):
    return re.sub(r"\s+", " ", value).strip()


def norm(value):
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def one(values, message):
    values = list(values)
    if len(values) != 1:
        fail(message)
    return values[0]


class Node:
    def __init__(self, tag="", attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def nodes(self, tag=None, cls=None):
        for c in self.children:
            if isinstance(c, Node):
                if (tag is None or c.tag == tag) and (
                    cls is None or cls in c.attrs.get("class", "").split()
                ):
                    yield c
                yield from c.nodes(tag, cls)

    def text(self):
        if self.tag in ("script", "style", "nav", "footer", "form"):
            return ""
        if self.tag == "img":
            return self.attrs.get("alt", "")
        return text(
            " ".join(c.text() if isinstance(c, Node) else c for c in self.children)
        )


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        try:
            self.html = raw.decode("utf-8-sig")
        except UnicodeError:
            fail("Expected UTF-8 official HTML.")
        self.root = Node()
        self.stack = [self.root]
        self.feed(self.html)
        self.close()
        self.title = one(
            self.root.nodes("title"), "Missing/duplicate document title."
        ).text()
        if re.search(
            r"just a moment|access denied|forbidden|captcha|service unavailable",
            self.title,
            re.I,
        ):
            fail("Source did not return the expected information page.")
        mains = list(self.root.nodes("main"))
        self.main = (
            one(mains, "Missing/duplicate main information area.")
            if mains
            else one(self.root.nodes("body"), "Missing HTML body.")
        )

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in (
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Error(
            "unexpected_redirect",
            "Redirect rejected; no retry or alternate client.",
            http_status=code,
        )


class Client:
    def __init__(self, allowed, budget=8):
        self.allowed = allowed
        self.budget = budget
        self.started = time.monotonic()
        self.requests = self.bytes = self.pacing_ms = 0
        self.last = None
        self.last_source = None
        self.cache = {}
        self.cache_hits = 0
        self.blocked = set()
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url, transport="python"):
        url = urls.urldefrag(url)[0]
        if not self.allowed(url):
            raise Error(
                "unsupported_url",
                "Only configured official information documents are allowed.",
            )
        if url in self.cache:
            self.cache_hits += 1
            return self.cache[url]
        host = urls.urlsplit(url).netloc
        if host in self.blocked:
            raise Error(
                "source_stopped",
                "This source failed earlier in this invocation; no further requests.",
            )
        if self.requests >= self.budget:
            raise Error(
                "request_budget_exhausted",
                "Official pass read budget exhausted.",
                limit=self.budget,
            )
        if transport == "curl" and not shutil.which("curl"):
            raise Error(
                "missing_dependency",
                "This source requires curl with modern TLS support.",
            )
        delay = (
            max(0, 1.5 - (time.monotonic() - self.last)) if self.last is not None else 0
        )
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay * 1000)
        self.last = time.monotonic()
        self.requests += 1
        self.last_source = {
            "url": url,
            "publisher_updated_at": None,
            "retrieved_at": None,
            "transport": transport,
        }
        try:
            if transport == "curl":
                raw, modified, status = self.curl(url)
            else:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "japan-travel-skills (anonymous official pass reader)",
                        "Accept": "text/html",
                    },
                )
                with self.opener.open(req, timeout=15) as response:
                    status = response.status
                    raw = response.read(LIMIT + 1)
                    self.bytes += len(raw)
                    modified = response.headers.get("Last-Modified")
                    length = response.headers.get("Content-Length")
                    if len(raw) <= LIMIT and length is not None and (
                        not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))
                    ):
                        raise Error("incomplete_response", "Body size does not match Content-Length.")
            if status != 200:
                raise Error(
                    "http_error",
                    "Expected an HTTP 200 information document.",
                    http_status=status,
                )
            if len(raw) > LIMIT:
                raise Error(
                    "response_too_large", "Official pass document exceeds 2 MiB."
                )
        except urllib.error.HTTPError as e:
            self.blocked.add(host)
            details = {"http_status": e.code}
            if e.headers and e.headers.get("Retry-After"):
                details["retry_after"] = e.headers["Retry-After"]
            raise Error(
                "http_error",
                "Official source denied or failed the request; no retry.",
                **details,
            ) from None
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            subprocess.SubprocessError,
        ) as e:
            self.blocked.add(host)
            if isinstance(e, http.client.IncompleteRead):
                self.bytes += len(e.partial)
            raise Error(
                "network_error",
                "Official source could not be read; no retry.",
                exception_type=type(e).__name__,
                network_reason=network_reason(e, timeout_types=(subprocess.TimeoutExpired,)),
            ) from None
        except Error:
            self.blocked.add(host)
            raise
        meta = {
            **self.last_source,
            "retrieved_at": dt.datetime.now(JST).isoformat(),
            "http_last_modified_raw": modified,
        }
        self.last_source = meta
        self.cache[url] = (raw, meta)
        return raw, meta

    def curl(self, url):
        with tempfile.TemporaryDirectory(prefix="japan-passes-") as directory:
            body = Path(directory) / "body"
            headers = Path(directory) / "headers"
            command = [
                "curl",
                "-q",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--connect-timeout",
                "10",
                "--max-time",
                "20",
                "--max-filesize",
                str(LIMIT),
                "--silent",
                "--show-error",
                "--output",
                str(body),
                "--dump-header",
                str(headers),
                "--write-out",
                "%{http_code}",
                url,
            ]
            result = subprocess.run(command, capture_output=True, timeout=25)
            raw = b""
            if body.exists():
                self.bytes += body.stat().st_size
                with body.open("rb") as stream:
                    raw = stream.read(LIMIT + 1)
            if result.returncode:
                raise Error(
                    "transport_error",
                    "curl source read failed; no retry.",
                    exit_code=result.returncode,
                    network_reason={5: "dns", 6: "dns", 7: "connection_failed", 28: "timeout",
                                    35: "tls", 60: "tls"}.get(result.returncode, "unknown"),
                )
            try:
                status = int(result.stdout.decode("ascii"))
            except (ValueError, UnicodeError):
                raise Error(
                    "transport_error", "Unexpected curl status output."
                ) from None
            modified = None
            fields = {}
            if headers.exists():
                for line in headers.read_text(errors="replace").splitlines():
                    if line.startswith("HTTP/"):
                        fields = {}
                    elif ":" in line:
                        key, value = line.split(":", 1)
                        fields[key.lower()] = value.strip()
                    if line.lower().startswith("last-modified:"):
                        modified = line.split(":", 1)[1].strip()
            length = fields.get("content-length")
            if status == 200 and length is not None and (
                not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))
            ):
                raise Error("incomplete_response", "Body size does not match Content-Length.")
            if fields.get("retry-after"):
                raise Error("http_error", "Source requested a cooldown; no retry.",
                            http_status=status, retry_after=fields["retry-after"])
            return raw, modified, status

    def usage(self):
        return {
            "http_requests": self.requests,
            "response_body_bytes": self.bytes,
            "memory_cache_hits": self.cache_hits,
            "pacing_ms": self.pacing_ms,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
            "scope": "This invocation; no token/money estimate. Sources share reads only within the invocation.",
        }


SKIP = {"script", "style", "nav", "footer", "header", "form", "button", "noscript"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
STOP = re.compile(
    r"^(?:Destinations|Recommended Spots|Special Offer|See also|Useful Links|Our Recommendations|Tourist Information|Travel Tips|Campaign|How much can you save)",
    re.I,
)
NOTICE = re.compile(
    r"(?:sales? (?:ended|end|suspended)|discontinued|no longer|as of|from .{0,35}20\d\d|until .{0,35}20\d\d|20\d\d.{0,40}(?:price|sale|valid|change)|subject to change)",
    re.I,
)


def image(node, url):
    if not node.attrs.get("src"):
        return None
    src = urls.urljoin(url, node.attrs.get("src", ""))
    if urls.urlsplit(src).scheme != "https":
        return None
    return {
        "url": src,
        "alt": node.attrs.get("alt", ""),
        "state": "reference_only_not_ocr",
    }


def table(node, url):
    rows = []
    for row in node.nodes("tr"):
        # A nested layout table has its own table record; never splice its cells.
        ancestor = row.parent
        while ancestor is not None and ancestor.tag != "table":
            ancestor = ancestor.parent
        if ancestor is not node:
            continue
        cells = []
        for cell in row.children:
            if not isinstance(cell, Node) or cell.tag not in ("th", "td"):
                continue
            spans = {}
            for key in ("rowspan", "colspan"):
                value = cell.attrs.get(key, "1")
                if not re.fullmatch(r"[1-9][0-9]?", value):
                    fail("Invalid official table span.")
                spans[key] = int(value)
            cells.append(
                {
                    "kind": cell.tag,
                    "text": cell.text(),
                    **spans,
                    "images": [
                        v for v in (image(i, url) for i in cell.nodes("img")) if v
                    ],
                }
            )
        if len(cells) > 60:
            fail("Official table exceeds the supported column limit.")
        if cells:
            rows.append(cells)
        if len(rows) > 200:
            fail("Official table exceeds the supported row limit.")
    return rows


def sections(root, url, seed=()):
    result = []
    path = list(seed)
    current = None
    stopped_level = None

    def add(kind, value):
        nonlocal current
        if current is None:
            current = {"heading_path": [h for _, h in path], "blocks": []}
            result.append(current)
        current["blocks"].append({"kind": kind, "value": value})

    def visit(node):
        nonlocal path, current, stopped_level
        if node.tag in SKIP:
            return
        if node.tag in HEADINGS:
            level = int(node.tag[1])
            heading = node.text()
            if not heading:
                return
            if stopped_level is not None:
                if level > stopped_level:
                    return
                stopped_level = None
            path = [(n, h) for n, h in path if n < level] + [(level, heading)]
            current = None
            if STOP.search(heading):
                stopped_level = level
            return
        if stopped_level is not None and not any(
            n.tag in HEADINGS for n in node.nodes()
        ):
            return
        if node.tag == "table":
            rows = table(node, url)
            if rows:
                add("table", rows)
            return
        if node.tag == "img":
            item = image(node, url)
            if item:
                add("image", item)
            return
        if node.tag in ("p", "li", "dt", "dd"):
            # Recurse when the publisher nests headings/tables inside a block.
            if not any(n.tag in HEADINGS or n.tag == "table" for n in node.nodes()):
                value = node.text()
                if value:
                    add("text", value)
                for img in node.nodes("img"):
                    item = image(img, url)
                    if item:
                        add("image", item)
                return
        for c in node.children:
            if isinstance(c, Node):
                visit(c)
            elif text(c) and stopped_level is None:
                add("text", text(c))

    visit(root)
    # Remove exact responsive duplicates only; retain distinct table layouts.
    for section in result:
        seen = set()
        blocks = []
        for block in section["blocks"]:
            key = json.dumps(block, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                blocks.append(block)
        section["blocks"] = blocks
    return [s for s in result if s["blocks"]]


def notices(records):
    found = []
    for record in records:
        for block in record["blocks"]:
            if block["kind"] == "text" and NOTICE.search(block["value"]):
                item = {"heading_path": record["heading_path"], "text": block["value"]}
                if item not in found:
                    found.append(item)
    return found
