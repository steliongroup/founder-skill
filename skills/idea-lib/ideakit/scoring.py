"""The blind judge: a brief built by code, and caps that code enforces on the scores.

The judge sees only the neutral sheet, the evidence table and the rubric. It
never sees the founder's claims, notes, title or which idea is preferred.
Code then rejects scores without citations and caps any level the evidence
cannot carry.
"""

import math

from . import evidence, prereg
from .common import STRONG, IdeaError, Idea, read_json, read_jsonl, write_text

BRIEF = """# Evaluation brief {codename}

You are an independent analyst scoring a business proposal against a fixed rubric.
You did not write the proposal and nobody involved will see your name. Your job is
accuracy, not encouragement: most new products fail, and a score above 3 must be
earned by the evidence below, not by how plausible the idea sounds.

Rules:
1. Use ONLY the facts in the evidence table. Do not use outside knowledge, and do
   not assume facts that are not listed.
2. For each criterion pick the anchor level (1-5) that the evidence supports. If
   evidence is missing, the right answer is the "no evidence" level (usually 2).
3. Cite the fact ids (e.g. F003) that support each level. With no relevant
   facts, leave fact_ids empty and pick the "no evidence" level. Code caps any
   level above 3 that lacks verified grade A or B facts, so do not try.
4. Write the rationale before choosing the level, and keep it to 1-3 sentences.

## The proposal (neutral description)

{sheet}

## Evidence table

Grade: A primary or official, B report with known sample, C secondary, D unverified.
Only facts marked verified count as A or B.

{facts}

{computed}## Rubric

{rubric}

## Output

Write the file {out} containing ONLY this JSON (no markdown fence), one object per
criterion listed above, in any order:

[
  {{"criterion": "<key>", "rationale": "<1-3 sentences>", "level": <1-5>, "fact_ids": ["F001", "..."]}}
]
"""


def _sheet_text(s):
    a = s["archetype"]
    p = s["price_hypothesis"]
    lines = [
        "- Codename: %s" % s["codename"],
        "- One line: %s" % s["one_liner"],
        "- Problem: %s" % s["problem"],
        "- Solution: %s" % s["solution"],
        "- Market: %s; platform: %s; geography: %s; revenue model: %s" % (
            a["market"], ", ".join(a["platform"]), ", ".join(a["geo"]), a["revenue_model"]),
        "- Price hypothesis: %s %s per %s" % (p["amount"], p["currency"], p["period"]),
        "- Target segments:",
    ]
    lines += ["  - %s: %s" % (t["name"], t["description"]) for t in s["target_segments"]]
    lines.append("- Current alternatives buyers use: %s" % "; ".join(s["current_alternatives"]))
    return "\n".join(lines)


def _facts_text(facts):
    if not facts:
        return "(no facts collected)"
    L = ["| id | fact | value | source | date | grade | verified |", "| --- | --- | --- | --- | --- | :---: | :---: |"]
    for f in facts:
        val = "" if f.get("value") is None else "%s %s" % (f["value"], f.get("unit", ""))
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            f["id"], f["claim"].replace("|", "/"), val.strip(), f["publisher"].replace("|", "/"),
            f.get("date") or "", evidence.effective_grade(f), "yes" if f.get("verified") else "no"))
    return "\n".join(L)


def _rubric_text(rubric):
    L = []
    for c in rubric["criteria"]:
        if c.get("computed"):
            continue
        L.append("### %s\n%s" % (c["key"], c["question"]))
        for lvl in sorted(c["anchors"]):
            L.append("- %s: %s" % (lvl, c["anchors"][lvl]))
        L.append("")
    return "\n".join(L).strip()


def judged_keys(rubric):
    return [c["key"] for c in rubric["criteria"] if not c.get("computed")]


def brief(d):
    idea = Idea(d)
    reg = prereg.load(d)
    sheet = read_json(idea.idea)
    facts = read_jsonl(idea.evidence)
    computed = ""
    mr = read_json(idea.p("market-result.json"), default={})
    if mr:
        from .market import summary_lines
        computed = ("## Computed indicators\n\nCalculated by code from the evidence and estimates above; the grade of "
                    "each input is shown. Use them for the market criterion.\n\n" + "\n".join(summary_lines(mr)) + "\n\n")
    text = BRIEF.format(codename=sheet["codename"], sheet=_sheet_text(sheet), facts=_facts_text(facts),
                        computed=computed, rubric=_rubric_text(reg["rubric"]), out=idea.scores)
    write_text(idea.brief, text)
    return idea.brief


