"""HTTP for the collectors: polite, cached, logged. Standard library only.

Every response is stored under <idea>/data/raw/ with its SHA-256, so a fact
built from it can be re-checked later and the raw data audited. Every call,
successful or not, is appended to <idea>/data/collect-log.jsonl.
"""

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from .common import IdeaError, Idea, now_iso, read_json, write_json

USER_AGENT = "Mozilla/5.0 (compatible; idea-evaluator/1.0; personal research)"
MIN_INTERVAL = {"default": 1.0, "suggestqueries.google.com": 1.5, "hn.algolia.com": 0.5,
                "api.github.com": 6.5, "api.stackexchange.com": 1.0, "ec.europa.eu": 1.0}
CACHE_DAYS = 30
_last_call = {}


class FetchError(IdeaError):
    pass


def _http_get(url, headers, timeout):
    """The one place that touches the network. Tests replace it."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(20 * 1024 * 1024)
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            status = resp.status
    except urllib.error.HTTPError as e:
        raise FetchError("HTTP %s from %s" % (e.code, urllib.parse.urlsplit(url).netloc))
    except (urllib.error.URLError, OSError) as e:
        raise FetchError("cannot reach %s: %s" % (urllib.parse.urlsplit(url).netloc, str(e)[:120]))
    if enc == "gzip" or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    elif enc == "deflate":
        body = zlib.decompress(body)
    return status, body


HTTP_GET = _http_get
SLEEP = time.sleep


def _polite(host):
    gap = MIN_INTERVAL.get(host, MIN_INTERVAL["default"])
    last = _last_call.get(host)
    if last is not None:
        wait = gap - (time.time() - last)
        if wait > 0:
            SLEEP(wait)
    _last_call[host] = time.time()


def _log(idea, entry):
    path = idea.p("data", "collect-log.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = dict(entry, at=now_iso())
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_skip(idea, source, query, reason):
    _log(idea, {"source": source, "query": query, "status": "skipped", "error": reason})


def log_error(idea, source, query, error):
    _log(idea, {"source": source, "query": query, "status": "error", "error": str(error)[:300]})


def _redact(url):
    """Never store API keys in logs or facts."""
    parts = urllib.parse.urlsplit(url)
    q = [(k, "REDACTED" if k.lower() in ("key", "api_key", "access_token") else v)
         for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def get(idea, source, url, query=None, as_json=True, headers=None, refresh=False, timeout=25):
    """Fetch a URL through the cache. Returns (data, raw_file, sha256)."""
    safe_url = _redact(url)
    key = hashlib.sha1(safe_url.encode("utf-8")).hexdigest()[:16]
    raw_dir = idea.p("data", "raw")
    meta_path = os.path.join(raw_dir, "%s-%s.meta.json" % (source, key))
    body_path = os.path.join(raw_dir, "%s-%s.body" % (source, key))
    if not refresh and os.path.exists(meta_path) and os.path.exists(body_path):
        meta = read_json(meta_path)
        age_days = (time.time() - meta.get("fetched_ts", 0)) / 86400.0
        if age_days <= CACHE_DAYS:
            with open(body_path, "rb") as fh:
                body = fh.read()
            return _decode(body, as_json, source), os.path.relpath(body_path, idea.dir), meta["sha256"]
    host = urllib.parse.urlsplit(url).netloc
    _polite(host)
    contact = os.environ.get("IDEAKIT_CONTACT")
    ua = "%s (%s)" % (USER_AGENT, contact) if contact else USER_AGENT
    h = {"User-Agent": ua, "Accept": "application/json" if as_json else "*/*",
         "Accept-Encoding": "gzip"}
    h.update(headers or {})
    try:
        status, body = HTTP_GET(url, h, timeout)
    except FetchError as e:
        log_error(idea, source, query or safe_url, e)
        raise
    sha = hashlib.sha256(body).hexdigest()
    os.makedirs(raw_dir, exist_ok=True)
    with open(body_path, "wb") as fh:
        fh.write(body)
    write_json(meta_path, {"url": safe_url, "source": source, "query": query, "status": status,
                           "fetched_at": now_iso(), "fetched_ts": time.time(), "sha256": sha})
    data = _decode(body, as_json, source)
    _log(idea, {"source": source, "query": query or safe_url, "status": "ok", "url": safe_url, "sha256": sha})
    return data, os.path.relpath(body_path, idea.dir), sha


def _decode(body, as_json, source):
    text = body.decode("utf-8", errors="replace")
    if not as_json:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise FetchError("%s did not return JSON (blocked, or the API changed)" % source)


def raw_sha_ok(idea, raw_file, sha):
    path = os.path.join(idea.dir, raw_file)
    if not os.path.exists(path):
        return False
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest() == sha


def log_entries(idea):
    from .common import read_jsonl
    return read_jsonl(idea.p("data", "collect-log.jsonl"))


def store_raw(idea, source, query, obj):
    """For collectors that use a library instead of HTTP (trends, Google Play): store what it returned."""
    body = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    key = hashlib.sha1(("%s|%s" % (source, query)).encode("utf-8")).hexdigest()[:16]
    raw_dir = idea.p("data", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    body_path = os.path.join(raw_dir, "%s-%s.body" % (source, key))
    with open(body_path, "wb") as fh:
        fh.write(body)
    write_json(os.path.join(raw_dir, "%s-%s.meta.json" % (source, key)),
               {"url": None, "source": source, "query": query, "fetched_at": now_iso(),
                "fetched_ts": time.time(), "sha256": sha})
    _log(idea, {"source": source, "query": query, "status": "ok", "sha256": sha})
    return os.path.relpath(body_path, idea.dir), sha
