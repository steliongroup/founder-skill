"""Pre-registration: freeze the rubric, weights and thresholds before research.

prereg.json embeds a full copy of the rubric and its hash. The verdict uses the
embedded copy and refuses to run if the copy was edited afterwards.
"""

import os
import shutil

from .common import IdeaError, Idea, canonical_sha256, data_file, now_iso, read_json, write_json

MODES = ("quick", "full")


def freeze(d, mode="quick", rubric_path=None, new_run=False):
    idea = Idea(d)
    idea.require_dir()
    if mode not in MODES:
        raise IdeaError("mode must be quick or full")
    sheet = read_json(idea.idea)
    market = sheet.get("archetype", {}).get("market")
    rubric_path = rubric_path or data_file("rubric.v1.json")
    rubric = read_json(rubric_path)
    if market not in rubric["weights_by_market"]:
        raise IdeaError("the rubric has no weights for market %r" % market)
    if os.path.exists(idea.prereg):
        if not new_run:
            raise IdeaError("already pre-registered. A new run (after real-world evidence or a new rubric)"
                            " needs --new-run, which archives the current run.")
        _archive(idea)
    weights = rubric["weights_by_market"][market]
    keys = [c["key"] for c in rubric["criteria"]]
    if sorted(weights) != sorted(keys):
        raise IdeaError("rubric weights for %s do not match its criteria" % market)
    goal = _goal(idea)
    reg = {
        "goal": goal,
        "rubric_id": rubric["id"], "rubric_version": rubric["version"],
        "rubric_file": os.path.basename(rubric_path), "rubric_sha256": canonical_sha256(rubric),
        "rubric": rubric, "mode": mode, "market": market, "weights": weights,
        "codename": sheet.get("codename"), "frozen_at": now_iso(),
    }
    reg["registration_sha256"] = canonical_sha256(reg)
    write_json(idea.prereg, reg)
    return reg


def _goal(idea):
    """The revenue goal, frozen with the rubric: input/goal.json, else <ideas root>/config.json default_goal."""
    g = read_json(idea.p("input", "goal.json"), default={}) or \
        read_json(os.path.join(os.path.dirname(os.path.abspath(idea.dir)), "config.json"), default={}).get("default_goal")
    if not g:
        return None
    for k in ("metric", "month", "value"):
        if k not in g:
            raise IdeaError("the goal needs metric, month and value, e.g. {\"metric\": \"revenue\", \"month\": 24, \"value\": 3000}")
    if g["metric"] not in ("revenue", "mrr", "profit", "paying"):
        raise IdeaError("goal.metric must be revenue, profit or paying")
    return {"metric": g["metric"], "month": int(g["month"]), "value": float(g["value"])}


def _archive(idea):
    old = read_json(idea.prereg)
    stamp = old.get("frozen_at", "old").replace(":", "").replace("-", "")
    dest = idea.p("runs", stamp)
    os.makedirs(dest, exist_ok=True)
    for f in ("prereg.json", "verdict.json", "verdict.md", "economics.json", "economics.md"):
        if os.path.exists(idea.p(f)):
            shutil.move(idea.p(f), os.path.join(dest, f))
    if os.path.isdir(idea.p("judge")):
        shutil.move(idea.p("judge"), os.path.join(dest, "judge"))
        os.makedirs(idea.p("judge"))


def load(d):
    """The frozen registration, checked against its own hash."""
    idea = Idea(d)
    reg = read_json(idea.prereg)
    if canonical_sha256(reg["rubric"]) != reg["rubric_sha256"]:
        raise IdeaError("the rubric inside prereg.json was edited after pre-registration. "
                        "Start a new run instead (ik.py prereg --new-run).")
    body = {k: v for k, v in reg.items() if k != "registration_sha256"}
    if canonical_sha256(body) != reg.get("registration_sha256"):
        raise IdeaError("prereg.json was edited after pre-registration (goal, mode or weights). "
                        "Start a new run instead (ik.py prereg --new-run).")
    w = reg["rubric"]["weights_by_market"][reg["market"]]
    if w != reg["weights"]:
        raise IdeaError("the weights in prereg.json do not match the frozen rubric")
    return reg
