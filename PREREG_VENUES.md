# Pre-registration — three-venue forward test

**Written 2026-07-28, before the two new arms have traded anything.** At the moment of writing
the production database holds 0 closed and 0 open positions on any arm.

This does **not** modify `PREREG_ARMS.md`. The Binance arms `t12` and `t18` continue exactly as
frozen, on their own books, untouched. What follows adds two new arms with their own books, so
nothing already committed is edited and each venue keeps a separate record.

## Why

Five out-of-sample replications, all pre-registered before running, put the evidence here:

| sample | venue tier | n | mean | win | t |
|---|---|---|---|---|---|
| Binance — in-sample, not evidence | large | 115 | +2.71% | 62.6% | +1.99 |
| Coinbase, clean tokens | large | 48 | +2.76% | 66.7% | +1.64 |
| Upbit, clean tokens | large | 63 | +3.99% | 65.1% | +2.55 |
| **pooled large-venue, clean** | large | **111** | **+3.46%** | 65.8% | **+3.03** |
| Bybit, fresh | small | 39 | −3.72% | 38.5% | −1.66 |
| four-venue pool, fresh | small | 92 | −2.65% | 43.5% | −1.80 |

The effect appears on large-audience venues and not on small ones, and on Upbit the listing hour
itself is worth **+4.94pp at t 2.93** against a placebo of the same tokens on arbitrary dates.
It sits **on** its significance bar rather than past it. The forward test currently listens to one
of the three large venues; adding the other two roughly doubles the signal rate, from 58 a year to
116, which is the difference between a 23-month test and an 11-month one.

## The two new arms

| | `cb12` | `up12` |
|---|---|---|
| signal | new USD/USDC pair on Coinbase | new KRW/USDT pair on Upbit |
| anchor | **that venue's own first traded hour** | same |
| entry | T+12h | T+12h |
| execution | Gate USDT perpetual | Gate USDT perpetual |
| take profit / stop / hold / leverage | 15% / 15% / 72h / 1× | same |
| size | 20% of that arm's own book | same |
| starting book | 1,000 USDT | 1,000 USDT |
| out-of-sample backtest | +2.76%, t 1.64, n 48 | +3.99%, t 2.55, n 63 |

**Why T+12h only, and no T+18h arm for the new venues.** T+12h was the operator's original
hypothesis, stated before any data was pulled and never swept. T+18h was added because of a
plateau in the Binance surface, and that plateau has now failed to replicate anywhere: T+18h is
+2.25% on Coinbase and +0.72% on Upbit against +2.76% and +3.99% for T+12h, and the two large-venue
hour surfaces anti-correlate at r = −0.685. Declining to carry a swept parameter into a new arm is
not the same as choosing a hour because it worked — the alternative would be to import a parameter
that has already failed out-of-sample twice.

**The existing `t18` arm is not dropped.** It is now clearly the weaker arm and `PREREG_ARMS.md`
forbids dropping one, precisely to stop that decision being made in reaction to a result.

## The anchor, which is where this project keeps failing

Each venue's anchor is **its own first traded hour**, never midnight:

| venue | how it is derived | first traded hour, measured |
|---|---|---|
| Binance | first 1h kline of the new symbol | varies |
| Coinbase | earliest hourly candle on the listing day | median **17:00 UTC** |
| Upbit | earliest 60-minute candle on the listing day | median **7h past midnight** |

**Three separate midnight-anchor bugs have been found in this project**, the most recent inside
the Upbit run itself, where it manufactured a +5.91% result at t 5.76 that had to be withdrawn.
Per-venue anchors are therefore not an implementation detail; they are the single most
error-prone part of this design, and the monitor will publish the measured offset per arm so a
recurrence is visible rather than silent.

## The concurrency cap belongs to reporting, not to collection

The operator asked for a cap of one concurrent position, and the measured case for it is strong:
on the two clean large-venue samples a cap of 1 gives **+64.4% CAGR at an 11.2% drawdown and 30%
peak exposure**, against +59.9% at 19.0% and 60% for a cap of 2 — better return, half the
drawdown, half the exposure. Simultaneous shorts on new listings in one market are correlated, so
a second open position is leverage rather than diversification. If more risk is wanted, the
efficient purchase is a larger single position: cap 1 at 50% gives +121% CAGR at the same 18%
drawdown that cap 2 at 30% produces for +60%.

**But a cap discards events, and Amendment 1 of `PREREG_ARMS.md` established that the gate may
size down and must never skip** — skipping removes sample points and biases the test. So:

- **collection takes every eligible event**, uncapped, on every arm
- **the cap is applied afterwards, in the report**, as a deployment overlay computed from the
  recorded trades

That way the measurement keeps its full sample and the deployment figure is still available. The
monitor will publish both: per-arm results from every trade, and a synthetic cap-1 portfolio
across all arms as the number an actual account would have earned.

No cooldown is applied in collection either, for the same reason. Across arms the same token can
be signalled by two venues — measured on history, 28 tokens were, at a median 153 days apart and
only 4 within a week — and those are separate events on separate books.

## The bar

The forward test now carries four pre-declared arms rather than two:

`bar = 2.0 + 0.35 × ln(4) = 2.49`

This is the forward test's own bar and is independent of the historical replications' bar, because
forward data cannot be overfitted by a rule frozen before it existed.

**Trade counts needed**, from the measured dispersion of 14.6pp:

| if the true mean is | events for t = 2.49 | at 116 signals/year |
|---|---|---|
| +1.18%, the parameter-free band average | 950 | 8.2 years |
| +2.71%, the Binance headline | 180 | 19 months |
| +3.46%, the pooled large-venue estimate | 110 | **11 months** |

## Stop rule, per arm, unchanged

**A win rate at or below 40% after 15 closed trades stops that arm.** Evaluated on the monitor
rather than by judgement.

## What would invalidate this

- editing any number in the arm table once that arm has traded
- dropping, pausing or ignoring an arm because its numbers look bad
- adding a fifth arm and reporting the best of five under this bar
- applying the concurrency cap to collection instead of to reporting, which would silently
  change the sample
- reporting the cap-1 portfolio figure without also reporting the uncapped per-arm results

## Known ways this could still be fooling us

- **The large-venue estimate sits on its bar.** t 3.03 clears 2.73 if eight configurations are
  charged for and fails 3.05 if twenty are. Everything downstream inherits that.
- **The entry hour is not identifiable.** The two large-venue surfaces anti-correlate. T+12h is
  2 for 2 on clean data, which is not the same as being right; the parameter-free estimate is
  +1.18% per trade, and at that level the pooled cap-1 CAGR is +31.6%, not +114%.
- **"Large venue" may be a proxy for token quality.** Median adverse excursion runs 22.1% on
  small venues, 8.8% on Coinbase, 5.3% on Upbit. That fits the audience story and equally fits
  large venues simply listing better-behaved tokens. Unresolved, and it does not change what to
  trade — only why it works.
- **Upbit's early listings are unmeasurable.** 24 events were dropped because no USDT market
  existed within 2h, which means Upbit led the market — the purest form of the hypothesis, and
  invisible for exactly that reason.
- **Announcement front-running.** Both Coinbase and Upbit publish listing notices in advance, so
  part of the pump may precede the anchor.
- **Six apparent discoveries in this project have been artefacts**, three of them midnight
  anchors, one found in the run that produced the evidence above. This is a forward test because
  history cannot settle it.
