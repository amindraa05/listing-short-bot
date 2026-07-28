# Pre-registration — Bybit replication

**Written 2026-07-28, after enumerating the sample and BEFORE computing a single return.**
Everything below rests on metadata only: symbol lists, listing timestamps, perp
availability, data coverage, and token overlap. No P&L existed when this was written.

The rule being tested was frozen earlier and is already in this repository's git history
(`PREREG_ARMS.md`, committed before this dataset was touched). That timestamped freeze is
what makes a historical replication legitimate rather than another sweep.

## The idea, and why it is the right one

The Binance sample is spent. All 115 events were used to sweep the entry hour, pick the
exits and repair filters, so nothing in it can serve as a clean test any more. The operator
proposed the correct remedy: run the **same frozen rule** against **new spot listings on a
different exchange**. Only the signal source changes; the rule, the exits and the execution
venue stay identical, which isolates the variable.

## What the enumeration found, and why it hurts

**1. The samples overlap 64%.** Of 109 Bybit events with a Gate perp by T+18h, **70 are the
same tokens already in the Binance study**, and 48 of those listed within 24 hours of each
other. A shared token is not an independent observation — it is the same asset on the same
days, so it cannot confirm anything the Binance sample did not already contain.

**Genuinely fresh tokens: 39.**

**2. The price series has to come from Bybit spot, not the Gate perp.** Gate's 1h
candlestick history only reaches back about 2,000 hours (~83 days), so the perp that would
actually be traded has no retrievable history for events this old. This matters more than it
looks, because the Binance study's own two pricing sources did **not** agree as closely as
its dashboard claims:

| priced on | n | mean | t |
|---|---|---|---|
| Gate perp | 68 | **+3.20%** | 1.92 |
| Binance spot | 47 | **+1.99%** | 0.86 |

A spot-priced replication should therefore be judged against roughly **+2%**, not the
headline +2.71%. Stating that now, before seeing the result, so it cannot be chosen later.

**3. Consequence: this test is underpowered and cannot confirm anything.** With the measured
dispersion of 14.6pp, at n = 39 the expected t is:

| if the true mean is | expected t at n=39 |
|---|---|
| +1.99% (the spot-priced benchmark) | **0.85** |
| +2.71% (the headline) | **1.16** |
| +4.86% (the t18 figure) | **2.08** |

Against a bar of 2.24 for two pre-declared arms, only the most optimistic case even
approaches significance. **This experiment is a refutation test, not a confirmation test,**
and it is being run anyway because a refutation would be worth having cheaply.

## The test, frozen

Unchanged from `PREREG_ARMS.md`: short only, TP 15%, SL 15%, max hold 72h, 1×, entry at
T+12h (`t12`) and T+18h (`t18`) after the **first traded hour**, a Gate perpetual required
to exist by that arm's entry hour, 0.30% assumed spread and 0.075% taker each side, and the
liquidation guard at +95%.

Changed, and only because it is forced:

- **signal**: a new USDT spot pair on Bybit rather than Binance
- **price series**: Bybit spot 1h candles
- **anchor**: earliest daily candle, then the earliest hourly candle inside that day — the
  same "first traded HOUR, never midnight" convention the Binance work had to be corrected
  to
- **window**: listings inside the last 730 days

## Samples, declared in advance

| | n | independent? |
|---|---|---|
| **PRIMARY — fresh tokens** (never in the Binance study) | 39 before coverage loss | yes |
| SECONDARY — shared tokens, anchored to the Bybit listing | 70 | **no** |
| tertiary — all eligible Bybit events | 109 | no |

Only the primary can support a claim. The secondary is reported because it answers a
different and narrower question: for the 30 tokens Bybit listed **before** Binance did, the
Binance study's anchor was late by construction, and it is worth knowing whether anchoring
to the true first listing changes the outcome. That is a check on the original study, not
evidence for the edge.

Events lost to missing or gappy Bybit hourly data will be reported as a count, not silently
dropped. Coverage is judged **from the entry hour onward**, not from the listing — judging
it from the listing was a bug in the Binance pipeline that wrongly excluded 24 valid events.

## What each outcome will be taken to mean

Declared now so that no result can be reinterpreted after the fact.

- **t ≥ 2.24 on the primary sample** — strong support. Unlikely on power grounds, so if it
  happens the sample should be checked for a fluke before being believed.
- **mean positive, t below 2.24** — consistent with the Binance result and confirms nothing.
  This is the expected outcome if the edge is real, and it must not be reported as support.
- **mean at or near zero** — mild evidence against. If the true mean were +1.99%, the chance
  of observing a mean at or below zero across 39 events is about 20%, so this outcome is not
  rare enough to settle anything either.
- **mean clearly negative, or win rate at or below 45%** — evidence against the edge, and
  the most informative thing this experiment can produce.
- **a large disagreement between the arms** — treated as noise, not signal. At n=39 the
  arms cannot be separated.

## What would make this experiment actually decisive

