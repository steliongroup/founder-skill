"""Bottom-up reachable market (SAM) and the share of it the goal needs.

market.json:
{
 "currency": "EUR",
 "segments": [
  {"name": "EU freelance designers",
   "count":          {"low": 300000, "mode": 420000, "high": 500000, "source": "fact:F012"},
   "reachable_share":{"low": 0.1, "mode": 0.2, "high": 0.3, "source": "estimate", "note": "EN/IT speakers online"},
   "adoption":       {"low": 0.2, "mode": 0.35, "high": 0.5, "source": "fact:F014"},
   "price_annual":   {"low": 108, "mode": 144, "high": 180, "source": "fact:F002"}}
 ]
}

SAM = sum over segments of count * reachable_share * adoption * price_annual.
The goal (frozen in prereg.json) is turned into annual revenue and divided by
SAM: the share of the reachable market the plan needs. Every input carries the
grade of its source, as in economics.
"""

import math
import random

from . import baserates, prereg
from .common import STRONG, IdeaError, Idea, now_iso, read_json, read_jsonl, write_json, write_text
from .economics import _pct, _range, _source_grade

FIELDS = ("count", "reachable_share", "adoption", "price_annual")
LABELS = {"count": "quanti sono", "reachable_share": "quota raggiungibile", "adoption": "quota che adotta questo tipo di soluzione",
          "price_annual": "prezzo annuo"}


def run(d, runs=4000, seed=12345):
    idea = Idea(d)
    reg = prereg.load(d)
    spec = read_json(idea.p("market.json"))
    segs = spec.get("segments") or []
    if not segs:
        raise IdeaError("market.json needs at least one segment")
    facts = {f["id"]: f for f in read_jsonl(idea.evidence)}
    rates = baserates.load()
    parsed = []
    for s in segs:
        if not s.get("name"):
            raise IdeaError("every segment needs a name")
        row = {"name": s["name"], "inputs": {}, "info": {}}
        for k in FIELDS:
            if k not in s:
                raise IdeaError("segment %r is missing %s" % (s["name"], k))
            r = _range(s[k], "%s.%s" % (s["name"], k))
            if k in ("reachable_share", "adoption") and not (0 <= r["low"] and r["high"] <= 1):
                raise IdeaError("%s.%s is a fraction between 0 and 1" % (s["name"], k))
            src = s[k].get("source") if isinstance(s[k], dict) else None
            grade, label = _source_grade(src, facts, rates)
            row["inputs"][k] = r
            row["info"][k] = {"grade": grade, "source": label}
        parsed.append(row)

    goal = reg.get("goal")
    goal_annual = None
    if goal and goal["metric"] in ("revenue", "mrr"):
        goal_annual = goal["value"] * 12.0

    def sam_of(pick):
        return sum(pick(seg, "count") * pick(seg, "reachable_share") * pick(seg, "adoption") * pick(seg, "price_annual")
                   for seg in parsed)

    rng = random.Random(seed)
    sams = []
    for _ in range(runs):
        def draw(seg, k):
            v = seg["inputs"][k]
            return rng.triangular(v["low"], v["high"], v["mode"]) if v["high"] > v["low"] else v["mode"]
        sams.append(sam_of(draw))
    mode_sam = sam_of(lambda seg, k: seg["inputs"][k]["mode"])
    shares = [goal_annual / s if s > 0 else math.inf for s in sams] if goal_annual else []
    n_inputs = len(parsed) * len(FIELDS)
    strong = sum(1 for seg in parsed for k in FIELDS if seg["info"][k]["grade"] in STRONG)
    counts_strong = all(seg["info"]["count"]["grade"] in STRONG for seg in parsed)
    result = {
        "computed_at": now_iso(), "currency": spec.get("currency", "EUR"), "runs": runs, "seed": seed,
        "segments": parsed, "goal": goal, "goal_annual_revenue": goal_annual,
        "sam": {"p10": _pct(sams, 0.1), "p50": _pct(sams, 0.5), "p90": _pct(sams, 0.9), "mode_case": mode_sam},
        "required_share": ({"p10": _pct(shares, 0.1), "p50": _pct(shares, 0.5), "p90": _pct(shares, 0.9),
                            "p_under_1pct": sum(1 for x in shares if x <= 0.01) / float(runs),
                            "p_under_5pct": sum(1 for x in shares if x <= 0.05) / float(runs)} if shares else None),
        "strong_input_share": strong / float(n_inputs), "all_counts_strong": counts_strong,
    }
    write_json(idea.p("market-result.json"), _clean(result))
    write_text(idea.p("market.md"), report(result))
    return result


