#!/usr/bin/env python3
"""ik: the command line of the idea evaluator. Standard library only.

    ik.py new "<private title>" [--root ideas]       create ideas/<slug>/ with a random codename
    ik.py lint IDEA                                  check idea.json (neutral, complete) and claims.jsonl
    ik.py prereg IDEA [--mode quick|full] [--new-run] [--rubric FILE]
    ik.py evidence add IDEA < facts.json             add facts (one object or a list); they start unverified
    ik.py evidence verify IDEA [--ids F001,F002] [--html-dir DIR] [--recheck]
    ik.py evidence list IDEA
    ik.py baserates list [--unverified] | show ID | verify [--ids ...] [--html-dir DIR]
    ik.py econ IDEA [--runs N] [--seed S]            Monte Carlo economics -> economics.json, economics.md
    ik.py brief IDEA                                 blind brief for the judge -> judge/brief.md
    ik.py verdict IDEA                               computed verdict -> verdict.json, verdict.md
    ik.py status IDEA                                what is done and what comes next

IDEA is the idea folder, e.g. ideas/my-app. Exit code 2 means a problem to fix,
printed on stderr; nothing is ever guessed to get past it.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ideakit import baserates, economics, evidence, intake, prereg, scoring, verdict  # noqa: E402
from ideakit.common import Idea, IdeaError, read_json, read_jsonl  # noqa: E402


def _ids(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def status(d):
    idea = Idea(d)
    idea.require_dir()
    steps = [
        ("idea.json (scheda cieca)", os.path.exists(idea.idea), "write idea.json, then: ik.py lint"),
        ("prereg.json (rubrica congelata)", os.path.exists(idea.prereg), "ik.py prereg IDEA --mode quick"),
        ("evidence.jsonl (fatti)", bool(read_jsonl(idea.evidence)), "research, then: ik.py evidence add / verify"),
        ("assumptions.json (input economici)", os.path.exists(idea.assumptions), "write assumptions.json"),
        ("economics.json", os.path.exists(idea.economics), "ik.py econ IDEA"),
        ("judge/scores.json (giudizio cieco)", os.path.exists(idea.scores), "ik.py brief IDEA, then run the judge"),
        ("verdict.json", os.path.exists(idea.verdict), "ik.py verdict IDEA"),
    ]
    nxt = None
    for name, done, how in steps:
        print("%s %s" % ("[x]" if done else "[ ]", name))
        if not done and nxt is None:
            nxt = how
    facts = read_jsonl(idea.evidence)
    if facts:
        s = evidence.summary(facts)
        print("facts: %d (A %d, B %d, C %d, D %d), pending %d, failed %d" % (
            s["total"], s["by_effective_grade"]["A"], s["by_effective_grade"]["B"], s["by_effective_grade"]["C"],
            s["by_effective_grade"]["D"], s["pending"], s["failed"]))
    print("next: %s" % (nxt or "done; read verdict.md"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="idea evaluator", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("title")
    p.add_argument("--root", default="ideas")
    sub.add_parser("lint").add_argument("idea")
    p = sub.add_parser("prereg")
    p.add_argument("idea")
    p.add_argument("--mode", default="quick", choices=prereg.MODES)
    p.add_argument("--rubric")
    p.add_argument("--new-run", action="store_true")
    p = sub.add_parser("evidence")
    p.add_argument("action", choices=["add", "verify", "list"])
    p.add_argument("idea")
    p.add_argument("--ids")
    p.add_argument("--html-dir")
    p.add_argument("--recheck", action="store_true")
    p = sub.add_parser("baserates")
    p.add_argument("action", choices=["list", "show", "verify"])
    p.add_argument("id", nargs="?")
    p.add_argument("--ids")
    p.add_argument("--html-dir")
    p.add_argument("--unverified", action="store_true")
    p = sub.add_parser("econ")
    p.add_argument("idea")
    p.add_argument("--runs", type=int)
    p.add_argument("--seed", type=int)
    sub.add_parser("brief").add_argument("idea")
    sub.add_parser("verdict").add_argument("idea")
    sub.add_parser("status").add_argument("idea")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            d, code = intake.new(a.root, a.title)
            print("created %s (codename %s). Next: write %s/idea.json and claims.jsonl" % (d, code, d))
        elif a.cmd == "lint":
            errs = intake.lint(a.idea)
            for e in errs:
                print("- %s" % e)
            print("ok" if not errs else "%d problems" % len(errs))
            return 1 if errs else 0
        elif a.cmd == "prereg":
            errs = intake.lint(a.idea)
            if errs:
                raise IdeaError("fix idea.json first (ik.py lint): %s" % errs[0])
            r = prereg.freeze(a.idea, a.mode, a.rubric, a.new_run)
            print("frozen %s v%s for %s (%s mode), sha256 %s..." % (
                r["rubric_id"], r["rubric_version"], r["market"], r["mode"], r["rubric_sha256"][:12]))
        elif a.cmd == "evidence":
            idea = Idea(a.idea)
            idea.require_dir()
            if a.action == "add":
                try:
                    objs = json.loads(sys.stdin.read())
                except json.JSONDecodeError as e:
                    raise IdeaError("stdin is not valid JSON: %s" % e)
                print("added %s (unverified until: ik.py evidence verify)" % ", ".join(evidence.add(idea, objs)))
            elif a.action == "verify":
                for fid, st in evidence.verify(idea, _ids(a.ids), a.html_dir, a.recheck):
                    print("%s: %s" % (fid, st))
                s = evidence.summary(evidence.load(idea))
                print("verified %d of %d" % (s["total"] - s["pending"] - s["failed"], s["total"]))
            else:
                for f in evidence.load(idea):
                    print("%s [%s%s] %s (%s) %s" % (f["id"], evidence.effective_grade(f),
                                                   "" if f.get("verified") else ", unverified",
                                                   f["claim"], f["publisher"], f.get("verify_status", "")))
        elif a.cmd == "baserates":
            if a.action == "list":
                for r in baserates.load()["rates"]:
                    if a.unverified and r.get("verified"):
                        continue
                    print("%-32s %s %s  [%s%s] %s" % (r["id"], r["value"], r["unit"], baserates.grade(r),
                                                     "" if r.get("verified") else ", unverified", r["source"]))
            elif a.action == "show":
                if not a.id:
                    raise IdeaError("give a base rate id")
                print(json.dumps(baserates.get(a.id), indent=1, ensure_ascii=False))
            else:
                for rid, st in baserates.verify(_ids(a.ids), a.html_dir):
                    print("%s: %s" % (rid, st))
        elif a.cmd == "econ":
            r = economics.run(a.idea, a.runs, a.seed)
            d = r["distribution"]
            print("contribution P50 %.2f, LTV:CAC P50 %s, revenue month 24 P50 %.0f, P(break-even) %.0f%%. Wrote economics.md"
                  % (d["contribution"]["p50"], "inf" if d["ltv_cac"]["p50"] == float("inf") else "%.1f" % d["ltv_cac"]["p50"],
                     d["revenue_m24"]["p50"], r["p_breakeven_in_horizon"] * 100))
            if r["adjustments"]:
                print("%d weak inputs clamped to their base rate (see economics.md)" % len(r["adjustments"]))
        elif a.cmd == "brief":
            print("wrote %s. Give it to a judge that has not seen the founder's notes." % scoring.brief(a.idea))
        elif a.cmd == "verdict":
            r = verdict.compute(a.idea)
            if r["verdict"] == "INCOMPLETE":
                print("INCOMPLETE: missing %s" % "; ".join(r["missing"]))
            else:
                print("%s · score %.0f · confidence %s · wrote verdict.md" % (r["verdict"], r["score"], r["confidence"]))
        elif a.cmd == "status":
            status(a.idea)
    except IdeaError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
