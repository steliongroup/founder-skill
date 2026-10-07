---
name: idea-valuta
description: >-
  Evaluates a business or software idea end to end with numbers and facts instead
  of opinions: a blind fact sheet, a rubric frozen before research, evidence
  whose quotes and numbers are checked on the source page by code, base-rate
  priors for every estimate, a Monte Carlo of the unit economics, a blind judge
  whose scores are capped by evidence strength, and a verdict computed by code
  (KILL / PIVOT / TEST / GO with a confidence level) plus the cheapest real-world
  experiment to run next. Works for desktop, mobile and web software, B2B and
  B2C, one country or global, from a raw idea or from existing research. Use when
  the user says "valuta questa idea", "evaluate this idea", "is this worth
  building", "should I build this", "/idea-valuta", or gives an idea to assess.
argument-hint: "[--quick | --full] <idea text, or path to a folder of documents>"
---

# idea-valuta

The orchestrator. It runs the evaluation pipeline in order and stops at the first
step that needs the user. Every step writes files into the idea folder; every
number in the verdict traces to a file.

What the user typed after `/idea-valuta`: `$ARGUMENTS`

## Ground rules (read once, apply everywhere)

1. **Separate what is known from what is believed.** The user's statements are
   claims (grade D) until a source confirms them. Your own knowledge is never a
   source: if a number matters, find it on a page and register it as a fact.
2. **The verdict is computed, not written.** Never state or imply a verdict that
   `ik.py verdict` did not produce. Never round a failing number into a passing one.
3. **Do not argue the user into or out of the idea.** If the user disagrees with
   the verdict, the only route is new evidence and a new run, never a re-score.
4. **Look for disconfirming evidence as hard as for confirming evidence.**
5. Reports to the user are in Italian. Files and prompts stay as the tools write them.

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
```

If `${CLAUDE_SKILL_DIR}` is not expanded, use the base directory Claude Code
printed for this skill and go up one level to `idea-lib/ik.py`. Python 3.8+,
standard library only. Idea folders live in `ideas/` in the current project
(a private repo the user keeps for ideas). `$IK --help` lists every command.

## Modes

| mode | when | data | time |
| --- | --- | --- | --- |
| `--quick` (default) | raw idea, first screen | 2-3 collectors that fit the archetype, 8-15 facts, no market model | 20-40 min |
| `--full` | idea that survived quick, or already researched | all fitting collectors, voice themes, bottom-up market, 30-60 facts | 1-2 h |

The simulated buyer panel and the multi-model jury are not built yet: in this
version the judge is one blind Claude sub-agent. Say this once when running `--full`.

## The pipeline

Run `$IK status ideas/<slug>` at any point to see what is done and what is next.
Resume from the first unchecked step; never redo a frozen step.

1. **Intake** (skill `idea-intake`): `$IK new "<title>"`, then write the blind
   sheet `idea.json` and the founder's `claims.jsonl`; `$IK lint` must print `ok`.
   Ask the user at most once, at most three questions, only for required fields.
2. **Goal and pre-registration**: if `ideas/config.json` has no `default_goal`
   and the idea has no `input/goal.json`, ask the user one question: the monthly
   revenue (or profit) they need, and by which month. Write it to
   `input/goal.json` as `{"metric": "revenue", "month": 24, "value": 3000}`.
   Then `$IK prereg ideas/<slug> --mode quick|full`. From here on the rubric,
   weights, thresholds and goal cannot change for this run.
3. **Collected data** (skill `idea-collect`): run the free sources that fit the
   archetype, then promote or reject every candidate with a reason. In quick
   mode, 2-3 sources (e.g. `trends` or `wikipedia`, plus `itunes`/`gplay` for
   apps or `hn`/`github` for software); in full mode, all that fit plus the
   voice themes.
4. **Evidence from pages** (skill `idea-evidence`): web research for what the
   collectors cannot measure (competitor prices, surveys, regulation), facts
   added with `$IK evidence add` and checked with `$IK evidence verify`. Facts
   that fail verification stay grade D; do not delete them, and do not "fix" a
   quote to make it pass unless you re-read the page.
5. **Market** (skill `idea-market`, full mode): bottom-up `market.json`, then
   `$IK market`.
6. **Economics** (skill `idea-economics`): write `assumptions.json` from facts and
   base rates, then `$IK econ`.
7. **Blind judgment and verdict** (skill `idea-verdict`): `$IK brief`, a judge
   sub-agent writes `judge/scores.json`, then `$IK verdict`.
8. **Report to the user**, in Italian, short:
   - the verdict line exactly as `verdict.md` states it (verdict, score, confidence);
   - the two or three criteria that decided it, each with its strongest fact;
   - any kill threshold that fired, word for word;
   - what share of the evidence is verified A/B, and what is still hypothesis;
   - which data sources failed or were skipped, if any;
   - the next experiment and its pre-set pass threshold;
   - where the files are (`ideas/<slug>/verdict.md`, `economics.md`).

Before step 3 in `--full` mode, tell the user roughly how long it will take.

## When the network is blocked

`ik.py evidence verify` needs to reach the source pages. If every fact comes back
`unreachable` (some cloud sandboxes block outbound sites), say so plainly: the
verdict will treat all evidence as grade D and confidence will be low. The user
can re-run `$IK evidence verify ideas/<slug>` and `$IK verdict ideas/<slug>` on
their own machine; or save a page's HTML as `<fact id>.html` in a folder and pass
`--html-dir` (useful for pages behind JavaScript or logins).

## A new run

After a real-world experiment, new evidence, or a new rubric version:
`$IK prereg ideas/<slug> --new-run --mode ...` archives the previous run under
`runs/` and starts clean; facts and claims are kept. Results of the user's own
experiments are added as `source_type: primary_data` facts with the URL of the
data (a sheet, an analytics export) and the exact figure as quote.

## Output

`ideas/<slug>/`: `idea.json`, `claims.jsonl`, `prereg.json`, `evidence.jsonl`,
`data/` (raw responses, candidates, voice), `market.json`, `market.md`,
`assumptions.json`, `economics.json`, `economics.md`, `judge/brief.md`,
`judge/scores.json`, `verdict.json`, `verdict.md`, and `input/` (private notes,
never shown to the judge).
