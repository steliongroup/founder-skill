"""The evidence store: every fact with its source, grade and verification state.

A fact counts as strong evidence only after code has fetched its page and found
its quote (and its number, if it has one) there. Until then its grade is D.
"""

import datetime
import os
import urllib.error
import urllib.request

from . import textmatch
from .common import GRADES, STRONG, IdeaError, Idea, lower_grade, now_iso, read_jsonl, write_jsonl

# Default grade by kind of source (GRADE-style certainty of the source itself).
GRADE_BY_TYPE = {
    "official_stat": "A",    # national statistics office, Eurostat, World Bank, filings
    "primary_data": "A",     # the user's own experiment results, raw datasets
    "company_page": "A",     # a company's own page, for facts about that company (price, features)
    "app_store": "A",        # store listing data: ratings, review counts, install buckets
    "academic": "B",         # peer-reviewed or working paper with method and sample
    "industry_report": "B",  # benchmark report with a known sample
    "review_platform": "B",  # individual public reviews, as evidence of what buyers say
    "news": "C",
    "forum": "C",            # Reddit, HN, community posts
    "blog": "C",
    "aggregator": "C",       # secondary summaries of other sources
    "vendor_marketing": "C", # a vendor's claims about a market it sells into
    "other": "D",
}
REQUIRED = ("claim", "url", "quote", "publisher", "source_type")
MAX_AGE_YEARS = 3
USER_AGENT = "Mozilla/5.0 (compatible; idea-evaluator/1.0; personal research)"
MAX_BYTES = 6 * 1024 * 1024


def load(idea):
    return read_jsonl(idea.evidence)


def _next_id(facts):
    n = 0
    for f in facts:
        try:
            n = max(n, int(f["id"][1:]))
        except (KeyError, ValueError):
            pass
    return "F%03d" % (n + 1)


def _check(obj):
    if not isinstance(obj, dict):
        raise IdeaError("a fact must be a JSON object")
    missing = [k for k in REQUIRED if not str(obj.get(k, "")).strip()]
    if missing:
        raise IdeaError("fact is missing: %s" % ", ".join(missing))
    st = obj["source_type"]
    if st not in GRADE_BY_TYPE:
        raise IdeaError("source_type %r is not one of: %s" % (st, ", ".join(GRADE_BY_TYPE)))
    if not str(obj["url"]).startswith(("http://", "https://")):
        raise IdeaError("url must start with http:// or https://")
    if "value" in obj and obj["value"] is not None:
        try:
            float(obj["value"])
        except (TypeError, ValueError):
            raise IdeaError("value must be a number, got %r" % obj["value"])
    default = GRADE_BY_TYPE[st]
    g = obj.get("grade", default)
    if g not in GRADES:
        raise IdeaError("grade must be one of A-D")
    if g != default:
        if abs(GRADES.index(g) - GRADES.index(default)) > 1:
            raise IdeaError("grade can move at most one step from %s (the default for %s)" % (default, st))
        if not str(obj.get("grade_reason", "")).strip():
            raise IdeaError("changing the grade from %s to %s needs a grade_reason" % (default, g))
    return default, g


def add(idea, objs):
    """Add facts. They enter unverified; run verify next. Returns the new ids."""
    if isinstance(objs, dict):
        objs = [objs]
    facts = load(idea)
    seen = {(f["url"], textmatch.normalize(f["quote"])) for f in facts}
    new_ids = []
    for obj in objs:
        default, g = _check(obj)
        key = (obj["url"], textmatch.normalize(obj["quote"]))
        if key in seen:
            raise IdeaError("this quote from %s is already in the evidence" % obj["url"])
        seen.add(key)
        fact = {k: obj[k] for k in obj if k not in ("id", "verified", "verify_status", "verified_at", "match", "stale")}
        fact["id"] = _next_id(facts)
        fact["grade"] = g
        fact["default_grade"] = default
        fact["verified"] = False
        fact["verify_status"] = "pending"
        fact["added_at"] = now_iso()
        facts.append(fact)
        new_ids.append(fact["id"])
    write_jsonl(idea.evidence, facts)
    return new_ids


def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en,it;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "pdf" in ctype.lower():
            raise IdeaError("PDF: save its text as <id>.txt in --html-dir and verify again")
        raw = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _page_text(fact, html_dir, fetch):
    if html_dir:
        for ext in (".html", ".htm", ".txt"):
            p = os.path.join(html_dir, fact["id"] + ext)
            if os.path.exists(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    raw = fh.read()
                return textmatch.html_to_text(raw) if ext != ".txt" else textmatch.normalize(raw)
    return textmatch.html_to_text(fetch(fact["url"]))


def _year(date):
    try:
        return int(str(date)[:4])
    except (TypeError, ValueError):
        return None


def verify_fact(fact, html_dir=None, fetch=fetch_url, today=None):
    """Mutates and returns the fact with its verification result."""
    today = today or datetime.date.today()
    fact["verified_at"] = now_iso()
    try:
        text = _page_text(fact, html_dir, fetch)
    except (urllib.error.URLError, OSError, ValueError, IdeaError) as e:
        fact.update(verified=False, verify_status="unreachable: %s" % str(e)[:160], match=None)
        return fact
    match = textmatch.find_quote(fact["quote"], text)
    if not match:
        fact.update(verified=False, verify_status="quote_not_found", match=None)
        return fact
    if fact.get("value") is not None and not textmatch.contains_number(fact["quote"], fact["value"]):
        fact.update(verified=False, verify_status="value_not_in_quote", match=match)
        return fact
    y = _year(fact.get("date"))
    fact["stale"] = bool(y and today.year - y > MAX_AGE_YEARS)
    fact.update(verified=True, verify_status="ok", match=match)
    return fact


def verify(idea, ids=None, html_dir=None, recheck=False, fetch=fetch_url):
    facts = load(idea)
    done = []
    for f in facts:
        if ids and f["id"] not in ids:
            continue
        if f.get("verified") and not recheck and not ids:
            continue
        verify_fact(f, html_dir, fetch)
        done.append((f["id"], f["verify_status"]))
    write_jsonl(idea.evidence, facts)
    return done


def effective_grade(fact):
    """The grade scoring uses: D unless verified; one step lower if stale."""
    if not fact.get("verified"):
        return "D"
    g = fact.get("grade", "D")
    return lower_grade(g) if fact.get("stale") else g


def is_strong(fact):
    return effective_grade(fact) in STRONG


def triangulation(facts):
    """claim_key -> {publishers, n, triangulated}. Only verified facts count."""
    out = {}
    for f in facts:
        k = f.get("claim_key")
        if not k or not f.get("verified"):
            continue
        e = out.setdefault(k, {"publishers": set(), "facts": []})
        e["publishers"].add(textmatch.normalize(f["publisher"]))
        e["facts"].append(f["id"])
    return {k: {"publishers": sorted(v["publishers"]), "facts": v["facts"], "n": len(v["publishers"]),
                "triangulated": len(v["publishers"]) >= 2} for k, v in out.items()}


def summary(facts):
    grades = {g: 0 for g in GRADES}
    for f in facts:
        grades[effective_grade(f)] += 1
    pending = sum(1 for f in facts if f.get("verify_status") == "pending")
    failed = sum(1 for f in facts if f.get("verify_status") not in ("ok", "pending"))
    return {"total": len(facts), "by_effective_grade": grades, "pending": pending, "failed": failed}
