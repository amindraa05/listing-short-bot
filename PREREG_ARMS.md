# Pre-registration — two-arm forward test

**Written 2026-07-28, before the first paper trade of either arm exists.** At the moment of
writing the production database holds 0 events and 0 positions, so nothing in this document
was chosen with knowledge of a forward outcome. That is the only property that makes the
test worth running.

## Why two arms instead of one

The backtest swept ten entry hours and T+18h won. The first version of the research page
reported that winner, and the honest rebuild dropped to T+12h — the operator's own
hypothesis, stated before any data was pulled.

The operator then made an argument that is correct and that this document acts on:

> forward data cannot be overfitted, so "T+18h was chosen by looking" is not a reason to
> refuse it going forward

Refusing a parameter because it came from a sweep is a rule about **reporting a backtest**.
Deciding what to run **forward** is a forecast — which configuration has the higher expected
future return — and a forecast has to be argued from evidence. The evidence on that question
is genuinely mixed:

**For the later entry.** The elevated region is broad, not a spike: on one fixed 115-event
sample, mean per trade runs +3.23% / +3.00% / +4.52% / +3.72% / +4.81% / +4.07% at
T+14/16/18/20/22/24h, against +2.71% at T+12h. And it has a **mechanism** — adverse
excursion is front-loaded, so a later entry has less of the violent window left to survive:

| entry | mean | win | stop hits | median MAE | excursions past +95% |
|---|---|---|---|---|---|
| T+12h | +2.71% | 62.6% | 39 | 10.2% | 7 |
| T+18h | +4.52% | 67.8% | 31 | 9.6% | 5 |
| T+22h | +4.81% | 71.3% | 30 | 6.9% | 4 |
| T+26h | +2.42% | 60.9% | 37 | 8.7% | 2 |

Both edges of that shape are explainable: too early and the pump is still running; past
~24h the fall has already happened, so target hits drop from 61 to 50 and time exits climb
from 15 to 28. A plateau with a named mechanism at both edges is structure. An isolated
spike would be noise.

Separately and with no statistics involved: at T+16h and later the tradeable universe grows
from **115 to 134 events (+17%)**, because perps that did not exist at T+12h do exist by
then. More events is a shorter forward test.

**Against the later entry.** Paired on the same 115 listings, T+18h minus T+12h is
**+1.82pp at t 1.50**, 95% CI **−0.56pp to +4.20pp** — not distinguishable from noise. It
won 57 listings and lost 49. And the mechanism first guessed at is absent: the price at
T+18h is *lower* than at T+12h in 63% of listings (median −2.51%), so a later entry is not
a higher short.

The evidence does not settle it. Two arms settle it, on clean data, at zero cost — this is
paper money and recording a second entry per listing consumes nothing but disk.

## The two arms, frozen

Both arms are declared here **before either has traded**. Neither may be modified, and
**neither may be dropped** once results exist.

| | arm `t12` | arm `t18` |
|---|---|---|
| entry | T+12h after the first traded hour | T+18h after the first traded hour |
| perp must exist by | T+12h | T+18h |
| take profit | 15% | 15% |
| stop loss | 15% | 15% |
| max hold | 72h | 72h |
| leverage | 1× | 1× |
| size | 20% of that arm's own equity | 20% of that arm's own equity |
| starting equity | 1,000 USDT, its own book | 1,000 USDT, its own book |
| backtest mean | +2.71% (n 115, t 1.99) | +4.86% (n 134, t 4.03) |

**Separate books.** Each arm carries its own equity so one arm's drawdown cannot distort
the other's position sizing, and the two return series stay independently comparable. The
same listing will usually be traded by both arms; that is the point.

**The perp filter tracks the entry hour and is not a tunable.** At a T+18h entry a perp that
exists by T+18h is genuinely shortable. The two must move together — pairing a T+12h claim
with a T+18h event set is the error the research page's decomposition section documents,
and it accounted for half of the fall from $6,180 to $2,269.

## What each arm is allowed to conclude

Two pre-declared configurations carry a multiple-testing bar of
`2.0 + 0.35 × ln(2) = 2.24`, which is close enough to the single-test 2.0 that it changes
nothing material. This is the whole reason to declare both now rather than pick later: had
one been chosen after seeing forward results, the sweep would simply have moved to fresh
data and the bar would rise with the number of hours effectively searched.

**Primary question:** does either arm show a positive mean per trade that clears t 2.24?

**Secondary question, and the one this design exists for:** is the paired difference
`t18 − t12` on listings both arms traded positive, and does it clear t 2.24? That test is
paired, so it removes the between-listing variance that made the backtest comparison
inconclusive at t 1.50.

