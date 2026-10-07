"""Candidates: data the collectors found, waiting for a relevance decision.

Code writes every candidate's value. The agent only decides, for each one,
whether it is about this idea: promote it (it becomes a fact, unchanged) or
reject it with a reason. Unfavourable but relevant data must be promoted;
the rejection reasons are kept and counted in the verdict, so cherry-picking
leaves a trace.
"""

from . import evidence
from .common import IdeaError, Idea, now_iso, read_jsonl, write_jsonl

STATUSES = ("pending", "promoted", "rejected")


def path(idea):
    return idea.p("data", "candidates.jsonl")


def load(idea):
    return read_jsonl(path(idea))


def add(idea, cands):
    """Append new candidates; duplicates (same source, claim, value, url) are skipped. Returns new ids."""
    rows = load(idea)
    seen = {(r["source"], r["claim"], str(r.get("value")), r.get("url")) for r in rows}
    n = max([int(r["id"][1:]) for r in rows] or [0])
    new = []
    for c in cands:
        key = (c["source"], c["claim"], str(c.get("value")), c.get("url"))
        if key in seen:
            continue
        seen.add(key)
        n += 1
        row = dict(c, id="K%03d" % n, status="pending", found_at=now_iso())
        rows.append(row)
        new.append(row["id"])
    write_jsonl(path(idea), rows)
    return new


def review(idea, promote=None, reject=None, reason=None, criteria=None):
    rows = load(idea)
    by_id = {r["id"]: r for r in rows}
    promote, reject = promote or [], reject or []
    for cid in promote + reject:
        if cid not in by_id:
            raise IdeaError("no candidate %s" % cid)
        if by_id[cid]["status"] != "pending":
            raise IdeaError("%s is already %s" % (cid, by_id[cid]["status"]))
    if reject and not (reason or "").strip():
        raise IdeaError("rejecting needs --reason (why the data is not about this idea)")
    done = []
    for cid in promote:
        fid = evidence.add_collected(idea, by_id[cid], criteria)
        by_id[cid].update(status="promoted", fact_id=fid, decided_at=now_iso())
        done.append((cid, fid))
    for cid in reject:
        by_id[cid].update(status="rejected", reason=reason.strip(), decided_at=now_iso())
        done.append((cid, "rejected"))
    write_jsonl(path(idea), rows)
    return done


def summary(idea):
    rows = load(idea)
    out = {s: 0 for s in STATUSES}
    for r in rows:
        out[r["status"]] += 1
    return out
