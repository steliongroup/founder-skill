"""The voice corpus: verbatim text from buyers (reviews, comments, questions).

Code collects the text; the agent tags items with themes; code counts the
themes. Individual items can be promoted to facts, quoted exactly as collected.
"""

from . import candidates, evidence, fetch
from .common import IdeaError, Idea, read_json, read_jsonl, write_json, write_jsonl


def path(idea):
    return idea.p("data", "voice.jsonl")


def load(idea):
    return read_jsonl(path(idea))


def listing(idea, max_rating=None, source=None):
    out = []
    for v in load(idea):
        if source and v["source"] != source:
            continue
        if max_rating is not None and v.get("rating") is not None and v["rating"] > max_rating:
            continue
        out.append(v)
    return out


def promote(idea, ids, criteria=None):
    """Turn voice items into facts. The quote is the collected text, unchanged."""
    rows = load(idea)
    by_id = {v["id"]: v for v in rows}
    done = []
    for vid in ids:
        v = by_id.get(vid)
        if not v:
            raise IdeaError("no voice item %s" % vid)
        if v.get("fact_id"):
            raise IdeaError("%s is already fact %s" % (vid, v["fact_id"]))
        stars = "%d-star " % v["rating"] if v.get("rating") is not None else ""
        cand = {"id": vid, "source": v["source"], "source_type": v["source_type"], "publisher": v["publisher"],
                "claim": "A %sreview or comment (%s) says: %s" % (stars, v.get("about") or v["source"], v["text"][:140]),
                "value": None, "unit": "", "url": v["url"], "quote": v["text"], "date": v.get("date") or None,
                "raw_file": v["raw_file"], "raw_sha256": v["raw_sha256"], "query": v.get("about"),
                "claim_key": None}
        fid = evidence.add_collected(idea, cand, criteria or ["problem"])
        v.update(fact_id=fid, status="promoted")
        done.append((vid, fid))
    write_jsonl(path(idea), rows)
    return done


def tags_path(idea):
    return idea.p("data", "voice-tags.json")


def themes(idea, max_rating=3):
    """Count themes from data/voice-tags.json and add one candidate per theme.

    voice-tags.json: {"themes": {"key": "description"}, "tags": {"V001": ["key", ...]}}
    Only items with rating <= max_rating (or no rating) are counted.
    """
    tagfile = read_json(tags_path(idea))
    themes_ = tagfile.get("themes") or {}
    tags = tagfile.get("tags") or {}
    items = {v["id"]: v for v in listing(idea, max_rating=max_rating)}
    unknown = sorted({t for ts in tags.values() for t in ts} - set(themes_))
    if unknown:
        raise IdeaError("tags use themes not defined in 'themes': %s" % ", ".join(unknown))
    missing = sorted(set(tags) - set(load_ids(idea)))
    if missing:
        raise IdeaError("tags refer to voice items that do not exist: %s" % ", ".join(missing[:10]))
    untagged = [i for i in items if i not in tags]
    if untagged:
        raise IdeaError("%d items are not tagged (tag every item, use [] for none): %s" % (
            len(untagged), ", ".join(untagged[:10])))
    total = len(items)
    counts = {k: [i for i in items if k in tags.get(i, [])] for k in themes_}
    snapshot = {"themes": themes_, "tags": {i: tags[i] for i in items}, "counts": {k: len(v) for k, v in counts.items()},
                "total": total, "max_rating": max_rating}
    raw, sha = fetch.store_raw(idea, "voice-themes", "themes", snapshot)
    sources = sorted({items[i]["source"] for i in items})
    out = []
    for k, ids in sorted(counts.items(), key=lambda kv: -len(kv[1])):
        if not ids:
            continue
        example = items[ids[0]]
        out.append({"source": "voice-themes", "source_type": "aggregator",
                    "claim": "%d of %d collected buyer texts (%s; rating <= %s or unrated) mention: %s" % (
                        len(ids), total, ", ".join(sources), max_rating, themes_[k]),
                    "value": len(ids), "unit": "of %d texts" % total, "url": example["url"],
                    "quote": "theme %s tagged on %s" % (k, ", ".join(ids[:15])), "publisher": "voice corpus (agent-tagged)",
                    "raw_file": raw, "raw_sha256": sha, "query": k, "claim_key": "voice_theme:%s" % k,
                    "date": None, "criteria": ["problem", "competition"], "sample_size": total})
    write_json(idea.p("data", "voice-themes.json"), snapshot)
    return candidates.add(idea, out), snapshot


def load_ids(idea):
    return [v["id"] for v in load(idea)]
