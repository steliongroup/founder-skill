"""The verdict, computed. KILL / PIVOT / TEST / GO with a confidence level.

Nothing here is written by a model: the score is the weighted rubric levels,
confidence is the share of weight backed by verified A/B evidence, kill rules
come from the frozen rubric, and the next experiment is picked by rule.
"""

import math

from . import candidates, evidence, fetch, prereg, scoring
from .common import IdeaError, Idea, data_file, now_iso, read_json, read_jsonl, write_json, write_text

LABELS_IT = {"KILL": "SCARTARE", "PIVOT": "CAMBIARE IMPOSTAZIONE", "TEST": "TESTARE CON PERSONE REALI",
             "GO": "PROCEDERE", "INCOMPLETE": "INCOMPLETO"}


def _score(levels, weights):
    tot = sum(weights[k] for k in levels)
    return 100.0 * sum(weights[k] * (levels[k] - 1) / 4.0 for k in levels) / tot


def compute(d):
    idea = Idea(d)
    reg = prereg.load(d)
    rubric = reg["rubric"]
    weights = reg["weights"]
    names = {c["key"]: c["name_it"] for c in rubric["criteria"]}
    sheet = read_json(idea.idea)
    facts = read_jsonl(idea.evidence)
    cands = candidates.summary(idea)
    if cands["pending"]:
        raise IdeaError("%d collected candidates are still undecided: promote or reject each one "
                        "(ik.py candidates list %s --pending)" % (cands["pending"], d))
    missing = []
    try:
        judged = scoring.validate(d)
    except IdeaError as e:
        if "missing file" not in str(e):
            raise
        judged = []
        missing.append("giudizio dei criteri (judge/scores.json)")
    try:
        econ = read_json(idea.economics)
    except IdeaError:
        econ = None
        missing.append("economia (economics.json)")

    rows = {j["criterion"]: j for j in judged}
    if econ:
        lvl, raw, cap, why = scoring.economics_level(econ, rubric["evidence_rules"], rubric["kill"])
        rows["unit_economics"] = {"criterion": "unit_economics", "level": lvl, "level_raw": raw, "cap": cap,
                                  "rationale": why, "fact_ids": [], "computed": True,
                                  "strong": econ["strong_key_input_share"] >= 0.5}
    for r in rows.values():
        if "strong" not in r:
            r["strong"] = bool(r.get("strong_fact_ids"))

    if missing:
        result = {"verdict": "INCOMPLETE", "missing": missing, "codename": sheet["codename"], "computed_at": now_iso()}
        write_json(idea.verdict, result)
        write_text(idea.p("verdict.md"), report(result, names))
        return result

    levels = {k: rows[k]["level"] for k in weights}
    score = _score(levels, weights)
    raw_score = _score({k: rows[k]["level_raw"] for k in weights}, weights)
    coverage = sum(weights[k] for k in weights if rows[k]["strong"]) / float(sum(weights.values()))
    cb = rubric["confidence_bands"]
    confidence = "alta" if coverage >= cb["high"] else ("media" if coverage >= cb["medium"] else "bassa")

    triggered = []
    dist = econ["distribution"]
    for rule in rubric["kill"]:
        hit = False
        if rule["id"] == "negative_contribution":
            hit = dist["contribution"]["p50"] <= 0
        elif rule["id"] == "ltv_cac_below_1":
            v = dist["ltv_cac"]["p50"]
            hit = v is not None and v < float(rule.get("min", 1.0))
        elif rule["id"] == "no_breakeven_in_horizon":
            hit = dist["breakeven_month"]["p50"] is None
        elif rule["id"] == "evidence_against":
            hit = any(rows[k]["level"] <= rule["level"] and rows[k]["strong"] for k in rule["criteria"])
        if hit:
            triggered.append({"id": rule["id"], "action": rule["action"], "text": rule["text_it"]})

    bands = rubric["verdict_bands"]
    if any(t["action"] == "kill" for t in triggered):
        v = "KILL"
    elif score >= bands["go"] and confidence == "alta":
        v = "GO"
    elif score >= bands["test"]:
        v = "TEST"
    elif score >= bands["pivot"]:
        v = "PIVOT"
    else:
        v = "KILL"

    weakest = sorted(weights, key=lambda k: (rows[k]["strong"], rows[k]["level"], -weights[k]))
    target = next((k for k in weakest if not rows[k]["strong"]), weakest[0])
    exp = _pick_experiment(target)

    result = {
        "codename": sheet["codename"], "computed_at": now_iso(), "mode": reg["mode"],
        "rubric": "%s v%s" % (reg["rubric_id"], reg["rubric_version"]), "rubric_sha256": reg["rubric_sha256"],
        "verdict": v, "score": round(score, 1), "score_if_caps_lifted": round(raw_score, 1) if raw_score != score else None,
        "confidence": confidence, "strong_evidence_coverage": round(coverage, 3),
        "criteria": [dict(rows[k], weight=weights[k], name=names[k]) for k in weights],
        "triggered": triggered, "evidence": evidence.summary(facts),
        "triangulation": evidence.triangulation(facts),
        "economics": {"p50": {k: dist[k]["p50"] for k in dist}, "p_breakeven": econ["p_breakeven_in_horizon"],
                      "p_goal": econ.get("p_goal"), "goal": econ.get("goal"), "currency": econ["currency"],
                      "adjustments": econ["adjustments"], "tornado": econ["tornado"][:3],
                      "strong_key_input_share": econ["strong_key_input_share"]},
        "next_experiment": exp, "weakest_criterion": target,
        "candidates": cands, "sources": _sources(idea),
    }
    write_json(idea.verdict, _clean(result))
    write_text(idea.p("verdict.md"), report(result, names))
    return result


