---
name: idea-economics
description: >-
  Builds the unit economics of a software idea as ranges, not single guesses:
  price, conversion, churn, acquisition cost, variable and fixed costs, each
  input tied to a verified fact, a published base rate, a founder claim or an
  explicit estimate. Runs a Monte Carlo (P10/P50/P90) for revenue, paying
  customers, LTV:CAC, break-even month, cash needed and the probability of
  reaching the pre-registered goal, and clamps optimistic inputs that lack strong
  evidence back to their base rate. Use inside /idea-valuta, or when the user says
  "fai i numeri", "unit economics", "is this profitable", "break-even", "LTV CAC".
argument-hint: "ideas/<slug>"
---

# idea-economics

Founders' spreadsheets fail in the same place: the conversion rate and the churn
they type in. Here those come from published base rates unless a strong fact
says otherwise, and every input is a range.

## The tool

```bash
IK="python3 ${CLAUDE_SKILL_DIR}/../idea-lib/ik.py"
$IK baserates list                  # the priors, with source and grade
$IK baserates show <id>
$IK econ ideas/<slug>               # writes economics.json and economics.md
```

The goal comes from pre-registration (`prereg.json`); do not put a goal in
`assumptions.json` (the tool refuses it).

## Step 1: pick the model and the priors

`model`: `subscription` (also freemium with a paid tier, usage plans with a
monthly bill) or `one_time` (paid apps, lifetime licences). The funnel is
visitors, then signups (or installs), then paying customers.

Choose priors by archetype (`idea.json`):

| input | B2B or prosumer web, self-serve | B2C mobile app | trial with card |
| --- | --- | --- | --- |
| `visitor_to_signup` | `landing_signup_saas` | `landing_signup_all` (store page visit to install, if no better data) | `landing_signup_saas` |
| `signup_to_paid` | `freemium_to_paid_selfserve` or `trial_to_paid_no_card` | `mobile_install_to_paid` (or `mobile_hard_paywall_vs_freemium` for a hard paywall) | `trial_to_paid_card` |
| `monthly_churn` | `saas_monthly_churn_early` | `consumer_sub_monthly_churn` | `saas_monthly_churn_early` |

`visitor_to_signup`, `signup_to_paid` and (for subscriptions) `monthly_churn`
must name their `prior` from this table; the tool refuses them otherwise. Pick
the prior that matches the funnel honestly: a freemium product compared with
the card-required trial rate is a way of cheating the clamp.

`cac_paid` has no direct base rate. Without evidence, derive it from
`cac_payback_months`: low = 6, mode = 16, high = 24 months of contribution per
customer. Write `"source": "baserate:cac_payback_months"` and say in `note` that
it is derived. For a B2C app with tiny prices this is generous; flag that.

## Step 2: write assumptions.json

Shape (example: `../idea-lib/examples/sample-idea/assumptions.json`):

```json
{
 "currency": "EUR", "model": "subscription", "horizon_months": 36,
 "inputs": {
  "price": {"low": 9, "mode": 12, "high": 15, "source": "claim:C002", "note": "competitor A charges 15 (F002)"},
  "signup_to_paid": {"low": 0.01, "mode": 0.03, "high": 0.06, "source": "baserate:freemium_to_paid_selfserve",
                     "prior": "freemium_to_paid_selfserve"}
 }
}
```

Inputs: `price`, `payment_fee_pct`, `variable_cost_paying`, `variable_cost_free`,
`fixed_monthly`, `startup_cost`, `visitors_month1`, `visitor_growth_monthly`,
`visitor_to_signup`, `signup_to_paid`, `monthly_churn`, `free_user_monthly_churn`,
`paid_budget_monthly`, `cac_paid`. Fractions are 0-1 (3% = 0.03). `$IK econ`
lists any that are missing.

For each input:
- `source`: `fact:F003` (a verified fact; strongest), `baserate:<id>`,
  `claim:C002` (the founder said so), or `estimate` (your reasoning, written in
  `note`). Estimates and claims are grade D.
- `prior`: the base rate it should be compared with, whenever one exists. If the
  input's source is weaker than A/B and its mode is outside the prior's range,
  the tool clamps it into the range and reports it. This is deliberate: an
  optimistic conversion needs evidence, not conviction.
- Ranges should be honest: wide where nothing is known. A range of 0.04-0.05 for
  an unmeasured conversion is false precision.
- Variable costs: price them from providers' own pages (API price per token,
  hosting, payment processor fee) and register those pages as facts.
- `visitors_month1`: what the founder can actually bring in month 1 from a named
  channel, not a hope. If unknown, a wide range and source `estimate`.

## Step 3: run and read

```bash
$IK econ ideas/<slug>
```

Read `economics.md`: the P10/P50/P90 table, the probability of break-even and of
the goal, the inputs table with grades, the clamped inputs, and the inputs that
move the result most. Do not re-run with friendlier inputs to get a better
answer: a change of inputs needs a new fact, and the reason goes in `note`.

## Output

`ideas/<slug>/assumptions.json`, `economics.json`, `economics.md`. Next:
`idea-verdict`.
