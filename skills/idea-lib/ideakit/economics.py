"""Unit economics for software ideas, as a Monte Carlo over input ranges.

assumptions.json gives every input as a number or a {low, mode, high} range,
with its source: "fact:F003", "baserate:<id>", "claim:C002" or "estimate".
A weak input (grade C or D) that sits outside the range of its base-rate prior
is clamped into that range: optimism needs evidence. Every clamp is reported.

The month loop (subscription; one_time sells each customer once):
    visitors   = visitors_month1 * (1 + visitor_growth_monthly) ** (m - 1)
    signups    = visitors * visitor_to_signup
    new_paid   = signups * signup_to_paid + paid_budget_monthly / cac_paid
    paying     = paying * (1 - monthly_churn) + new_paid
    free       = free * (1 - free_user_monthly_churn) + signups * (1 - signup_to_paid)
    revenue    = paying * price                     (one_time: new_paid * price)
    costs      = revenue * payment_fee_pct + paying * variable_cost_paying
                 + free * variable_cost_free + fixed_monthly + paid_budget_monthly
"""

import math
import random

from . import baserates, evidence, prereg
from .common import STRONG, IdeaError, Idea, now_iso, read_json, read_jsonl, write_json, write_text

INPUTS = {
    # key: (required, plain-language label)
    "price": (True, "prezzo per cliente pagante (al mese, o per vendita se one_time)"),
    "payment_fee_pct": (False, "commissioni di pagamento (quota del ricavo)"),
    "variable_cost_paying": (True, "costo variabile per cliente pagante al mese (AI, hosting, supporto)"),
    "variable_cost_free": (False, "costo variabile per utente gratuito attivo al mese"),
    "fixed_monthly": (True, "costi fissi al mese"),
    "startup_cost": (False, "spesa iniziale una tantum"),
    "visitors_month1": (True, "visitatori nel mese 1 (organici)"),
    "visitor_growth_monthly": (False, "crescita mensile dei visitatori"),
    "visitor_to_signup": (True, "visitatore -> registrazione"),
    "signup_to_paid": (True, "registrazione -> cliente pagante"),
    "monthly_churn": (True, "abbandono mensile dei paganti"),
    "free_user_monthly_churn": (False, "abbandono mensile degli utenti gratuiti"),
    "paid_budget_monthly": (False, "budget pubblicitario al mese"),
    "cac_paid": (True, "costo per acquisire un cliente pagante con canali a pagamento"),
}
DEFAULTS = {"payment_fee_pct": 0.0, "variable_cost_free": 0.0, "startup_cost": 0.0, "visitor_growth_monthly": 0.0,
            "free_user_monthly_churn": 0.3, "paid_budget_monthly": 0.0}
FRACTIONS = ("payment_fee_pct", "visitor_growth_monthly", "visitor_to_signup", "signup_to_paid", "monthly_churn",
             "free_user_monthly_churn")
MODELS = ("subscription", "one_time")
# The inputs founders are most optimistic about must name the base rate they are
# compared with, chosen from these lists, so a weak estimate cannot skip the clamp.
REQUIRED_PRIORS = {
    "visitor_to_signup": ("landing_signup_saas", "landing_signup_all"),
    "signup_to_paid": ("freemium_to_paid_selfserve", "trial_to_paid_no_card", "trial_to_paid_card",
                       "mobile_install_to_paid", "mobile_hard_paywall_vs_freemium"),
    "monthly_churn": ("saas_monthly_churn_early", "consumer_sub_monthly_churn"),
}


# ── inputs ──────────────────────────────────────────────────────────────────────
def _range(spec, key):
    if isinstance(spec, (int, float)):
        v = float(spec)
        return {"low": v, "mode": v, "high": v}
    if not isinstance(spec, dict):
        raise IdeaError("%s must be a number or {low, mode, high, source}" % key)
    try:
        r = {k: float(spec[k]) for k in ("low", "mode", "high")}
    except KeyError as e:
        raise IdeaError("%s needs %s" % (key, e))
    except (TypeError, ValueError):
        raise IdeaError("%s: low, mode and high must be numbers" % key)
    if not r["low"] <= r["mode"] <= r["high"]:
        raise IdeaError("%s: need low <= mode <= high, got %s" % (key, r))
    return r


