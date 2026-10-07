"""Reference-class priors (base rates) with their sources."""

import os

from . import textmatch
from .common import IdeaError, data_file, now_iso, read_json, write_json
from .evidence import fetch_url

UNVERIFIED_GRADE = "C"  # published benchmark reported via research, not yet matched on its page


def path():
    return os.environ.get("IDEAKIT_BASERATES") or data_file("baserates.json")


def load():
    return read_json(path())


def get(rate_id, table=None):
    table = table or load()
    for r in table["rates"]:
        if r["id"] == rate_id:
            return r
    raise IdeaError("no base rate %r (see: ik.py baserates list)" % rate_id)


def grade(rate):
    return rate.get("declared_grade", "C") if rate.get("verified") else UNVERIFIED_GRADE


def verify(ids=None, html_dir=None, fetch=fetch_url):
    """Mark a base rate verified when its match_text and keywords are on its page."""
    table = load()
    done = []
    for r in table["rates"]:
        if ids and r["id"] not in ids:
            continue
        r["verified_at"] = now_iso()
        try:
            local = os.path.join(html_dir, r["id"] + ".html") if html_dir else None
            if local and os.path.exists(local):
                with open(local, encoding="utf-8", errors="replace") as fh:
                    text = textmatch.html_to_text(fh.read())
            else:
                text = textmatch.html_to_text(fetch(r["url"]))
        except Exception as e:  # network errors of every kind end up as "unreachable"
            r.update(verified=False, verify_status="unreachable: %s" % str(e)[:160])
            done.append((r["id"], r["verify_status"]))
            continue
        ok_num = textmatch.normalize(r["match_text"]) in text
        missing = [k for k in r.get("keywords", []) if textmatch.normalize(k) not in text]
        if ok_num and not missing:
            r.update(verified=True, verify_status="ok")
        else:
            why = []
            if not ok_num:
                why.append("%r not on page" % r["match_text"])
            if missing:
                why.append("keywords missing: %s" % ", ".join(missing))
            r.update(verified=False, verify_status="; ".join(why))
        done.append((r["id"], r["verify_status"]))
    write_json(path(), table)
    return done