def validate(d):
    """Return the judged criteria after code checks: [{criterion, level_raw, level, cap, fact_ids, ...}]."""
    idea = Idea(d)
    reg = prereg.load(d)
    rules = reg["rubric"]["evidence_rules"]
    cap_weak = int(rules["cap_without_strong_evidence"])
    need_for_5 = int(rules["min_independent_strong_for_5"])
    raw = read_json(idea.scores)
    if not isinstance(raw, list):
        raise IdeaError("scores.json must be a JSON list")
    facts = {f["id"]: f for f in read_jsonl(idea.evidence)}
    keys = judged_keys(reg["rubric"])
    got = {}
    for s in raw:
        k = s.get("criterion")
        if k not in keys:
            raise IdeaError("scores.json: unknown criterion %r" % k)
        if k in got:
            raise IdeaError("scores.json: %s scored twice" % k)
        got[k] = s
    missing = [k for k in keys if k not in got]
    if missing:
        raise IdeaError("scores.json: missing %s" % ", ".join(missing))
    out = []
    for k in keys:
        s = got[k]
        lvl = s.get("level")
        if not isinstance(lvl, int) or not 1 <= lvl <= 5:
            raise IdeaError("%s: level must be an integer 1-5" % k)
        ids = s.get("fact_ids") or []
        bad = [i for i in ids if i not in facts]
        if bad:
            raise IdeaError("%s cites facts that do not exist: %s" % (k, ", ".join(bad)))
        if not str(s.get("rationale", "")).strip():
            raise IdeaError("%s: rationale is empty" % k)
        cited = [facts[i] for i in ids]
        strong = [f for f in cited if evidence.effective_grade(f) in STRONG]
        publishers = {f["publisher"].strip().lower() for f in strong}
        level, cap = lvl, None
        if not ids:
            level, cap = min(level, cap_weak), "no facts cited"
        elif level > cap_weak and not strong:
            level, cap = cap_weak, "levels above %d need a verified A/B fact" % cap_weak
        elif level == 5 and len(publishers) < need_for_5:
            level, cap = 4, "level 5 needs %d independent strong sources" % need_for_5
        out.append({"criterion": k, "level_raw": lvl, "level": level, "cap": cap, "fact_ids": ids,
                    "strong_fact_ids": [f["id"] for f in strong], "rationale": s["rationale"].strip()})
    return out


def economics_level(econ, rules, kill):
    """Level 1-5 for unit_economics, from the simulation. Returns (level, raw_level, cap, reason)."""
    d = econ["distribution"]
    contrib = d["contribution"]["p50"]
    ltv_cac = d["ltv_cac"]["p50"]
    ltv_cac = math.inf if ltv_cac is None else ltv_cac
    be = d["breakeven_month"]["p50"]
    be = math.inf if be is None else be
    horizon = econ["horizon_months"]
    p_goal = econ.get("p_goal")
    if contrib <= 0 or ltv_cac < 1:
        lvl, why = 1, "contributo <= 0 o LTV:CAC < 1"
    elif ltv_cac < 2 or be > horizon:
        lvl, why = 2, "LTV:CAC tra 1 e 2 o pareggio oltre l'orizzonte"
    elif ltv_cac < 3:
        lvl, why = 3, "LTV:CAC tra 2 e 3"
    elif ltv_cac >= 5 and be <= 12 and (p_goal is None or p_goal >= 0.5):
        lvl, why = 5, "LTV:CAC >= 5, pareggio entro 12 mesi"
    elif be <= 24:
        lvl, why = 4, "LTV:CAC >= 3, pareggio entro 24 mesi"
    else:
        lvl, why = 3, "LTV:CAC >= 3 ma pareggio oltre 24 mesi"
    need = float(rules.get("economics_min_strong_input_share_for_4", 0.5))
    if lvl >= 4 and econ["strong_key_input_share"] < need:
        return 3, lvl, "meno del %.0f%% degli input chiave ha prove A/B" % (need * 100), why
    return lvl, lvl, None, why