def _source_grade(source, facts_by_id, rates):
    """(grade, label) of an input's source."""
    s = str(source or "estimate")
    kind, _, ref = s.partition(":")
    if kind == "fact":
        f = facts_by_id.get(ref)
        if not f:
            raise IdeaError("source %s: no such fact in evidence.jsonl" % s)
        return evidence.effective_grade(f), s
    if kind == "baserate":
        return baserates.grade(baserates.get(ref, rates)), s
    if kind == "claim":
        return "D", s
    if kind == "estimate":
        return "D", "estimate"
    raise IdeaError("source %r must be fact:Fxxx, baserate:<id>, claim:Cxxx or estimate" % s)


def resolve(assumptions, facts, rates, clamp=True):
    """Validate inputs, grade them, clamp weak ones to their prior. Returns (inputs, info, adjustments)."""
    model = assumptions.get("model", "subscription")
    if model not in MODELS:
        raise IdeaError("model must be subscription or one_time")
    raw = assumptions.get("inputs") or {}
    unknown = sorted(set(raw) - set(INPUTS))
    if unknown:
        raise IdeaError("unknown inputs: %s (allowed: %s)" % (", ".join(unknown), ", ".join(INPUTS)))
    facts_by_id = {f["id"]: f for f in facts}
    inputs, info, adjustments = {}, {}, []
    for key, (required, label) in INPUTS.items():
        if key not in raw:
            if required:
                raise IdeaError("assumptions.json is missing input %r (%s)" % (key, label))
            v = DEFAULTS[key]
            inputs[key] = {"low": v, "mode": v, "high": v}
            info[key] = {"grade": "D", "source": "default", "label": label}
            continue
        spec = raw[key]
        r = _range(spec, key)
        if key in FRACTIONS and not (0 <= r["low"] and r["high"] <= 1):
            raise IdeaError("%s is a fraction between 0 and 1 (3%% = 0.03)" % key)
        if any(v < 0 for v in r.values()):
            raise IdeaError("%s cannot be negative" % key)
        src = spec.get("source") if isinstance(spec, dict) else None
        grade, label_src = _source_grade(src, facts_by_id, rates)
        prior_id = spec.get("prior") if isinstance(spec, dict) else None
        allowed = REQUIRED_PRIORS.get(key)
        if key == "monthly_churn" and model == "one_time":
            allowed = None  # one-off sales have no churn
        if allowed and prior_id not in allowed:
            raise IdeaError("%s needs \"prior\": one of %s (the base rate it is compared with)"
                            % (key, ", ".join(allowed)))
        if prior_id:
            prior = baserates.get(prior_id, rates)["range"]
            outside = r["mode"] < prior["low"] or r["mode"] > prior["high"]
            if outside and grade not in STRONG:
                before = dict(r)
                if clamp:
                    r = {k: min(max(v, prior["low"]), prior["high"]) for k, v in r.items()}
                adjustments.append({"input": key, "prior": prior_id, "grade": grade, "before": before,
                                    "after": r, "clamped": clamp})
        inputs[key] = r
        info[key] = {"grade": grade, "source": label_src, "label": label, "prior": prior_id,
                     "note": spec.get("note") if isinstance(spec, dict) else None}
    if inputs["cac_paid"]["low"] <= 0:
        raise IdeaError("cac_paid must be above zero (what it would cost to buy one customer)")
    if inputs["price"]["low"] <= 0:
        raise IdeaError("price must be above zero; for a free tier model the paying tier only")
    return model, inputs, info, adjustments