def _clean(o):
    if isinstance(o, float) and math.isinf(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def _money(v, cur):
    if v is None:
        return "n/d"
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, cur + " ")
    return sym + "{:,.0f}".format(v).replace(",", ".")


def _pctf(v):
    return "n/d" if v is None or (isinstance(v, float) and math.isinf(v)) else "%.2f%%" % (v * 100)


def summary_lines(r):
    """Plain lines for the judge's brief: computed numbers and the grades behind them, no adjectives."""
    cur = r["currency"]
    L = ["- Bottom-up reachable market (SAM), annual: P10 %s, P50 %s, P90 %s." % (
        _money(r["sam"]["p10"], cur), _money(r["sam"]["p50"], cur), _money(r["sam"]["p90"], cur))]
    if r.get("required_share"):
        rs = r["required_share"]
        L.append("- Share of that market needed for the revenue target: P50 %s (P10 %s, P90 %s); "
                 "probability it is under 5%%: %.0f%%, under 1%%: %.0f%%." % (
                     _pctf(rs["p50"]), _pctf(rs["p10"]), _pctf(rs["p90"]), rs["p_under_5pct"] * 100, rs["p_under_1pct"] * 100))
    L.append("- Inputs with verified A/B sources: %.0f%%; segment counts all from A/B sources: %s." % (
        r["strong_input_share"] * 100, "yes" if r["all_counts_strong"] else "no"))
    for seg in r["segments"]:
        L.append("  - %s: %s" % (seg["name"], "; ".join(
            "%s %g-%g (%s, grade %s)" % (k, seg["inputs"][k]["low"], seg["inputs"][k]["high"],
                                         seg["info"][k]["source"], seg["info"][k]["grade"]) for k in FIELDS)))
    return L


def report(r):
    cur = r["currency"]
    L = ["# Mercato raggiungibile (dal basso)", "",
         "SAM = per ogni segmento: quanti sono × quota raggiungibile × quota che adotta × prezzo annuo. "
         "%d simulazioni, seed %s." % (r["runs"], r["seed"]), "",
         "| | P10 | P50 | P90 |", "| --- | ---: | ---: | ---: |",
         "| SAM annuo | %s | %s | %s |" % (_money(r["sam"]["p10"], cur), _money(r["sam"]["p50"], cur), _money(r["sam"]["p90"], cur))]
    if r.get("required_share"):
        rs = r["required_share"]
        L.append("| Quota del SAM necessaria per l'obiettivo | %s | %s | %s |" % (_pctf(rs["p10"]), _pctf(rs["p50"]), _pctf(rs["p90"])))
        L += ["", "Obiettivo pre-registrato: %s al mese %s (= %s all'anno). Probabilità che basti meno del 5%% del SAM: **%.0f%%**; "
              "meno dell'1%%: **%.0f%%**." % (_money(r["goal"]["value"], cur), r["goal"]["month"], _money(r["goal_annual_revenue"], cur),
                                              rs["p_under_5pct"] * 100, rs["p_under_1pct"] * 100)]
    else:
        L += ["", "Nessun obiettivo di ricavo pre-registrato: la quota necessaria non è calcolabile."]
    L += ["", "## Input", "", "| segmento | input | basso | moda | alto | fonte | grado |", "| --- | --- | ---: | ---: | ---: | --- | :---: |"]
    for seg in r["segments"]:
        for k in FIELDS:
            v, i = seg["inputs"][k], seg["info"][k]
            L.append("| %s | %s | %g | %g | %g | %s | %s |" % (seg["name"], LABELS[k], v["low"], v["mode"], v["high"], i["source"], i["grade"]))
    L += ["", "Input con prove A/B verificate: %.0f%%." % (r["strong_input_share"] * 100)]
    if not r["all_counts_strong"]:
        L.append("Almeno un conteggio di segmento non viene da una fonte A/B: il SAM è un'ipotesi.")
    return "\n".join(L) + "\n"