Pooling fresh listings across several venues at once — Bybit, OKX, KuCoin and Gate spot —
deduplicated against both the Binance sample and each other. The bot already carries clients
for all of those. That is the route to a sample large enough to confirm rather than only to
refute, and it is the recommended next step regardless of what the 39 events show.

## Known ways this could still be fooling us

- **Survivorship.** Only pairs currently `status: Trading` on Bybit are enumerated. A token
  listed and then delisted inside the window is invisible, and delisted tokens are
  disproportionately the ones that collapsed — which is the direction this strategy profits
  from. **The primary sample is therefore biased against the edge**, which makes a positive
  result more trustworthy and a negative one less so.
- **Spot, not perp.** The trade is a perpetual short; the series is spot. The Binance study
  found spot-priced events ran 1.2pp weaker than perp-priced ones and never established why.
- **One market regime.** The same objection as the original: 730 days, one cycle.

---

# RESULT — run 2026-07-28, after the above was committed

## Primary sample: the edge is not there

| arm | n | mean | median | win | t | 95% CI |
|---|---|---|---|---|---|---|
| **t12** (T+12h) | 39 | **−3.72%** | **−15.32%** | **38.5%** | −1.66 | −8.13 … +0.68 |
| **t18** (T+18h) | 39 | −1.55% | −2.46% | 48.7% | −0.68 | −5.98 … +2.89 |

Two pre-registered thresholds were both crossed: **the mean is clearly negative**, and the
**win rate of 38.5% is below the 40% stop signal** that this project agreed in advance is
the point to abandon an arm.

**The modal outcome inverted.** The median trade in the Binance sample was **+14.77%** — the
take profit. The median fresh Bybit trade is **−15.32%** — the stop. It is not that the edge
shrank; the typical trade changed sides.

How unlikely is this if the edge were real:

| under the hypothesis that the true mean is | P(observing a mean ≤ −3.72%) |
|---|---|
| +1.99%, the spot-priced Binance benchmark | **0.55%** |
| +2.71%, the headline | **0.21%** |
| 0.00%, no edge at all | 4.88% |

And on win rate alone: P(≤15 wins in 39 | p = 0.626) = **0.19%**.

The dispersion matches — sd 14.03 against the Binance sample's 14.61 — so this is not a
strange sample producing noise. It is the same kind of distribution with the sign flipped.

## The secondary sample reproduces the Binance result exactly, which is the tell

| sample | n | mean | median | win | t |
|---|---|---|---|---|---|
| shared tokens (already in the Binance study) | 69 | **+2.06%** | +14.72% | 59.4% | +1.17 |
| fresh tokens | 39 | **−3.72%** | −15.32% | 38.5% | −1.66 |

Difference **+5.78pp at t 2.02**. The edge is present on the tokens the original study used
and absent on tokens it never saw. That is the signature of a sample-specific result rather
than a mechanism.

## Checks run before believing it

- **Established tokens contaminating the fresh sample.** 7 of 39 were tokens whose perpetual
  already existed by more than 30 days at the Bybit listing — VET (1,568 days), VTHO (427),
  RENDER, HYPE — so Bybit merely added a venue. Removing them changes almost nothing:
  **−3.50%, win 40.6%** on the 32 genuinely new tokens.
- **Spot versus perp pricing.** Adding back the full 1.21pp that spot pricing cost in the
  Binance study still leaves **−2.51%**.
- **Time split.** First half −5.66% (win 31.6%), second half −1.89% (win 45.0%). Negative in
  both, so it is not one bad window.
- **Both arms.** t18 is also negative, so it is not an entry-hour artefact.
- **Adverse excursion.** Median MAE 22.4% on fresh tokens against 13.7% on shared, and 19 of
  32 fresh events stopped out. These tokens keep running up after the entry.

## What this does and does not refute

**Refuted:** the general claim that *a new spot listing on a major exchange pumps and then
falls hard enough to short*. On clean data it does the opposite.

**Not refuted, but now unsupported:** the narrower claim that **Binance listings specifically**
behave that way. A Binance listing is a far larger liquidity event than a Bybit one, and the
adverse-excursion gap above is consistent with fresh Bybit tokens simply continuing to pump.
That escape route is real — but it is now a hypothesis with **no clean evidence behind it at
all**, because the Binance sample is spent and this was the replication.

**The honest reading against the edge is weaker than the numbers suggest, in one specific
way.** Survivorship works in the edge's favour here: only pairs still listed on Bybit were
enumerated, and delisted tokens are disproportionately the ones that collapsed — exactly the
trades a short would have won. The pre-registration named this before the run. So the true
fresh-sample mean is probably somewhat better than −3.72%. It would have to be better by
almost 6pp to reach the Binance figure.

## Consequence

The paper forward test keeps running, because it costs nothing and it is the only remaining
clean test of the narrow Binance-specific claim. But the prior behind it should now be
treated as much weaker than the dashboard's framing implies, and **no real capital should go
near this** until the forward test has produced its own evidence.