# ── simulation ──────────────────────────────────────────────────────────────────
def simulate(model, x, horizon):
    """One run with fixed inputs x. Returns monthly rows and summary numbers."""
    paying = free = 0.0
    cumulative = -x["startup_cost"]
    rows = []
    breakeven = None
    low = cumulative
    for m in range(1, horizon + 1):
        visitors = x["visitors_month1"] * (1 + x["visitor_growth_monthly"]) ** (m - 1)
        signups = visitors * x["visitor_to_signup"]
        new_paid = signups * x["signup_to_paid"] + x["paid_budget_monthly"] / x["cac_paid"]
        if model == "subscription":
            paying = paying * (1 - x["monthly_churn"]) + new_paid
            revenue = paying * x["price"]
            var_paying = paying * x["variable_cost_paying"]
        else:
            paying = new_paid
            revenue = new_paid * x["price"]
            var_paying = new_paid * x["variable_cost_paying"]
        free = free * (1 - x["free_user_monthly_churn"]) + signups * (1 - x["signup_to_paid"])
        costs = (revenue * x["payment_fee_pct"] + var_paying + free * x["variable_cost_free"]
                 + x["fixed_monthly"] + x["paid_budget_monthly"])
        profit = revenue - costs
        cumulative += profit
        low = min(low, cumulative)
        if breakeven is None and profit >= 0 and revenue > 0:
            breakeven = m
        rows.append({"month": m, "visitors": visitors, "signups": signups, "new_paid": new_paid, "paying": paying,
                     "free": free, "revenue": revenue, "costs": costs, "profit": profit, "cumulative": cumulative})
    contribution = x["price"] * (1 - x["payment_fee_pct"]) - x["variable_cost_paying"]
    if model == "subscription":
        ltv = contribution / x["monthly_churn"] if x["monthly_churn"] > 0 else math.inf
    else:
        ltv = contribution
    payback = x["cac_paid"] / contribution if contribution > 0 and model == "subscription" else None
    return rows, {
        "contribution": contribution, "ltv": ltv, "ltv_cac": ltv / x["cac_paid"], "cac_payback_months": payback,
        "breakeven_month": breakeven, "cash_needed": -low,
        "revenue_m12": rows[min(11, horizon - 1)]["revenue"], "revenue_m24": rows[min(23, horizon - 1)]["revenue"],
        "revenue_end": rows[-1]["revenue"], "paying_m12": rows[min(11, horizon - 1)]["paying"],
        "paying_m24": rows[min(23, horizon - 1)]["paying"], "profit_end": rows[-1]["profit"],
        "cumulative_end": rows[-1]["cumulative"],
    }


