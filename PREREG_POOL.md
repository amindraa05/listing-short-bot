# Pre-registration — multi-venue pooled replication

**Written 2026-07-28, after enumerating the sample and BEFORE computing a single return.**
Metadata only: symbol lists, listing timestamps, perp availability, venue overlap. No P&L
existed when this was written. The rule it tests was frozen in `PREREG_ARMS.md`, committed to
this repository before any of these datasets was touched.

This extends `PREREG_BYBIT.md`. That run gave 39 fresh tokens and a negative result, and its
own pre-registration said 39 events could refute but never confirm. This is the fix it named.

## What an event is

**The token's first listing across the tracked venues** — Bybit, OKX, KuCoin, Gate spot — so
that a token is counted once and only once. A token listed on KuCoin in October and on OKX
the following April is one event, anchored to October.

That rule is not cosmetic. OKX reports `listTime` 2026-04-24 for GRASS while KuCoin and Gate
both say 2024-10-28. Taking the earliest is what stops a stale venue field from inventing a
listing eighteen months late.

## Enumeration, before any outcome

| | count |
|---|---|
| distinct tokens across the four venues | 2,231 |
| first listed inside the 730-day window | 1,280 |
| first-lister: Gate 870 · KuCoin 201 · Bybit 114 · OKX 95 | |
| never listed on Binance **at all** | 1,150 |
| a Gate perpetual exists by T+18h | 199 |
| **pooled fresh sample** (perp by T+18h, never on Binance) | **101** |
| of which already reported in the Bybit run | 22 |
| **genuinely new evidence beyond that run** | **79** |

Deduplication is against **all 467 Binance USDT listings on record**, not the 134 the Binance
study ended up using. A token the study looked at and then dropped for having no perp is still
a token it looked at, and reusing it would not be independent. This is stricter than the Bybit
run, which is why only 22 of that run's 39 survive here — the rest were either on Binance
outside the study's usable set, or got re-anchored to a venue that listed them earlier.

## Power, stated before the result

With the measured dispersion of 14.61pp, at n = 101:

| if the true mean is | expected t |
|---|---|
| +1.99%, the spot-priced Binance benchmark | **1.37** |
| +2.71%, the headline | **1.86** |
| +4.86%, the t18 figure | **3.34** |

Against the bar of 2.24 this **still cannot confirm the conservative case**, and saying so now
prevents a positive-but-insignificant result being dressed up later. What it can do, which 39
events could not, is separate a small positive edge from a clearly negative one with some
authority.

## Method, frozen

Identical to `PREREG_ARMS.md`: short only, TP 15%, SL 15%, max hold 72h, 1×, entry T+12h
(`t12`) and T+18h (`t18`) after the first traded hour, a Gate perpetual required by that arm's
entry hour, 0.30% assumed spread, 0.075% taker per side, liquidation guard at +95%, adverse
checked before favourable, gap-through-stop filled at the open.

Price series: the **anchor venue's own spot candles**, falling back in the fixed order
Bybit → OKX → KuCoin → Gate → Binance when the anchor venue has no usable history. Retention
was measured: Bybit, OKX and KuCoin reach past 730 days; Gate spot fails beyond roughly 365.
The pricing venue **will be recorded per event and results reported split by it**, because the
Binance study already showed this matters — its Gate-perp subset ran +3.20% against +1.99% for
its Binance-spot subset, a 1.2pp gap it never explained.

Coverage is judged **from the entry hour onward**, never from the listing. Judging it from the
listing was a bug in the Binance pipeline that wrongly excluded 24 valid events.

## Samples declared in advance

| | n | what it can support |
|---|---|---|
| **PRIMARY — pooled fresh** | 101 | the claim |
| **PRIMARY-NEW — pooled fresh excluding anything in the Bybit run** | 79 | the claim, independently of that run |
| secondary — by anchor venue | varies | robustness only, n too small per venue |
| secondary — by pricing venue | varies | robustness only |

Both primaries are declared because reporting only the 101 would quietly re-use the 22 already
published, and reporting only the 79 would discard valid events. They must agree; if they do
not, that disagreement is the finding.

## What each outcome will be taken to mean

- **t ≥ 2.24 positive on both primaries** — the strongest support this project has ever
  produced for the thesis, and grounds to revisit the Bybit refutation as a small-sample fluke.
- **positive but t below 2.24 on both** — consistent, confirms nothing, and must not be
  reported as support. Under the +2.71% hypothesis this is the single most likely outcome.
- **near zero** — the thesis is not worth capital, whatever its sign.
- **clearly negative, or win rate ≤ 45%** — taken together with the Bybit run, the general
  thesis is refuted on out-of-sample data and the project should stop.
- **the two primaries disagreeing materially** — treated as evidence that the pool is
  heterogeneous rather than as licence to pick the better one.

## Known ways this could still be fooling us

- **Survivorship, and it favours the edge.** Only pairs currently trading are enumerated.
  Tokens listed and then delisted are invisible, and delisted tokens are disproportionately
  the ones that collapsed — exactly the trades a short would have won. So the pooled mean is
  biased **downward**, and a negative result is correspondingly weaker evidence than it looks.
