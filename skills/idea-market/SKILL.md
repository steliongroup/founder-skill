---
name: idea-market
description: >-
  Sizes the reachable market of an idea bottom-up from counts instead of
  top-down from vendor reports: for each target segment, how many there are
  (official statistics or measured counts), what share can be reached, what share
  adopts this kind of solution, and what they would pay per year. Runs a Monte
  Carlo for the serviceable market (SAM) and computes what share of it the
  pre-registered revenue goal requires, with every input graded by its source.
  Use inside /idea-valuta, or when the user says "quanto è grande il mercato",
  "market size", "TAM SAM SOM", "is the market big enough".
argument-hint: "ideas/<slug>"
---

# idea-market

"The market is worth $40 billion" says nothing about whether this product can
reach its goal. The question this skill answers is narrower and checkable: how
many buyers can this product actually reach, what would they pay, and what share
of them does the goal require?

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
$IK market ideas/<slug>        # reads market.json, writes market-result.json and market.md
```

Pre-registration must exist (the goal comes from it).

## Step 1: the counts come first

For each target segment in `idea.json`, find a count before anything else:

| buyer | where the count comes from |
| --- | --- |
| businesses in the EU | Eurostat SBS: enterprises by NACE sector and size class (`$IK collect eurostat`) |
| businesses in the US | Census County Business Patterns (fetch the page, register as `official_stat`) |
| consumers | World Bank population and internet users (`$IK collect worldbank`), national statistics for age or occupation |
| professionals | national statistics offices, professional registers |
| users of an existing tool | that tool's own published numbers (company_page), store install buckets |

The count must be a fact in `evidence.jsonl` (promoted candidate or verified
page). A vendor's market-size report is grade C and is not a count.

## Step 2: write market.json

```json
{
 "currency": "EUR",
 "segments": [
  {"name": "Professional services firms, 0-9 employees, IT+DE",
   "count":           {"low": 1100000, "mode": 1213000, "high": 1213000, "source": "fact:F012"},
   "reachable_share": {"low": 0.05, "mode": 0.1, "high": 0.2, "source": "estimate", "note": "online, invoice digitally"},
   "adoption":        {"low": 0.1, "mode": 0.2, "high": 0.35, "source": "fact:F015", "note": "share using cloud accounting"},
   "price_annual":    {"low": 108, "mode": 144, "high": 180, "source": "fact:F002"}}
 ]
}
```

- `count`: how many exist in the target geography. Narrow it to the segment the
  product serves, and explain any narrowing in `note`.
- `reachable_share`: the share that the founder's channels and languages can
  reach. Usually an estimate; keep it wide and honest.
- `adoption`: the share that would use this kind of solution at all, from
  adoption statistics (e.g. Eurostat ICT usage) or competitor penetration.
- `price_annual`: the yearly price, from competitor pages and the price
  hypothesis.
- `source`: `fact:Fxxx`, `baserate:<id>`, `claim:Cxxx` or `estimate`, as in the
  economics.

## Step 3: run and read

`$IK market ideas/<slug>` writes `market.md`: SAM at P10/P50/P90, the share of it
the goal needs and the probability that it is under 5% and under 1%, and the
input grades. The judge's brief includes these computed lines for the market
criterion. If the goal needs more than a few percent of the reachable market,
that is the finding; do not widen the segments to make it smaller.

## Output

`ideas/<slug>/market.json`, `market-result.json`, `market.md`. Next:
`idea-economics`, then `idea-verdict`.
