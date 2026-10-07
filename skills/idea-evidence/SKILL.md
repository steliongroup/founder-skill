---
name: idea-evidence
description: >-
  Collects the evidence for an idea evaluation and registers each fact with its
  verbatim quote, URL, publisher, date and source type, so that code can fetch the
  page and confirm the quote and the number are really there. Searches for
  disconfirming evidence as hard as for confirming evidence, covers every rubric
  criterion (problem, demand, market, competition, willingness to pay,
  distribution, feasibility) and the inputs the economics needs. Grades sources
  A to D. Use inside /idea-valuta after pre-registration, or when the user says
  "cerca prove", "find evidence", "research this idea", "verify these sources".
argument-hint: "ideas/<slug>"
---

# idea-evidence

The rule this whole pack rests on: **a number counts only if code found it on the
page**. Your memory, a summary, or a plausible figure is not evidence. This skill
finds pages, copies the exact sentence, and lets `ik.py` check it.

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
$IK evidence add ideas/<slug> < facts.json      # one object or a list
$IK evidence verify ideas/<slug>                # fetch pages, check quotes and numbers
$IK evidence list ideas/<slug>
```

Pre-registration (`$IK prereg`) must already exist: research starts after the
criteria are frozen.

## What to look for

Read `ideas/<slug>/idea.json` (not the private notes). For each criterion, search
both ways. Budget: quick mode 8-15 facts and about 15 searches; full mode 30-60
facts.

| criterion | confirming | disconfirming |
| --- | --- | --- |
| problem | surveys or studies of the segment, recurring complaints in reviews and forums | evidence that buyers do not care, or that existing tools already solve it well |
| demand | search interest, traffic or downloads of alternatives, community size and activity | declining interest, dead communities, failed products ("shut down", "post-mortem") |
| market | official counts of the target (businesses by sector and size, population by segment and country), adoption rates | small or shrinking counts |
| competition | competitor list with prices, ratings, review counts, traction proxies | strong incumbents with good reviews at the same price; free alternatives |
| willingness to pay | competitor price pages, what buyers pay today for workarounds | "should be free" sentiment, price complaints, free tools that are good enough |
| distribution | where buyers gather (communities, marketplaces, search), channel costs | channels that are saturated or cost more than a customer is worth |
| feasibility | components and APIs that exist, regulation that applies | platform policies, regulation or technical limits that block it |

For the economics, look specifically for: competitor prices (company pages),
conversion and churn figures for this product type, costs of the main variable
inputs (API prices, hosting, payment fees from the provider's own page).

Use web search and fetch the pages. Product pages and official statistics beat
articles about them. When two sources report the same quantity, give both the
same `claim_key` (e.g. `late_payment_share`) so code can count them as
independent confirmations.

## How to register a fact

```json
{
  "claim": "Share of EU freelancers with at least one late invoice in 2025",
  "value": 0.62, "unit": "fraction",
  "url": "https://...",
  "quote": "62% of respondents had at least one invoice paid late in the last 12 months",
  "publisher": "Name of the organisation that published it",
  "source_type": "industry_report",
  "date": "2025-05",
  "sample_size": 1200,
  "claim_key": "late_payment_share",
  "criteria": ["problem"]
}
```

- `quote` is copied **verbatim** from the fetched page, one or two sentences,
  including the number. Never paraphrase, never merge sentences, never fix typos.
- `value` only if the number is in the quote. A percentage can be given as 0.62
  or 62 (unit "percent"); both match "62%".
- `source_type` sets the default grade:

| source_type | grade | use for |
| --- | :---: | --- |
| official_stat, primary_data, company_page, app_store | A | statistics offices, the user's own experiment data, a company's own page about itself, store listings |
| academic, industry_report, review_platform | B | studies and benchmarks with a stated sample; individual public reviews |
| news, forum, blog, aggregator, vendor_marketing | C | articles, Reddit/HN posts, summaries of other sources, vendors sizing their own market |
| other | D | anything else |

- You may move a grade one step with `"grade": "B", "grade_reason": "..."` (e.g. a
  blog that publishes its raw survey data). The tool refuses bigger moves.
- `date` is when the source was published (YYYY or YYYY-MM). Sources older than
  3 years lose one grade.

## Verify

```bash
$IK evidence verify ideas/<slug>
```

Statuses: `ok`; `quote_not_found` (re-read the page and copy the exact sentence,
or drop the fact); `value_not_in_quote` (the number is not in your quote);
`unreachable` (network, PDF, JavaScript page). For a page the tool cannot read,
save its HTML or text as `<fact id>.html` / `.txt` in a folder and run
`$IK evidence verify ideas/<slug> --ids F007 --html-dir <folder>`; say in the
report which facts were verified from saved copies.

Do not delete facts that failed: they stay as grade D, and the record of what
could not be confirmed is part of the result.

## Never

- Never register a number you did not read on the page in this session.
- Never quote a page you did not fetch.
- Never present a vendor's market-size press release as a market size (it is
  `vendor_marketing`, grade C).
- Never scrape against a site's terms or log into anything on the user's behalf.

## Output

`ideas/<slug>/evidence.jsonl`. Tell the user how many facts were found per
criterion and how many verified at A/B. Next: `idea-economics`.
