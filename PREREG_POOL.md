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
