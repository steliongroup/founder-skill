---
name: idea-collect
description: >-
  Collects measured data about an idea from free public sources, with code
  reading every number: search demand (Wikipedia pageviews, Google Trends,
  autocomplete), competitors and traction (App Store, Google Play, GitHub, Hacker
  News, domain age and Tranco rank), buyers' own words (store reviews, HN and
  YouTube comments, Stack Exchange) and official market counts (World Bank,
  Eurostat). Results become candidates that must each be promoted to evidence
  or rejected with a reason, so unfavourable data cannot silently disappear.
  Use inside /idea-valuta, or when the user says "raccogli dati", "collect data",
  "check demand", "find competitors", "what do users complain about".
argument-hint: "ideas/<slug>"
---

# idea-collect

The collectors replace guesses with counts. Code calls the source, stores the
raw response with its hash, and computes each number. You choose what to ask
(keywords, countries, apps) and decide what is relevant; you never type a value.

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
$IK collect --list                       # the sources
$IK collect <source> ideas/<slug> [options]
$IK candidates list ideas/<slug> --pending
$IK candidates promote ideas/<slug> K001,K004 --criteria demand
$IK candidates reject ideas/<slug> K002,K003 --reason "a photo editor, not an invoicing tool"
$IK voice list ideas/<slug> --max-rating 3
$IK voice themes ideas/<slug>
$IK voice promote ideas/<slug> V003,V011 --criteria problem
```

Pre-registration must exist first. Responses are cached for 30 days under
`ideas/<slug>/data/raw/`; every call, failed or not, is in
`data/collect-log.jsonl`, and the verdict lists the sources that failed.

## Optional extras (free)

| need | how |
| --- | --- |
| Google Trends | `pip install trendspy` (unofficial; may hit rate limits) |
| Google Play | `pip install google-play-scraper` |
| YouTube | env `YOUTUBE_API_KEY` (free key, Google Cloud console) |
| higher GitHub / Stack Exchange limits | env `GITHUB_TOKEN`, `STACKEXCHANGE_KEY` |
| Wikimedia etiquette | env `IDEAKIT_CONTACT` (an email or URL added to the User-Agent; Wikimedia asks for one) |

A missing extra is logged as skipped; say so in the report, do not substitute
numbers from memory.

## Step 1: choose the queries (before looking at any result)

From `idea.json`, write 3 to 6 search phrases a buyer would type, in the
languages of the target countries, and the names of 3 to 8 known alternatives.
Use `$IK collect autocomplete ideas/<slug> --q "<seed>" --lang it --country it`
to discover real phrasing (saved to `data/keywords.json`; it produces no
numbers). Write the final list into `ideas/<slug>/data/queries.md` with one line
on why each was chosen. Do not change the list after seeing results unless a
query proves to be about something else, and note it there.

## Step 2: run the sources that fit the archetype

| archetype | demand | competitors and traction | voice | market |
| --- | --- | --- | --- | --- |
| B2C mobile app | `trends`, `wikipedia` | `itunes`, `gplay` | `appreviews` (top 3 competitors), `gplay --review-apps 3` | `worldbank` (population, internet users) |
| B2C web app | `trends`, `wikipedia`, `youtube` | `hn`, `domain` (for each competitor site) | `youtube`, `hn` comments | `worldbank` |
| B2B / prosumer software | `trends`, `wikipedia`, `hn` | `github`, `hn`, `domain`, `itunes` if mobile | `hn`, `stackexchange`, store reviews of competitors | `eurostat` (enterprises by NACE sector and size), `worldbank` |
| developer tools | `hn`, `github`, `stackexchange` | `github`, `hn` | `hn`, `stackexchange` | sector counts if any |

Examples:

```bash
$IK collect wikipedia ideas/x --article "Invoice" --lang en
$IK collect trends ideas/x --keywords "invoice reminder,payment reminder" --geo IT
$IK collect itunes ideas/x --q "invoice reminder" --country it
$IK collect appreviews ideas/x --app-id 123456789 --country it
$IK collect hn ideas/x --q "late payments freelancer"
$IK collect domain ideas/x --domain competitor.com
$IK collect worldbank ideas/x --countries IT,DE --indicator internet_users_pct
$IK collect eurostat ideas/x --dataset sbs_sc_ovw --countries IT,DE --filter nace_r2=M --filter size_emp=0-9 --unit enterprises
```

Eurostat codes vary by dataset. Find the dataset and dimension codes in the
Eurostat data browser first; if a call returns no values, fix the codes rather
than switching to a number from an article.

## Step 3: decide every candidate

`$IK candidates list ideas/<slug> --pending`. For each candidate decide only one
thing: **is this data about this idea's buyers, alternatives or market?**

- Relevant: promote it, whether it helps or hurts the idea. Low traction for
  competitors, falling interest, a tiny count: all of it goes in.
- Not relevant (homonym, different category, wrong country): reject with a
  specific reason.

The verdict refuses to run while candidates are pending, and it reports how many
were rejected. A rejection reason like "not useful" is not a reason.

## Step 4: the voice corpus

`$IK voice list ideas/<slug> --max-rating 3` shows the collected texts. Then:

1. Write `ideas/<slug>/data/voice-tags.json`: a short list of themes and, for
   EVERY listed item, the themes it mentions (`[]` if none):
   `{"themes": {"price": "price too high for solo users"}, "tags": {"V001": ["price"], "V002": []}}`
2. `$IK voice themes ideas/<slug>` counts them (code) and adds one candidate per
   theme. These counts are grade C because the tagging is yours; decide them
   like any candidate.
3. Promote a few individual texts that state a theme clearly
   (`$IK voice promote`): they become grade B (store reviews) or C (forums)
   facts, quoted exactly as collected.

Tag what the text says, not what would support the idea. Praise for a
competitor is a theme too.

## Output

`ideas/<slug>/data/` (raw responses, log, candidates, voice, keywords,
competitors) and new facts in `evidence.jsonl`. Next: `idea-market` for the
bottom-up market, then `idea-economics`.