def _sources(idea):
    """What the collectors reached, failed to reach, or skipped (latest status per source and query)."""
    last = {}
    for e in fetch.log_entries(idea):
        last[(e["source"], e.get("query"))] = e
    out = {"ok": 0, "error": [], "skipped": []}
    for (src, q), e in sorted(last.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if e["status"] == "ok":
            out["ok"] += 1
        else:
            out[e["status"]].append({"source": src, "query": q, "error": e.get("error")})
    return out


def _clean(o):
    if isinstance(o, float) and math.isinf(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def _pick_experiment(target):
    lib = read_json(data_file("experiments.json"))["experiments"]
    for e in lib:
        if target in e["criteria"]:
            return dict(e, for_criterion=target)
    return dict(lib[0], for_criterion=target)


def _fmt_money(v, cur):
    if v is None or (isinstance(v, float) and math.isinf(v)):
        return "n/d"
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, cur + " ")
    return ("-" if v < 0 else "") + sym + "{:,.0f}".format(abs(v)).replace(",", ".")


def report(r, names):
    L = ["# Verdetto %s" % r["codename"], ""]
    if r["verdict"] == "INCOMPLETE":
        L += ["**Verdetto: INCOMPLETO.** Manca: %s." % "; ".join(r["missing"]), ""]
        return "\n".join(L) + "\n"
    L.append("**Verdetto: %s (%s)** · punteggio %.0f/100 · confidenza **%s** (%.0f%% del peso coperto da prove A/B verificate)"
             % (r["verdict"], LABELS_IT[r["verdict"]], r["score"], r["confidence"], r["strong_evidence_coverage"] * 100))
    L.append("")
    L.append("Modo %s, rubrica %s (hash %s...), calcolato il %s. Il verdetto è calcolato dal codice, non scritto da un modello."
             % (r["mode"], r["rubric"], r["rubric_sha256"][:12], r["computed_at"][:10]))
    if r["triggered"]:
        L += ["", "## Soglie scattate", ""]
        for t in r["triggered"]:
            L.append("- **%s**: %s" % ("SCARTO" if t["action"] == "kill" else "attenzione", t["text"]))
    L += ["", "## Criteri", "", "| criterio | peso | livello | prove forti | nota |", "| --- | ---: | :---: | --- | --- |"]
    for c in r["criteria"]:
        note = c.get("cap") or ""
        lvl = "%d" % c["level"] + (" (era %d)" % c["level_raw"] if c["level_raw"] != c["level"] else "")
        strong = "input economici" if c.get("computed") and c["strong"] else ", ".join(c.get("strong_fact_ids") or []) or "nessuna"
        L.append("| %s | %d | %s | %s | %s |" % (c["name"], c["weight"], lvl, strong, note))
    if r.get("score_if_caps_lifted"):
        L += ["", "Senza i limiti sulle prove il punteggio sarebbe %.0f: è quanto vale l'idea **se** le ipotesi deboli "
              "fossero confermate da prove forti." % r["score_if_caps_lifted"]]
    e = r["economics"]
    cur = e["currency"]
    p = e["p50"]
    L += ["", "## Numeri (mediana delle simulazioni)", ""]
    L.append("- Contributo per cliente pagante: %s; LTV:CAC %s." % (
        _fmt_money(p["contribution"], cur), "n/d" if p["ltv_cac"] is None else "%.1f" % p["ltv_cac"]))
    L.append("- Ricavo mensile al mese 24: %s; cassa necessaria: %s." % (
        _fmt_money(p["revenue_m24"], cur), _fmt_money(p["cash_needed"], cur)))
    L.append("- Probabilità di pareggio mensile nell'orizzonte: %.0f%%." % (e["p_breakeven"] * 100))
    if e.get("goal"):
        L.append("- Probabilità di raggiungere l'obiettivo: %.0f%%." % (e["p_goal"] * 100))
    if e["adjustments"]:
        L.append("- %d stime deboli riportate al tasso base (vedi economics.md)." % len(e["adjustments"]))
    if e["tornado"]:
        L.append("- Gli input che muovono di più il risultato: %s." % ", ".join(t["label"] for t in e["tornado"]))
    ev = r["evidence"]
    g = ev["by_effective_grade"]
    L += ["", "## Prove", "", "%d fatti: A %d, B %d, C %d, D %d (non verificati contano come D). In attesa di verifica: %d; verifica fallita: %d."
          % (ev["total"], g["A"], g["B"], g["C"], g["D"], ev["pending"], ev["failed"])]
    tri = [k for k, t in r["triangulation"].items() if t["triangulated"]]
    if tri:
        L.append("Confermati da almeno 2 fonti indipendenti: %s." % ", ".join(tri))
    c = r.get("candidates") or {}
    if c.get("promoted") or c.get("rejected"):
        L.append("Dati raccolti automaticamente: %d promossi a prova, %d scartati come non pertinenti "
                 "(motivi in data/candidates.jsonl)." % (c["promoted"], c["rejected"]))
    src = r.get("sources") or {}
    if src.get("error") or src.get("skipped"):
        L += ["", "## Fonti non raggiunte o saltate", "",
              "Queste fonti non hanno contribuito: i criteri che ne dipendono hanno meno prove, non prove inventate.", ""]
        for e in src.get("error", []) + src.get("skipped", []):
            L.append("- %s (%s): %s" % (e["source"], e["query"], e["error"]))
    x = r["next_experiment"]
    L += ["", "## Prossimo passo: l'esperimento reale più economico", "",
          "Criterio più debole tra quelli importanti: **%s**." % names[r["weakest_criterion"]], "",
          "**%s** (%s)" % (x["name_it"], x["cost_it"]), "", x["how_it"], "",
          "Soglia fissata prima del test: %s" % x["pass_it"], "",
          "Dopo il test, registra il risultato come prova `primary_data` e ricalcola con una nuova esecuzione."]
    L += ["", "_Le prove di grado C e D, il panel simulato e le stime non sono fatti. Non è consulenza finanziaria o legale._"]
    return "\n".join(L) + "\n"
