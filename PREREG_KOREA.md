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

---

# RESULT — run 2026-07-28, after the above was committed

## The first run was wrong, and its numbers are withdrawn

The first pass anchored on the daily candle's midnight UTC. Because these tokens already trade
on other venues, the USDT series HAS a candle at midnight, so nothing was lost and nothing
looked wrong. It produced **+5.91% at t 5.76 on the t18 arm** — which would have been the
strongest number this project ever produced, and was an artefact.

Verified against Upbit directly: its real first traded hour is **6–10 hours past midnight UTC,
median 7h**. So "midnight + 12h" was really T+2h..T+6h from the listing, still inside the pump,
and "midnight + 18h" was T+8h..T+12h, past its peak. The two arms measured two different events
and neither was the one under test. **Third time this project has had to fix a midnight anchor.**

Two other repairs made at the same time: the placebo control covered only t12 while the positive
result sat on t18, leaving the headline untested; and 7 events had a USDT series starting up to
330 days after the listing (AERO, 7,919h) which is not a measurement of the Upbit listing at all.
Events whose series drifts more than 2h from the anchor are now dropped.

Everything below uses Upbit's own first traded hour. Diagnostic: median anchor offset **7.0h**
(p25 6, p75 9), and series drift median 0.00h, max 0.00h.

## Primary

| arm | n | mean | median | win | t | 95% CI |
|---|---|---|---|---|---|---|
| **t12** | **63** | **+3.99%** | **+11.25%** | **65.1%** | **+2.55** | +0.93 … +7.05 |
| t18 | 65 | +0.72% | +2.73% | 56.9% | +0.48 | −2.24 … +3.68 |

Against a bar of 2.73, t12 is **positive and just below it**. Clean+weak (n=90) reaches +3.81%
at **t 2.93**, which clears.

## The placebo control passes on the arm that matters

| | n | mean | win | t |
|---|---|---|---|---|
| REAL t12, entered at the Upbit listing | 63 | **+3.99%** | 65.1% | +2.55 |
| PLACEBO t12, arbitrary later dates | 209 | **−0.95%** | 49.8% | −1.50 |
| **listing minus placebo** | | **+4.94pp** | | **+2.93 — beyond drift** |
| REAL t18 | 65 | +0.72% | 56.9% | +0.48 |
| PLACEBO t18 | 209 | −0.73% | 50.2% | −1.12 |
| listing minus placebo | | +1.44pp | | +0.88 — not separable |

The listing hour carries the effect on t12 and does not on t18.

## Robustness

| check | result |
|---|---|
| trim the 1/2/3 best and worst | t **2.63 / 2.71 / 2.80** — it strengthens, so not outliers |
| first half of the window | +1.99%, t 0.91 |
| second half | +5.92%, t 2.69 — no decay, if anything the reverse |
| priced on Binance / Bybit / Gate | +2.52% / +4.88% / +9.71% — all positive |
| exit mix | 31 target, 14 stop, 18 time; median MAE **5.3%**; 2 of 63 would liquidate |
| contaminated subset (11 events) | +11.99% — inflated exactly as on Coinbase, and excluded |

## The pooled large-venue estimate

| sample | tier | n | mean | win | t |
|---|---|---|---|---|---|
| Coinbase clean | large | 48 | +2.76% | 66.7% | +1.64 |
| Upbit clean | large | 63 | +3.99% | 65.1% | +2.55 |
| **LARGE-VENUE CLEAN POOLED** | **large** | **111** | **+3.46%** | **65.8%** | **+3.03** |
| four-venue pool | small | 92 | −2.65% | 43.5% | −1.80 |

Large minus small: **+6.11pp at t 3.27.**

Neither large venue clears its bar alone. Pooled, they do — and whether that survives depends
entirely on how much searching is charged for:

| configurations counted | bar | verdict at t 3.03 |
|---|---|---|
| 8 — four replications × 2 arms | 2.73 | clears |
| 12 — plus venue-tier and clean/weak partitions | 2.87 | clears |
| 20 — plus cohort, price-source and hour splits | 3.05 | **fails** |
| 32 — every split reported this session | 3.21 | **fails** |

**It sits on its bar, not past it.** That is the honest statement.

## What cannot be resolved here

**The 24 dropped events are the purest form of the hypothesis.** They were dropped because no
USDT market existed within 2h of the Upbit listing — meaning **Upbit was early and Korea led the
rest of the market**. Those are precisely the cases where the audience-arrival story should be
strongest, and they are unmeasurable because there is no USDT series to price them on. The
surviving sample is restricted to tokens already tradeable in USDT when Upbit listed them.

**"Large venue" may be a proxy for token quality.** Median adverse excursion is 22.1% on the
small-venue pool, 8.8% on Coinbase, 5.3% on Upbit. Large-venue tokens simply run up far less
after the entry. That fits "big audience, pump exhausts" and it equally fits "big venues list
better-behaved tokens". The two cannot be separated with this data. For trading it does not
matter — you would only ever trade large-venue listings. For the mechanism it matters, and it
is unresolved.

## Verdict

The general thesis stays refuted: on 92 fresh tokens across four small venues the rule loses.

The narrow claim now has what it did not have this morning: **clean out-of-sample support that
survives a placebo control.** 111 events across two independent large-audience venues,
**+3.46% per trade at t 3.03**, against −2.65% on small venues.

Three further things are worth recording because they cut against earlier conclusions of mine:

1. **The frozen hour is now 2 for 2.** T+12h works on Coinbase (+2.76%) and Upbit (+3.99%);
   T+18h is flat on both (+2.25%, +0.72%). T+18h and T+22h were the swept winners on Binance and
   have failed to replicate anywhere. The frozen hour was never chosen by looking, and it is the
   one that holds.
2. **Do not drop the t18 arm.** It is now the weaker arm on the evidence, and `PREREG_ARMS.md`
   forbids dropping an arm — which exists precisely to stop a decision like this being made in
   reaction to a result.
3. **This is still historical data.** Six apparent discoveries in this project were artefacts of
   unexamined assumptions, three midnight anchors among them, and one was found in this very run.
   The forward test on Binance listings is now testing something with real support behind it, and
   it remains the only evidence that cannot be contaminated. **No real capital until it has
   produced its own.**