def _pct(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    i = (len(vals) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    a, b = vals[lo], vals[hi]
    if math.isinf(a) or math.isinf(b):
        return a if i - lo < 0.5 else b
    return a + (b - a) * (i - lo)


def _goal_value(rows, goal):
    m = min(int(goal["month"]), len(rows))
    metric = goal.get("metric", "revenue")
    if metric in ("revenue", "mrr"):
        return rows[m - 1]["revenue"]
    if metric == "profit":
        return rows[m - 1]["profit"]
    if metric == "paying":
        return rows[m - 1]["paying"]
    raise IdeaError("goal.metric must be revenue, profit or paying")


def run(d, runs=None, seed=None, clamp=None):
    idea = Idea(d)
    assumptions = read_json(idea.assumptions)
    try:
        reg = prereg.load(d)
    except IdeaError as e:
        if "missing file" not in str(e):
            raise
        raise IdeaError("pre-register first (ik.py prereg): the goal and thresholds must be frozen before the numbers")
    rubric_econ = reg["rubric"].get("economics", {})
    horizon = int(assumptions.get("horizon_months") or rubric_econ.get("horizon_months", 36))
    runs = int(runs or rubric_econ.get("runs", 4000))
    clamp = rubric_econ.get("clamp_weak_inputs_to_prior", True) if clamp is None else clamp
    seed = 12345 if seed is None else seed
    facts = read_jsonl(idea.evidence)
    rates = baserates.load()
    model, inputs, info, adjustments = resolve(assumptions, facts, rates, clamp)
    goal = reg.get("goal")
    if assumptions.get("goal") and assumptions["goal"] != goal:
        raise IdeaError("assumptions.json has its own goal: the goal is pre-registered in prereg.json "
                        "(input/goal.json or ideas/config.json). Remove it from assumptions.json.")

    mode_x = {k: v["mode"] for k, v in inputs.items()}
    mode_rows, mode_sum = simulate(model, mode_x, horizon)

    rng = random.Random(seed)
    samples = {k: [] for k in mode_sum}
    goal_hits = 0
    for _ in range(runs):
        x = {k: (rng.triangular(v["low"], v["high"], v["mode"]) if v["high"] > v["low"] else v["mode"])
             for k, v in inputs.items()}
        rows, s = simulate(model, x, horizon)
        for k, v in s.items():
            samples[k].append(math.inf if v is None and k in ("breakeven_month", "cac_payback_months") else v)
        if goal and _goal_value(rows, goal) >= float(goal["value"]):
            goal_hits += 1
    dist = {k: {"p10": _pct(v, 0.1), "p50": _pct(v, 0.5), "p90": _pct(v, 0.9)} for k, v in samples.items()}
    p_breakeven = sum(1 for v in samples["breakeven_month"] if not math.isinf(v)) / float(runs)

    # one-at-a-time sensitivity around the mode case
    tornado = []
    target_month = int(goal["month"]) if goal else min(24, horizon)
    for k, v in inputs.items():
        if v["high"] == v["low"]:
            continue
        outs = []
        for end in ("low", "high"):
            x = dict(mode_x)
            x[k] = v[end]
            rows, s = simulate(model, x, horizon)
            outs.append((rows[target_month - 1]["revenue"], s["breakeven_month"]))
        tornado.append({"input": k, "label": info[k]["label"], "revenue_at_low": outs[0][0],
                        "revenue_at_high": outs[1][0], "swing": abs(outs[1][0] - outs[0][0]),
                        "breakeven_at_low": outs[0][1], "breakeven_at_high": outs[1][1]})
    tornado.sort(key=lambda t: -t["swing"])

    key_inputs = reg["rubric"]["evidence_rules"]["economics_key_inputs"]
    strong = [k for k in key_inputs if info[k]["grade"] in STRONG]

    result = {
        "computed_at": now_iso(), "model": model, "currency": assumptions.get("currency", "EUR"),
        "horizon_months": horizon, "runs": runs, "seed": seed, "goal": goal,
        "inputs": inputs, "input_info": info, "adjustments": adjustments,
        "mode_case": mode_sum, "mode_months": mode_rows, "distribution": dist,
        "p_breakeven_in_horizon": p_breakeven,
        "p_goal": (goal_hits / float(runs)) if goal else None,
        "tornado": tornado[:6], "key_inputs": key_inputs, "strong_key_inputs": strong,
        "strong_key_input_share": len(strong) / float(len(key_inputs)) if key_inputs else 0.0,
    }
    write_json(idea.economics, _jsonable(result))
    write_text(idea.p("economics.md"), report(result))
    return result


def _jsonable(o):
    if isinstance(o, float) and math.isinf(o):
        return None
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    return o


# ── report ──────────────────────────────────────────────────────────────────────
def _m(v, cur="EUR"):
    if v is None or (isinstance(v, float) and math.isinf(v)):
        return "n/d"
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, cur + " ")
    s = "{:,.0f}".format(abs(v)).replace(",", ".")
    return ("-" if v < 0 else "") + sym + s


def _mo(v, horizon):
    if v is None or (isinstance(v, float) and math.isinf(v)):
        return "oltre %d mesi" % horizon
    return "mese %.0f" % v


def report(r):
    cur, h, d = r["currency"], r["horizon_months"], r["distribution"]
    L = ["# Economia (simulazione)", ""]
    L.append("%d simulazioni con seed %s, orizzonte %d mesi, modello %s. Ogni input è un intervallo; "
             "i risultati sono P10 / P50 / P90 (pessimista / mediano / ottimista)." % (r["runs"], r["seed"], h, r["model"]))
    L += ["", "## Risultati", "", "| misura | P10 | P50 | P90 |", "| --- | ---: | ---: | ---: |"]

    def row(name, k, fmt):
        L.append("| %s | %s | %s | %s |" % (name, fmt(d[k]["p10"]), fmt(d[k]["p50"]), fmt(d[k]["p90"])))
    row("Contributo per cliente pagante", "contribution", lambda v: _m(v, cur))
    row("LTV (valore di un cliente)", "ltv", lambda v: _m(v, cur))
    row("LTV : CAC", "ltv_cac", lambda v: "n/d" if v is None or math.isinf(v) else "%.1f" % v)
    row("Ricavo mensile al mese 12", "revenue_m12", lambda v: _m(v, cur))
    row("Ricavo mensile al mese 24", "revenue_m24", lambda v: _m(v, cur))
    row("Clienti paganti al mese 24", "paying_m24", lambda v: "%.0f" % v)
    row("Primo mese in pareggio", "breakeven_month", lambda v: _mo(v, h))
    row("Cassa necessaria", "cash_needed", lambda v: _m(v, cur))
    L.append("")
    L.append("- Probabilità di arrivare al pareggio mensile entro %d mesi: **%.0f%%**." % (h, r["p_breakeven_in_horizon"] * 100))
    if r["goal"]:
        g = r["goal"]
        L.append("- Probabilità di raggiungere l'obiettivo (%s >= %s al mese %s): **%.0f%%**." % (
            g.get("metric", "revenue"), g["value"], g["month"], r["p_goal"] * 100))
    L += ["", "## Da dove vengono gli input", "", "| input | basso | moda | alto | fonte | grado | tasso base |",
          "| --- | ---: | ---: | ---: | --- | :---: | --- |"]
    for k, v in r["inputs"].items():
        i = r["input_info"][k]
        L.append("| %s | %g | %g | %g | %s | %s | %s |" % (i["label"], v["low"], v["mode"], v["high"], i["source"],
                                                          i["grade"], i.get("prior") or ""))
    share = r["strong_key_input_share"]
    L += ["", "Input chiave con prova forte (A/B): %d su %d (%s)." % (
        len(r["strong_key_inputs"]), len(r["key_inputs"]), ", ".join(r["strong_key_inputs"]) or "nessuno")]
    if share < 0.5:
        L.append("Meno della metà degli input chiave ha una prova forte: il risultato è soprattutto un'ipotesi.")
    if r["adjustments"]:
        L += ["", "## Stime riportate al tasso base", "",
              "Questi input avevano una fonte debole e un valore fuori dall'intervallo del tasso base. "
              "Sono stati riportati dentro l'intervallo: per uscirne serve una prova di grado A o B."]
        for a in r["adjustments"]:
            L.append("- %s: moda %g -> %g (tasso base %s, grado della fonte %s)." % (
                a["input"], a["before"]["mode"], a["after"]["mode"], a["prior"], a["grade"]))
    if r["tornado"]:
        L += ["", "## Cosa muove di più il risultato", "",
              "Ricavo mensile al mese %s cambiando un input alla volta dal minimo al massimo:" % (
                  r["goal"]["month"] if r["goal"] else min(24, h)), ""]
        for t in r["tornado"]:
            L.append("- %s: da %s a %s." % (t["label"], _m(t["revenue_at_low"], cur), _m(t["revenue_at_high"], cur)))
    L += ["", "Tutti i numeri vengono da assumptions.json e dalle fonti citate. Non sono consigli finanziari."]
    return "\n".join(L) + "\n"
