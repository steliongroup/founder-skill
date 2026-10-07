---
name: idea-verdict
description: >-
  Runs the blind judgment and computes the verdict for an idea. Code writes a
  brief with only the neutral fact sheet, the evidence table and the frozen
  rubric; a fresh judge sub-agent that has not seen the conversation scores each
  criterion and must cite fact ids; code rejects uncited or invalid scores, caps
  levels the evidence cannot carry, adds the computed economics level, applies the
  pre-registered kill thresholds and outputs KILL / PIVOT / TEST / GO with a
  confidence level and the cheapest real-world experiment. Use inside /idea-valuta
  or when the user says "dai il verdetto", "score this idea", "verdict".
argument-hint: "ideas/<slug>"
---

# idea-verdict

You (the session that talked to the founder) do not score the idea. A judge who
has never heard the pitch does, from a brief that code wrote, and code decides
what the scores are allowed to be.

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
```

## Step 1: the brief

```bash
$IK brief ideas/<slug>
```

It writes `ideas/<slug>/judge/brief.md`: the codename, the neutral sheet, the
evidence table with effective grades, and the rubric anchors for every judged
criterion. It contains no claims, no private notes, no title, no economics level.
Do not edit it.

## Step 2: the judge

Launch ONE sub-agent (Agent tool, `subagent_type: general-purpose`) with exactly
this prompt, nothing added:

```
Read <absolute path to judge/brief.md> and follow it exactly. It is your whole
brief. Do not open any other file in that folder or elsewhere, and do not search
the web. Write the JSON file it asks for and reply with "done".
```

Do not tell the judge anything about the founder, the conversation, or what you
think of the idea. If the judge printed the JSON instead of writing it, save its
reply's JSON array to `judge/scores.json` unchanged.

Limitation, say it if asked: in this version the judge is one Claude sub-agent,
so the brief protects it from the founder's framing but not from Claude's own
habits. A multi-model jury on OpenRouter replaces it in a later phase.

## Step 3: the verdict

```bash
$IK verdict ideas/<slug>
```

If it fails with a scores problem (missing criterion, unknown fact id, level out
of range), re-run the judge once with the same prompt; never fix the scores
yourself.

What code does:
- A level above 3 needs at least one cited fact that is verified and grade A/B;
  otherwise it is capped at 3. Level 5 needs two independent strong publishers.
- `unit_economics` is computed from `economics.json` (LTV:CAC, break-even, goal),
  capped at 3 when fewer than half the key inputs have A/B evidence.
- Kill thresholds from the frozen rubric: negative contribution per customer,
  LTV:CAC below 1, strong evidence against the problem or demand.
- Score = weighted levels (0-100). Confidence = share of the weight backed by
  verified A/B evidence. GO needs a high score AND high confidence; a high score
  on weak evidence is TEST, never GO. With no verified A/B evidence at all, every
  level is capped at 3 and the best possible verdict is PIVOT.
- The next experiment targets the most important criterion that lacks strong
  evidence, with a pass threshold fixed in advance.

## Step 4: tell the user

From `verdict.md`, in Italian, without softening:
- the verdict line as written;
- why: the criteria with the lowest levels and the highest weights, and the
  fired thresholds;
- what is proven (A/B) and what is still belief;
- `score_if_caps_lifted` if present: "if the weak hypotheses were confirmed, the
  score would be X", which is the honest upside;
- the next experiment, its cost and its pass threshold.

If the user disagrees: ask what evidence would show the verdict wrong, add it
through `idea-evidence`, and start a new run (`$IK prereg --new-run`). Never
re-score, never edit `scores.json`, never edit `prereg.json`.

## Output

`ideas/<slug>/judge/brief.md`, `judge/scores.json`, `verdict.json`, `verdict.md`.
