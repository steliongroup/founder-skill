"""Turning web pages into comparable text, and finding quotes and numbers in it.

This is what makes "a number counts only if it is on the page" checkable by code.
"""

import difflib
import html
import re
import unicodedata

_DROP = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1\s*>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
# curly quotes, guillemets, en/em dashes and minus sign, written as code points
_QUOTES = {chr(0x2018): "'", chr(0x2019): "'", chr(0x201C): '"', chr(0x201D): '"', chr(0x00AB): '"',
           chr(0x00BB): '"', chr(0x2013): "-", chr(0x2014): "-", chr(0x2212): "-"}

FUZZY_MIN = 0.8  # share of the quote that must appear as one contiguous run


def normalize(s):
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in _QUOTES.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s.lower()).strip()


def html_to_text(raw):
    raw = _DROP.sub(" ", raw)
    raw = _TAG.sub(" ", raw)
    return normalize(html.unescape(raw))


def find_quote(quote, text):
    """'exact', 'fuzzy' or None. text must already be normalized.

    A fuzzy match (typography, a contraction) is accepted only if every number in
    the quote also appears in the matching stretch of the page, so an edited
    figure inside an otherwise copied sentence never passes.
    """
    q = normalize(quote)
    if not q:
        return None
    if q in text:
        return "exact"
    sm = difflib.SequenceMatcher(None, q, text, autojunk=False)
    m = sm.find_longest_match(0, len(q), 0, len(text))
    if m.size < FUZZY_MIN * len(q):
        return None
    start = max(0, m.b - m.a - 20)
    window = text[start:m.b + (len(q) - m.a) + 20]
    for v in numbers_in(q):
        if not contains_number(window, v):
            return None
    return "fuzzy"


_NUM = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(%|k|mln|mld|bn|million|millions|billion|billions|mila|milioni|miliardi|m|b)?(?!\w)",
    re.I)
_MULT = {"k": 1e3, "mila": 1e3, "m": 1e6, "mln": 1e6, "million": 1e6, "millions": 1e6, "milioni": 1e6,
         "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9, "miliardi": 1e9, "mld": 1e9}


def _readings(token):
    """Every value a written number could mean (US or EU separators)."""
    out = set()
    has_c, has_d = "," in token, "." in token
    if has_c and has_d:
        dec = "," if token.rfind(",") > token.rfind(".") else "."
        th = "." if dec == "," else ","
        out.add(float(token.replace(th, "").replace(dec, ".")))
        return out
    sep = "," if has_c else ("." if has_d else None)
    if sep is None:
        out.add(float(token))
        return out
    parts = token.split(sep)
    if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
        if all(len(p) == 3 for p in parts[1:]):
            out.add(float("".join(parts)))  # thousands separator
    if len(parts) == 2:
        out.add(float(parts[0] + "." + parts[1]))  # decimal separator
    return out


def numbers_in(text):
    vals = set()
    for m in _NUM.finditer(text or ""):
        base = _readings(m.group(1))
        suffix = (m.group(2) or "").lower()
        for v in base:
            vals.add(v)
            if suffix == "%":
                vals.add(v / 100.0)
            elif suffix in _MULT:
                vals.add(v * _MULT[suffix])
    return vals


def contains_number(text, value, rel=1e-6):
    if value is None:
        return True
    value = float(value)
    for v in numbers_in(text):
        if abs(v - value) <= rel * max(1.0, abs(value)):
            return True
    return False
