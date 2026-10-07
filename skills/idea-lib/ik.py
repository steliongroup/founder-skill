#!/usr/bin/env python3
"""ik: the command line of the idea evaluator. Standard library only.

    ik.py new "<private title>" [--root ideas]       create ideas/<slug>/ with a random codename
    ik.py lint IDEA                                  check idea.json (neutral, complete) and claims.jsonl
    ik.py prereg IDEA [--mode quick|full] [--new-run] [--rubric FILE]
    ik.py evidence add IDEA < facts.json             add facts (one object or a list); they start unverified
    ik.py evidence verify IDEA [--ids F001,F002] [--html-dir DIR] [--recheck]
    ik.py evidence list IDEA
    ik.py baserates list [--unverified] | show ID | verify [--ids ...] [--html-dir DIR]
    ik.py collect SOURCE IDEA [options]              free data sources -> candidates / voice (ik.py collect --list)
    ik.py candidates list IDEA [--pending]           numbers the collectors found
    ik.py candidates promote IDEA K001,K002 [--criteria problem,demand]
    ik.py candidates reject IDEA K003 --reason "..." not about this idea (reason is kept)
    ik.py voice list IDEA [--max-rating 3] [--source S]   verbatim buyer texts
    ik.py voice themes IDEA [--max-rating 3]         count themes from data/voice-tags.json -> candidates
    ik.py voice promote IDEA V001,V002 [--criteria problem]
    ik.py market IDEA                                bottom-up SAM from market.json -> market.md
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

from ideakit import baserates, candidates, collect, economics, evidence, intake, market, prereg, scoring, verdict, voice  # noqa: E402
from ideakit.common import Idea, IdeaError, read_json, read_jsonl  # noqa: E402


def _ids(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _collect(idea, a):
    src = a.source

    def need(*names):
        for n in names:
            if not getattr(a, n.replace("-", "_")):
                raise IdeaError("collect %s needs --%s" % (src, n))
    if src == "autocomplete":
        need("q")
        return collect.autocomplete(idea, a.q, a.lang, a.country)
    if src == "wikipedia":
        need("article")
        return collect.wikipedia(idea, a.article, a.lang, max(a.months, 24))
    if src == "trends":
        need("keywords")
        return collect.trends(idea, _ids(a.keywords), a.geo, a.timeframe)
    if src == "itunes":
        need("q")
        return collect.itunes(idea, a.q, a.country)
    if src == "appreviews":
        need("app-id")
        return collect.appreviews(idea, a.app_id, a.country, a.pages)
    if src == "gplay":
        need("q")
        return collect.gplay(idea, a.q, a.country, a.lang, review_apps=a.review_apps)
    if src == "hn":
        need("q")
        return collect.hn(idea, a.q, a.months)
    if src == "github":
        need("q")
        return collect.github(idea, a.q)
    if src == "stackexchange":
        need("q")
        return collect.stackexchange(idea, a.q, a.site)
    if src == "domain":
        need("domain")
        return collect.domain(idea, a.domain)
    if src == "worldbank":
        need("countries", "indicator")
        return collect.worldbank(idea, _ids(a.countries), a.indicator)
    if src == "eurostat":
        need("dataset")
        filters = {}
        for f in a.filter:
            k, _, v = f.partition("=")
            if not k or not v:
                raise IdeaError("--filter must look like dim=code1,code2")
            filters[k.strip()] = _ids(v)
        if a.countries:
            filters["geo"] = _ids(a.countries)
        return collect.eurostat(idea, a.dataset, filters, a.unit)
    if src == "youtube":
        need("q")
        return collect.youtube(idea, a.q, a.months)
    raise IdeaError("unknown source %s" % src)


def status(d):
    idea = Idea(d)
    idea.require_dir()
    steps = [
        ("idea.json (scheda cieca)", os.path.exists(idea.idea), "write idea.json, then: ik.py lint"),
        ("prereg.json (rubrica congelata)", os.path.exists(idea.prereg), "ik.py prereg IDEA --mode quick"),
        ("evidence.jsonl (fatti)", bool(read_jsonl(idea.evidence)), "research, then: ik.py evidence add / verify"),
        ("data/ (raccolta automatica, facoltativa)", os.path.isdir(idea.p("data")), "ik.py collect --list"),
        ("market.json (mercato dal basso, facoltativo in quick)", os.path.exists(idea.p("market-result.json")),
         "write market.json, then: ik.py market IDEA"),
        ("assumptions.json (input economici)", os.path.exists(idea.assumptions), "write assumptions.json"),
        ("economics.json", os.path.exists(idea.economics), "ik.py econ IDEA"),
        ("judge/scores.json (giudizio cieco)", os.path.exists(idea.scores), "ik.py brief IDEA, then run the judge"),
        ("verdict.json", os.path.exists(idea.verdict), "ik.py verdict IDEA"),
    ]
    nxt = None
    for name, done, how in steps:
        optional = "facoltativ" in name
        print("%s %s" % ("[x]" if done else ("[-]" if optional else "[ ]"), name))
        if not done and not optional and nxt is None:
            nxt = how
    facts = read_jsonl(idea.evidence)
    if facts:
        s = evidence.summary(facts)
        print("facts: %d (A %d, B %d, C %d, D %d), pending %d, failed %d" % (
            s["total"], s["by_effective_grade"]["A"], s["by_effective_grade"]["B"], s["by_effective_grade"]["C"],
            s["by_effective_grade"]["D"], s["pending"], s["failed"]))
    c = candidates.summary(idea)
    if sum(c.values()):
        print("candidates: %d pending, %d promoted, %d rejected" % (c["pending"], c["promoted"], c["rejected"]))
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
    p = sub.add_parser("collect")
    p.add_argument("source", nargs="?", choices=sorted(collect.SOURCES))
    p.add_argument("idea", nargs="?")
    p.add_argument("--list", action="store_true", help="list the sources")
    p.add_argument("--q", help="search term / query")
    p.add_argument("--country", default="us")
    p.add_argument("--lang", default="en")
    p.add_argument("--geo", default="", help="trends: ISO country, empty = worldwide")
    p.add_argument("--keywords", help="trends: up to 5, comma separated")
    p.add_argument("--timeframe", default="today 5-y")
    p.add_argument("--article", help="wikipedia: exact article title")
    p.add_argument("--app-id", help="appreviews: App Store numeric id")
    p.add_argument("--pages", type=int, default=2)
    p.add_argument("--review-apps", type=int, default=0, help="gplay: fetch 1-3 star reviews of the first N apps")
    p.add_argument("--domain")
    p.add_argument("--countries", help="worldbank/eurostat: ISO codes, comma separated")
    p.add_argument("--indicator", help="worldbank: code or preset (%s)" % ", ".join(collect.WB_PRESETS))
    p.add_argument("--dataset", help="eurostat dataset code")
    p.add_argument("--filter", action="append", default=[], help="eurostat: dim=code1,code2 (repeatable)")
    p.add_argument("--unit", default="", help="eurostat: unit label for the values")
    p.add_argument("--site", default="stackoverflow")
    p.add_argument("--months", type=int, default=24)
    p = sub.add_parser("candidates")
    p.add_argument("action", choices=["list", "promote", "reject"])
    p.add_argument("idea")
    p.add_argument("ids", nargs="?")
    p.add_argument("--pending", action="store_true")
    p.add_argument("--reason")
    p.add_argument("--criteria")
    p = sub.add_parser("voice")
    p.add_argument("action", choices=["list", "themes", "promote"])
    p.add_argument("idea")
    p.add_argument("ids", nargs="?")
    p.add_argument("--max-rating", type=int)
    p.add_argument("--source")
    p.add_argument("--criteria")
    sub.add_parser("market").add_argument("idea")
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
        elif a.cmd == "collect":
            if a.list or not a.source:
                for k, v in sorted(collect.SOURCES.items()):
                    print("%-14s %s" % (k, v))
                return 0
            if not a.idea:
                raise IdeaError("give the idea folder")
            idea = Idea(a.idea)
            idea.require_dir()
            res = _collect(idea, a)
            if isinstance(res, dict):
                for k, v in res.items():
                    print("%s: %s" % (k, ", ".join(v) or "(none)"))
            elif isinstance(res, int):
                print("%d new voice items. Next: ik.py voice list %s" % (res, a.idea))
            else:
                print("%d new candidates%s. Next: ik.py candidates list %s --pending" % (
                    len(res), (" (%s)" % ", ".join(res)) if res else "", a.idea))
        elif a.cmd == "candidates":
            idea = Idea(a.idea)
            idea.require_dir()
            if a.action == "list":
                for c in candidates.load(idea):
                    if a.pending and c["status"] != "pending":
                        continue
                    print("%s [%s, %s] %s = %s %s  <%s>%s" % (
                        c["id"], c["status"], evidence.GRADE_BY_TYPE[c["source_type"]], c["claim"], c["value"],
                        c.get("unit", ""), c["url"], (" -> %s" % c["fact_id"]) if c.get("fact_id") else
                        ((" (%s)" % c["reason"]) if c.get("reason") else "")))
            else:
                ids = _ids(a.ids)
                if not ids:
                    raise IdeaError("give candidate ids, e.g. K001,K002")
                done = candidates.review(idea, promote=ids if a.action == "promote" else None,
                                         reject=ids if a.action == "reject" else None, reason=a.reason,
                                         criteria=_ids(a.criteria))
                for cid, res in done:
                    print("%s -> %s" % (cid, res))
        elif a.cmd == "voice":
            idea = Idea(a.idea)
            idea.require_dir()
            if a.action == "list":
                for v in voice.listing(idea, a.max_rating, a.source):
                    print("%s [%s%s] %s: %s" % (v["id"], v["source"], "" if v.get("rating") is None else ", %d*" % v["rating"],
                                               v.get("about") or "", v["text"][:300].replace("\n", " ")))
            elif a.action == "themes":
                new, snap = voice.themes(idea, 3 if a.max_rating is None else a.max_rating)
                for k, n in sorted(snap["counts"].items(), key=lambda kv: -kv[1]):
                    print("%-24s %d of %d" % (k, n, snap["total"]))
                print("%d new candidates (grade C: agent-tagged counts)" % len(new))
            else:
                ids = _ids(a.ids)
                if not ids:
                    raise IdeaError("give voice ids, e.g. V001,V007")
                for vid, fid in voice.promote(idea, ids, _ids(a.criteria)):
                    print("%s -> %s" % (vid, fid))
        elif a.cmd == "market":
            r = market.run(a.idea)
            rs = r.get("required_share")
            print("SAM P50 %.0f %s%s. Wrote market.md" % (r["sam"]["p50"], r["currency"],
                  (", goal needs %.2f%% of it (P50)" % (rs["p50"] * 100)) if rs and rs["p50"] is not None else ""))
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
