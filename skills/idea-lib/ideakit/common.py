"""Shared helpers: paths, JSON files, ids, hashes. Standard library only."""

import datetime
import hashlib
import json
import os

PKG = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(PKG), "data")

GRADES = ["A", "B", "C", "D"]
STRONG = ("A", "B")


class IdeaError(Exception):
    """A problem the user or the agent must fix. Printed, never guessed around."""


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is not None:
            return default
        raise IdeaError("missing file: %s" % path)
    except json.JSONDecodeError as e:
        raise IdeaError("%s is not valid JSON: %s" % (path, e))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise IdeaError("%s line %d is not valid JSON: %s" % (path, n, e))
    except FileNotFoundError:
        pass
    return rows


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def canonical_sha256(obj):
    """Hash of a JSON value that does not depend on key order or whitespace."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def lower_grade(g):
    i = GRADES.index(g)
    return GRADES[min(i + 1, len(GRADES) - 1)]


class Idea:
    """The files of one idea folder. Nothing here decides anything."""

    def __init__(self, d):
        self.dir = d

    def p(self, *parts):
        return os.path.join(self.dir, *parts)

    @property
    def idea(self):
        return self.p("idea.json")

    @property
    def claims(self):
        return self.p("claims.jsonl")

    @property
    def evidence(self):
        return self.p("evidence.jsonl")

    @property
    def prereg(self):
        return self.p("prereg.json")

    @property
    def assumptions(self):
        return self.p("assumptions.json")

    @property
    def economics(self):
        return self.p("economics.json")

    @property
    def scores(self):
        return self.p("judge", "scores.json")

    @property
    def brief(self):
        return self.p("judge", "brief.md")

    @property
    def verdict(self):
        return self.p("verdict.json")

    def require_dir(self):
        if not os.path.isdir(self.dir):
            raise IdeaError("no idea folder at %s (create it with: ik.py new)" % self.dir)


def data_file(name):
    return os.path.join(DATA, name)
