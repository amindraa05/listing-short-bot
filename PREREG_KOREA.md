# Pre-registration — Korea (Upbit) test of the large-venue pattern

**Written 2026-07-28, after enumerating the sample and BEFORE computing a single return.**
Metadata only: market lists, anchors from candles, Gate perp launch times, overlap with every
run already published, and price-series availability. No P&L existed when this was written.

## What is being tested

Three replications have narrowed the claim to one thing: **the effect appears on
large-audience venues and not on small ones.**

| already published | venue tier | n | mean | t |
|---|---|---|---|---|
| Binance (in-sample, the rule was built here) | large | 115 | +2.71% | +1.99 |
| Coinbase, clean tokens | large | 48 | +2.76% | +1.64 |
| Bybit, fresh | small | 39 | −3.72% | −1.66 |
| four-venue pool, fresh | small | 92 | −2.65% | −1.80 |

Korea is the third large-audience venue available, and Upbit's domestic retail base is the
closest thing to Binance's in concentration. **This is the first sample large enough to move
the large-venue estimate**, at n=67 clean against Coinbase's 48.

## The design correction that makes this possible

The first version of this idea was going to be abandoned because Upbit quotes in KRW, and a KRW
path measures the token and the won together — the kimchi premium would have been inside every
number.

The operator corrected it: **we do not trade in Korea.** The Upbit listing is only the signal.
The trade is a USDT-margined perpetual elsewhere, so the price series should be a USDT series
too. The Korean venue supplies the timestamp and nothing else, and the FX problem disappears
rather than being adjusted for.

## Enumeration, before any outcome

| | count |
|---|---|
| Upbit KRW/USDT markets, one per token | 306 |
| first listed inside the 730-day window | 183 |
| a Gate perpetual exists by T+18h | **127** |
| **PRIMARY — token never in the Binance study** | **67** |
| shared with the study but ≥3 days apart | 33 |
| shared and within 3 days (not independent) | 27 |

Separation for the shared group is genuinely wide: median **79 days**, p25 45, p75 194, and only
3 of 33 fall inside 14 days. So `weak` is reportable, unlike the Bybit case where 48 of 70 shared
tokens listed within 24 hours of Binance. It is still not the primary.

**Bithumb is enumerated and deliberately not used as a signal source.** 471 KRW pairs are visible
from the VPS — Bithumb is unreachable from the research network — and 174 of its tokens are absent
from Upbit. But it publishes no per-pair listing time and its candlestick feed returns a fixed
window, so anchors cannot be derived the same way. Recording that rather than inventing anchors
from a proxy.

## Price series

A USDT series in a fixed priority order, recorded per event and reported split by source:
**Binance spot → Bybit → OKX → KuCoin → Gate spot.** Measured availability across the 67 clean
tokens: Binance 36, Bybit 22, KuCoin 6, Gate 2, OKX 1, **none 0**. Every event is priceable.

Pricing source has mattered before — the Binance study's Gate-perp subset ran +3.20% against
+1.99% for its Binance-spot subset — so the split is reported, not assumed away.

## Power, stated before the result

| n | if the true mean is +1.18% | +2.76% | +8.53% |
|---|---|---|---|
| 67 (primary) | 0.66 | **1.55** | 4.78 |
| 100 (primary + weak) | 0.81 | **1.89** | 5.84 |

`+1.18%` is the parameter-free band average measured on clean Coinbase and is the most defensible
current estimate; `+2.76%` is clean Coinbase at the frozen hour. **Neither reaches the bar at this
n.** This sample can move the pooled large-venue estimate and can refute; it cannot confirm alone.

## The bar

Fourth replication in this session — Bybit, the four-venue pool, Coinbase, Korea — two arms each.
Eight configurations:

`bar = 2.0 + 0.35 × ln(8) = 2.73`

Raised again, for the same reason as before: continuing to look for a venue where the answer comes
out favourable is itself a search.

## Method, frozen

Unchanged from `PREREG_ARMS.md`: short only, TP 15%, SL 15%, max hold 72h, 1×, entry T+12h and
T+18h after the anchor, a Gate perpetual required by that arm's entry hour, 0.30% assumed spread,
0.075% taker per side, liquidation guard at +95%, adverse before favourable, gap-through-stop at
the open, coverage judged from the entry hour onward.

**The anchor is the first traded hour on the USDT series at or after the Upbit listing day**, not
midnight. This is the third time this project has had to say that; on the Coinbase run the
midnight anchor cost 91 of 102 events before the loss counter caught it.

## Declared analyses

1. **Primary**: clean 67, both arms.
2. Primary + weak (100), reported separately.
3. **Pooled large-venue clean estimate**: Korea primary combined with clean Coinbase, versus the
   92-event small-venue pool. This is the number the whole exercise has been converging on.
4. A **placebo control** identical to the Coinbase one — same tokens, same rule, at +30/60/120/240
   days after their own listing — because that control is what ruled out market beta last time and
   a positive result without it means nothing.
5. Split by price-series source.

## What each outcome will be taken to mean

- **primary positive with t ≥ 2.73, placebo control passing** — the large-venue pattern holds on a
  third independent venue. Still not a licence for capital; it would mean the forward test is
  testing something real.
- **primary positive, t below 2.73** — pools with Coinbase and raises the large-venue estimate's
  precision. Reported as such, not as confirmation.
- **primary near zero** — the large-venue pattern was two samples agreeing by luck. The whole
  thesis is then finished.
- **primary negative** — same conclusion, more firmly.
- **primary positive but the placebo control also positive** — the result is market drift and is
  discarded, exactly as it would have been on Coinbase.

## Known ways this could still be fooling us

- **Survivorship, favouring the edge.** Only currently-listed Upbit markets are enumerated.
- **Announcement front-running.** Upbit listing notices move price before the listing hour, so the
  pump may be partly spent before the anchor. Same objection as Coinbase, unresolved.
- **The audience-size story is unfalsifiable if it keeps being adjusted.** Three large venues is
  the whole population; there is no fourth to appeal to if this one disagrees.
- **One market regime.** 730 days.
