# Pre-registration — Coinbase test of the surviving cohort

**Written 2026-07-28, after enumerating the sample and BEFORE computing a single return.**
Metadata only: product lists, listing dates from earliest daily candles, Gate perp launch
times, and overlap with the two runs already published. No P&L existed when this was written.

## Why this is not just a fifth venue

The pooled run refuted the general claim. But the Binance edge never lived in the general
claim — it lived in **one cohort**, and that split was published on the research dashboard
before any of these replications were built:

| cohort | n | mean | t | win |
|---|---|---|---|---|
| **perp_after** — no perpetual existed yet at the listing | 37 | **+8.53%** | **+4.36** | 81.1% |
| perp_before — established token arriving on the venue | 70 | +0.47% | +0.28 | 54.3% |
| near_simultaneous | 8 | −4.66% | −0.55 | 50.0% |

70 of the 135 Binance events — the established tokens — measured **+0.47%**, which is nothing.
So the thesis is not "a new listing falls". It is **"a token so new that no perpetual exists
yet falls after its listing pump"**.

That suggests a mechanism worth naming: with no perpetual in existence **nobody can short the
pump**, so it overshoots, and the arrival of a perp hours later is what lets the air out.

The pooled run could barely test it. Only 8 of its 92 events were perp_after, because on
Gate, KuCoin and Bybit the perpetual is usually launched at the same time as the spot pair —
67 of 92 fell in the near_simultaneous bucket. **The pooled refutation is valid for the
general claim and close to silent on the specific one.** That is stated here because it is a
correction to how the pooled result was first reported.

Coinbase turns out to have a real population of the right kind: **40 perp_after events, 30 of
them passing the frozen rule.** Comparable to Binance's 37.

## Independence, measured rather than assumed

Of those 30:

| | n | status |
|---|---|---|
| token never in the Binance study | **15** | clean |
| same token, Coinbase listing ≥3 days from the Binance one | 4 | weakly independent — different date, different 72h window, shares only the asset's character |
| same token, within 3 days of the Binance listing | 11 | **not independent**, the price paths overlap |

This is a different contamination profile from the Bybit run, where 48 of 70 shared tokens
listed within 24 hours of Binance. Here the split is explicit and the primary excludes every
shared token outright.

## Power, stated before the result

The reason 15 events is worth running is that the effect being tested is large. With the
measured dispersion of 14.61pp:

| n | expected t if the true mean is +8.53% | if +2.71% |
|---|---|---|
| 15 (primary) | **2.26** | 0.72 |
| 19 (primary + weakly independent) | **2.54** | 0.81 |
| 30 (contaminated, reported only for completeness) | 3.20 | 1.02 |

So this test **can** detect the cohort effect if it is real, which neither previous run could.
It cannot detect a merely ordinary +2.71%.

## The bar

This is the **third** out-of-sample replication attempted in this session — Bybit, the
four-venue pool, and now Coinbase — each with two arms. Six configurations:

`bar = 2.0 + 0.35 × ln(6) = 2.63`

Stricter than the 2.24 the earlier runs used, deliberately, because searching for a venue
where the result comes out favourable is itself a search and must be charged for.

## Method, frozen

Identical to `PREREG_ARMS.md`: short only, TP 15%, SL 15%, max hold 72h, 1×, entry T+12h
(`t12`) and T+18h (`t18`) after the first traded hour, a Gate perpetual required by that arm's
entry hour, 0.30% assumed spread, 0.075% taker per side, liquidation guard at +95%, adverse
checked before favourable, gap-through-stop filled at the open, coverage judged from the entry
hour onward.

Price series: **Coinbase spot hourly candles**, the signal venue, as in both previous runs.
Coinbase caps candles at 300 per request, and the 110-hour window fits in one call.

## Samples declared in advance

| | n | what it can support |
|---|---|---|
| **PRIMARY — perp_after, token never in the Binance study** | 15 | the claim |
| SECONDARY — primary plus the 4 separated by ≥3 days | 19 | the claim, slightly weakened |
| context — all 30 perp_after | 30 | nothing; 11 overlap the Binance windows |
| context — all 102 eligible Coinbase listings, all cohorts | 102 | tests the general claim again, already refuted |

## What each outcome will be taken to mean

- **primary mean strongly positive with t ≥ 2.63** — the cohort hypothesis survives its first
  real out-of-sample test. That would not resurrect the general thesis, which is refuted; it
  would mean the narrow one is alive and the forward test matters a great deal.
- **primary positive, t below 2.63** — consistent with the cohort effect, confirms nothing.
  With n=15 this is a likely outcome even if the effect is real, and it must be reported as
  inconclusive.
- **primary near zero or negative** — taken with the two published refutations, the thesis is
  finished in every form and the paper forward test becomes a formality.
- **primary and secondary disagreeing** — treated as noise at these sample sizes.
- **the all-cohort Coinbase sample being positive while the perp_after primary is not** —
  would be treated as a warning that the cohort story is itself an artefact, not as support.

## Known ways this could still be fooling us

- **Survivorship, favouring the edge.** Only currently-online Coinbase products are
  enumerated; delisted ones are invisible and are disproportionately the collapses a short
  would have won.
- **Coinbase spot is not the Gate perp.** The trade is a perpetual short. Prior runs showed
  pricing venue is worth roughly 1.2pp.
- **Coinbase listings are announced in advance.** Binance's are too, but Coinbase's roadmap
  announcements are famously front-run, so the pump may already be spent before the listing
  hour that anchors this test. If the mechanism needs the pump to happen *after* the anchor,
  this venue may understate it. Unresolvable here, and named now rather than later.
- **n=15.** Small enough that a single event moves the mean by roughly 1pp.
- **One market regime.** 730 days.
