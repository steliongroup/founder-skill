"""The blind fact sheet (idea.json) and the founder's claims (claims.jsonl).

idea.json is the only description of the idea the judges ever see. It must be
neutral, third person, and free of hype. The founder's own assertions live in
claims.jsonl as hypotheses (grade D) until evidence confirms them.
"""

import os
import re
import secrets

from .common import IdeaError, Idea, now_iso, read_json, read_jsonl, write_json

MARKETS = ("b2c", "b2b", "b2b2c")
PLATFORMS = ("desktop", "mobile", "tablet", "web", "api", "other")
REVENUE_MODELS = ("subscription", "freemium", "one_time", "usage", "ads", "marketplace", "service")
PERIODS = ("month", "year", "one_time")
STAGES = ("raw", "researched")
CLAIM_TYPES = ("problem", "market", "customer", "competitor", "traction", "price", "cost", "channel", "other")
TEXT_FIELDS = ("one_liner", "problem", "solution")

# Words that carry enthusiasm or ownership, not information (English and Italian).
HYPE = [
    r"revolution\w*", r"rivoluzion\w*", r"game[- ]?chang\w*", r"disrupt\w*", r"dirompent\w*",
    r"unique", r"best", r"migliore", r"miglior", r"incredib\w*", r"amazing", r"straordinari\w*",
    r"perfect\w*", r"perfett\w*", r"huge", r"enorm\w*", r"massive", r"everyone", r"everybody",
    r"nobody else", r"nessun altro", r"first ever", r"innovativ\w*",
    r"genius", r"geniale", r"brilliant", r"must[- ]have", r"killer", r"obviously", r"ovviamente", r"sicuramente", r"certainly",
    r"guaranteed", r"garantit\w*",
]
FIRST_PERSON = [r"\bmy\b", r"\bme\b", r"\bwe\b", r"\bour\b", r"\bio\b", r"\bmio\b", r"\bmia\b",
                r"\bmiei\b", r"\bmie\b", r"\bnoi\b", r"\bnostr[oaie]\b"]
_HYPE_RE = re.compile(r"\b(" + "|".join(HYPE) + r")\b", re.I)
_FP_RE = re.compile("|".join(FIRST_PERSON), re.I)
# English "I" only when it is clearly the pronoun: Italian uses "i" and "I" as an article.
_I_RE = re.compile(r"\bI(?:'(?:m|ve|ll|d)\b| (?:am|have|want|think|will|built|believe|plan|need|know|can|was)\b)")


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:48] or "idea"


def new(root, title):
    """Create ideas/<slug>/ with a random codename. The title stays private."""
    d = os.path.join(root, slugify(title))
    if os.path.exists(d):
        raise IdeaError("%s already exists" % d)
    os.makedirs(os.path.join(d, "input"))
    os.makedirs(os.path.join(d, "judge"))
    codename = "IDEA-%s" % secrets.token_hex(2).upper()
    write_json(os.path.join(d, "input", "private.json"),
               {"title": title, "codename": codename, "created_at": now_iso(),
                "note": "Private. Never passed to judges. Put your notes and documents in this folder."})
    return d, codename


def lint_text(text):
    """Problems in one text field: hype words and first person."""
    probs = []
    for m in _HYPE_RE.finditer(text or ""):
        probs.append("hype word %r" % m.group(0))
    for m in list(_FP_RE.finditer(text or "")) + list(_I_RE.finditer(text or "")):
        probs.append("first person %r" % m.group(0))
    return probs


def _need(cond, msg, errs):
    if not cond:
        errs.append(msg)


def validate_idea(obj):
    errs = []
    for k in ("codename", "one_liner", "problem", "solution", "target_segments", "archetype",
              "price_hypothesis", "current_alternatives", "stage"):
        _need(k in obj and obj[k] not in ("", None, []), "idea.json needs %r" % k, errs)
    if errs:
        return errs
    a = obj["archetype"]
    _need(a.get("market") in MARKETS, "archetype.market must be one of %s" % ", ".join(MARKETS), errs)
    plats = a.get("platform") or []
    _need(isinstance(plats, list) and plats and all(p in PLATFORMS for p in plats),
          "archetype.platform must be a list from %s" % ", ".join(PLATFORMS), errs)
    geo = a.get("geo") or []
    _need(isinstance(geo, list) and geo, "archetype.geo must be a list of ISO country codes or ['global']", errs)
    _need(a.get("revenue_model") in REVENUE_MODELS,
          "archetype.revenue_model must be one of %s" % ", ".join(REVENUE_MODELS), errs)
    p = obj["price_hypothesis"]
    try:
        _need(float(p.get("amount")) >= 0, "price_hypothesis.amount must be >= 0", errs)
    except (TypeError, ValueError):
        errs.append("price_hypothesis.amount must be a number")
    _need(p.get("period") in PERIODS, "price_hypothesis.period must be one of %s" % ", ".join(PERIODS), errs)
    _need(bool(p.get("currency")), "price_hypothesis.currency is required", errs)
    _need(obj["stage"] in STAGES, "stage must be one of %s" % ", ".join(STAGES), errs)
    for s in obj["target_segments"]:
        _need(isinstance(s, dict) and s.get("name") and s.get("description"),
              "every target segment needs a name and a description", errs)
    texts = [(k, obj.get(k, "")) for k in TEXT_FIELDS]
    texts += [("target_segments[%d]" % i, s.get("description", "")) for i, s in enumerate(obj["target_segments"])
              if isinstance(s, dict)]
    for field, text in texts:
        for prob in lint_text(text):
            errs.append("%s: %s (the sheet must be neutral, third person)" % (field, prob))
    return errs


def validate_claims(rows):
    errs = []
    seen = set()
    for i, c in enumerate(rows, 1):
        cid = c.get("id")
        if not re.match(r"^C\d{3,}$", str(cid)):
            errs.append("claim %d: id must look like C001" % i)
        if cid in seen:
            errs.append("claim %s: duplicate id" % cid)
        seen.add(cid)
        if not str(c.get("text", "")).strip():
            errs.append("claim %s: empty text" % cid)
        if c.get("type") not in CLAIM_TYPES:
            errs.append("claim %s: type must be one of %s" % (cid, ", ".join(CLAIM_TYPES)))
        if c.get("grade", "D") != "D":
            errs.append("claim %s: founder claims are always grade D (evidence goes in evidence.jsonl)" % cid)
    return errs


def lint(d):
    idea = Idea(d)
    idea.require_dir()
    errs = validate_idea(read_json(idea.idea))
    private = read_json(idea.p("input", "private.json"), default={})
    sheet = read_json(idea.idea)
    if private.get("codename") and sheet.get("codename") != private["codename"]:
        errs.append("idea.json codename must be %s" % private["codename"])
    title = (private.get("title") or "").strip().lower()
    if title and len(title) > 3:
        blob = " ".join(str(sheet.get(k, "")) for k in TEXT_FIELDS).lower()
        if title in blob:
            errs.append("the private title %r appears in the sheet: use the codename" % private["title"])
    errs += validate_claims(read_jsonl(idea.claims))
    return errs