- **These are not Binance listings.** 870 of the 1,280 in-window tokens were first listed on
  Gate, which lists almost everything. A Gate or KuCoin listing is a far smaller liquidity
  event than a Binance one. If the mechanism needs a large captive audience arriving at once,
  this pool tests a different thing — and that is the one honest escape route left for the
  thesis. It cannot be resolved here; only the forward test on Binance listings can.
- **Spot, not perp.** The trade is a perpetual short and the series is spot.
- **One market regime.** 730 days, one cycle. Unchanged from every previous objection.

---

# RESULT — run 2026-07-28, after the above was committed

## Both primaries are negative, and they agree

| sample | arm | n | mean | median | win | t | 95% CI |
|---|---|---|---|---|---|---|---|
| **pooled fresh** | t12 | 92 | **−2.65%** | **−15.32%** | **43.5%** | −1.80 | −5.55 … +0.24 |
| **pooled fresh** | t18 | 93 | **−3.27%** | **−15.32%** | **40.9%** | **−2.24** | −6.13 … −0.41 |
| new evidence only | t12 | 65 | −2.01% | −5.51% | 46.2% | −1.16 | −5.41 … +1.38 |
| new evidence only | t18 | 65 | −2.59% | −15.32% | 43.1% | −1.49 | −5.99 … +0.81 |

The pre-registered refutation threshold was "clearly negative, **or win rate ≤ 45%**".
Both arms of the pooled sample are below 45%, and t18 reaches **−2.24**, the mirror image of
the bar. The two primaries agree in sign and roughly in size, which was the condition set in
advance for taking the pooled figure seriously.

How unlikely this is if the edge were real:

| | P(mean this low \| true +1.99%) | P(mean this low \| true +2.71%) | P(this few wins \| p=0.626) |
|---|---|---|---|
| t12 pooled, n 92 | **0.083%** | 0.014% | **0.015%** |
| t18 pooled, n 93 | **0.016%** | 0.002% | **0.002%** |
| t12 new only, n 65 | 1.04% | 0.32% | 0.51% |
| t18 new only, n 65 | 0.42% | 0.11% | 0.11% |

## Every robustness split points the same way

| split | n | mean | win |
|---|---|---|---|
| first half of the window | 46 | −2.30% | 45.7% |
| second half | 46 | −3.01% | 41.3% |
| priced on Bybit | 22 | −4.40% | 36.4% |
| priced on KuCoin | 37 | −2.88% | 40.5% |
| priced on Gate | 25 | −1.25% | 52.0% |
| priced on OKX | 8 | −1.22% | 50.0% |
| listed on ONE venue only | 35 | **−4.99%** | 37.1% |
| listed on 2+ venues | 57 | −1.22% | 47.4% |

Not one pricing venue and not one time half is positive. The only positive cell anywhere is
Gate-anchored events at +0.46% on n=28, t 0.18 — noise. The pattern that the more venues
listed a token the less badly it did is consistent with venue count proxying for token
quality, and even the 2+ venue group is negative.

## The mechanism, and it is the opposite of the thesis

| | target | stop | time | median MAE | would liquidate unstopped |
|---|---|---|---|---|---|
| Binance sample, n 115 | 61 | 39 | 15 | ~10% | 7 (6%) |
| pooled t12, n 92 | **33** | **49** | 10 | **22.1%** | **15 (16%)** |
| pooled t18, n 93 | 32 | 51 | 10 | 23.5% | 15 (16%) |

The exit mix inverted. In the Binance sample the take profit fired more often than the stop,
61 to 39. Here the stop fires more often, 49 to 33, the median trade goes 22% **against** a
short before it resolves, and 16% of events would have liquidated a 1× short outright. These
tokens do not pump and fall. They pump and keep going.

## The one hypothesis left standing, and how it now looks

The Binance sample and the pooled non-Binance sample differ by **+5.36pp at t 2.67** — they
are statistically distinguishable. Two readings fit:

**(a)** Binance listings really are a different event: a much larger captive audience arriving
at once, so the pump exhausts and reverses where a Gate or KuCoin listing simply drifts up.

**(b)** The Binance result was the artefact, and this is what the population actually looks like.

**(b) has the better support.** The Binance sample never cleared its own significance bar
(t 1.99 against 3.55), had no clean holdout left, and four measurement bugs were found inside
it — every one of which happened to improve the result. A run of favourable errors is itself
evidence about the direction of the undiscovered ones.

Reading (a) cannot be dismissed and cannot be tested here. Only the forward test on live
Binance listings can settle it, and that is what is running.

## Where survivorship leaves this

The pre-registration stated before the run that survivorship favours the edge: only currently
trading pairs were enumerated, and delisted tokens are disproportionately the ones that
collapsed — exactly what a short would have won. So the true pooled mean is probably better
than −2.65%. It would have to be better by **4.6pp** to reach the Binance figure, and by
2.7pp merely to reach zero.

## Verdict

**The general thesis is refuted on out-of-sample data.** A new spot listing on a major venue,
excluding Binance, does not fall after its pump often enough or far enough to short. Across
92 fresh tokens on four venues it does the opposite, with a probability under the edge
hypothesis of 0.08% or less.

What survives is only the narrow claim that **Binance listings specifically** behave
differently. That claim is now statistically distinguishable from the pooled result, which is
the strongest thing that can be said for it, and it has **no clean supporting evidence at
all**. The paper forward test continues because it costs nothing and is the only remaining
clean test of it. **No real capital should go near this.**