**Trade counts needed**, from the measured dispersion of 14.6pp:

| if the true mean is | events for t = 2.24 | months at ~5/month |
|---|---|---|
| +2.71% (the t12 backtest) | 146 | 29 |
| +4.86% (the t18 backtest) | 45 | 9 |

## Stop rule, unchanged

**A win rate at or below 40% after 15 closed trades stops that arm.** If the true win rate
is 63%, the chance of observing 40% or worse across 15 trades is 3.5%, so this detects a
broken strategy long before it can confirm a working one. The rule applies per arm and is
evaluated on the monitor page rather than by judgement.

## What would invalidate this test

- editing any number in the table above once trades exist
- dropping, pausing or ignoring an arm because its numbers look bad
- adding a third arm and reporting the best of three under this bar
- reading a result before either arm reaches 15 closed trades and acting on it

Recorded so that the failure mode is nameable rather than deniable: **six apparent
discoveries in this project turned out to be artefacts of unexamined assumptions, and all
four measurement bugs found during the research happened to flatter the result.** A run of
favourable errors is itself evidence that the undiscovered ones are probably favourable too.

---

## Amendment 1 — liquidity discipline, 2026-07-28

Made while the database still held **0 closed positions and 0 open positions**, so nothing
below was chosen with knowledge of a forward outcome.

**What changed.** Two execution mechanics, neither of them a rule parameter:

1. **A participation gate.** Before an entry, the intended notional is compared against
   what the contract actually traded in the previous hour. Above **3%** of it the notional
   is cut to exactly 3%.
2. **Order slicing.** An order larger than **25% of the visible bid depth** is split across
   ticks, up to 6 slices over 30 minutes, and the position's VWAP, take profit and stop
   move onto the running average as each slice lands.

**Why this does not compromise the test.** The statistical test is on **percentage** returns
per trade — mean, win rate, t. Cutting the notional changes the dollar P&L and leaves the
percentage untouched. Skipping an event would be a different matter, because it removes a
sample point, so **the gate never skips**: it only sizes down. The single existing refusal,
a book too thin to fill the order at all, is unchanged and predates this amendment.

**Why it was needed.** Measured on the 135 events of the research sample: the median entry
hour trades $2.9M on Binance spot and the Gate perp runs a median 2.07× that. Against that
median, size is a non-issue at any capital this account will hold. The tail is not:
**RED traded $203k in its first hour and $1,072 in hour twelve.** A fixed-percentage order
into that hour is the whole hour. The gate exists for the RED case, not the median case.

The 3% number comes from what execution cost does to the edge, not from taste. Against a
2.71% mean, extra slippage of 0.25% eats 9% of it and takes t from 1.99 to 1.80; 1.00% eats
37% and takes t to 1.25. A 1% tolerance is not a safety margin — it is a third of the thesis.

**Also corrected the same day:** the Gate taker fee, from an assumed 0.05% to the 0.075%
that Gate's own contract spec reports on all 850 USDT perps. Round trip 15bps, not 10.
A measurement input, not a rule parameter, and again corrected before any position closed.

**Still frozen and untouched:** entry hours, take profit, stop loss, max hold, leverage,
the 20% sizing rule, the arms themselves, and the stop signal.

---

## Amendment 2 — position size solved from a drawdown target, 2026-07-28

Made while the database held **0 closed and 0 open positions on every arm**.

**What changed.** `POSITION_PCT` from 20% to **17%**.

**Why it is not a free choice.** 20% was picked by hand, before there was any way to target a
drawdown. There is now: size and drawdown are near-proportional in this strategy, so a drawdown
target has exactly one size that meets it. Bisecting against a bootstrapped p90 drawdown on the
clean out-of-sample sample gives:

| p90 drawdown target | size | CAGR at +3.46%/trade | at +1.18%/trade |
|---|---|---|---|
| 10% | 9% | +26.9% | +6.7% |
| 15% | 14% | +45.5% | — |
| **20%** | **17%** | **+58.9%** | **+12.8%** |
| 25% | 23% | +85.3% | — |
| 30% | 28% | +111.2% | +19.3% |

The 20% target is what ships. Changing the target changes one number and its consequence is
published in the same table, which is the point of solving it rather than choosing it.

**Why this cannot bias the test.** The statistic is the **percentage** return per trade — mean,
win rate, t. Size changes the dollar P&L and leaves the percentage untouched. This is the same
argument Amendment 1 used to justify sizing down at the liquidity gate, and the same reason a
concurrency cap is forbidden in collection: a cap would remove events, and size does not.

**Still frozen and untouched:** entry hours, take profit, stop loss, max hold, leverage, the
arms themselves, the stop signal, and the rule that no arm may be dropped.
