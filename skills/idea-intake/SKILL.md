---
name: idea-intake
description: >-
  Turns a raw idea, or a folder of existing research documents, into a blind,
  neutral fact sheet (idea.json) that judges will see, plus a list of the
  founder's own assertions (claims.jsonl) kept as unverified hypotheses. Strips
  enthusiasm, first person and the founder's identity, classifies the archetype
  (B2B or B2C, platform, countries, revenue model), and pulls sourced facts out of
  existing documents so they can be verified instead of trusted. Use as the first
  step of /idea-valuta, or when the user says "prepara la scheda dell'idea",
  "intake", "import my research", or hands over documents about an idea.
argument-hint: "<idea text, or path to documents>"
---

# idea-intake

The judges never meet the founder. They see one page, written in the third
person, with no adjectives that sell. This skill writes that page and puts
everything the founder believes into a separate list of claims to be tested.

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
```

## Step 1: the folder

```bash
$IK new "<a private working title>"     # creates ideas/<slug>/ with a random codename
```

The title and the codename are in `ideas/<slug>/input/private.json`. Put the
user's raw text in `input/idea.md` and copy or link any documents into `input/`.
Nothing in `input/` is ever shown to a judge.

## Step 2: read everything the user gave

Raw idea: read the text. Existing research: read the documents (large ones in
parts; a table of contents and the sections on problem, market, competitors,
prices and costs first). Do not summarize the documents' opinions as facts.

## Step 3: the blind sheet, idea.json

Write `ideas/<slug>/idea.json`, shape (example: `../idea-lib/examples/sample-idea/idea.json`):

| field | content |
| --- | --- |
| `codename` | from `input/private.json` |
| `one_liner` | what it is, for whom, in one neutral sentence |
| `problem` | the problem as the target buyer would describe it, no numbers you have not sourced |
| `solution` | what the product does, concretely |
| `target_segments` | list of `{name, description}`: who, where, how many invoices/users/hours, not adjectives |
| `archetype.market` | `b2c`, `b2b` or `b2b2c` (sold to businesses who serve consumers) |
| `archetype.platform` | list from `desktop`, `mobile`, `tablet`, `web`, `api`, `other` |
| `archetype.geo` | ISO country codes, or `["global"]` |
| `archetype.revenue_model` | `subscription`, `freemium`, `one_time`, `usage`, `ads`, `marketplace`, `service` |
| `price_hypothesis` | `{amount, currency, period}` with period `month`, `year` or `one_time` |
| `current_alternatives` | what buyers use today, including "nothing" and manual workarounds |
| `stage` | `raw` or `researched` |

Writing rules, enforced by `$IK lint`:
- Third person, present tense. No "I", "my", "we", "our", "io", "mio", "noi".
- No selling words: revolutionary, unique, best, innovative, game-changer,
  rivoluzionario, migliore, incredibile and the like. Describe, do not praise.
- The private title must not appear; use the codename.
- No market sizes, growth rates or statistics in the sheet: those are facts and
  go through `idea-evidence`.

If the name of the segment, the price, the platform or the geography is missing,
ask the user (one message, at most three questions). Never invent them; a
placeholder price is still a claim and is marked as one.

## Step 4: the claims, claims.jsonl

Every assertion the founder makes that could be true or false becomes one line:

```json
{"id": "C001", "text": "Most freelancers are paid late every month.", "type": "problem", "source": "founder", "grade": "D", "status": "hypothesis"}
```

`type` is one of problem, market, customer, competitor, traction, price, cost,
channel, other. `source` is `founder` or `document:<file name>`. Grade is always
D. Aim to capture the claims the idea depends on most: who has the problem, how
often, what they pay today, how big the market is, why competitors fail them,
which channel reaches them.

## Step 5: facts already in the documents

When a document cites a source with a URL for a number or a quote, that is a
candidate fact, not a fact. Pass it to `idea-evidence` with the URL, so code can
check it on the page. A document's statement without a source is a claim.

## Step 6: check

```bash
$IK lint ideas/<slug>
```

It must print `ok`. Fix every problem it lists; do not work around the word list
with synonyms that still praise.

## Output

`ideas/<slug>/idea.json`, `claims.jsonl`, `input/` (private). Next: the goal and
`$IK prereg` (see `/idea-valuta` step 2), then `idea-evidence`.
