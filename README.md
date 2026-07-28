# listing-short-bot

Paper-trades one hypothesis: **a new Binance spot listing pumps, then falls, and the fall
can be shorted on a perpetual.** It records; it cannot place a real order. There is no
signing code and no API key anywhere in this repository.

## Why it exists

The backtest behind this rule **did not clear its own significance bar**, and the reason
that matters is worth stating precisely rather than burying:

| | arm t12 | arm t18 |
|---|---|---|
| events | 115 over 1.89 years | 134 |
| mean per trade | +2.71% | +4.86% |
| median | +14.77% | +14.77% |
| win rate | 62.6% | 68.7% |
| t | **1.99** against a bar of **3.55** | **4.03** — clears it |
| DEV subset that chose no parameter | t **1.14** | — |

Both figures come with a caveat that matters more than either number. t12 fails the bar.
t18 clears it, but 84 is *this project's count* of the configurations searched; the count
is not knowable exactly, and at 500 the bar would be 4.17 and t18 would fail too. The
difference between the two arms is also not itself significant (+1.82pp at t 1.50), which
is exactly why both are being run forward rather than argued about.

**Live results:** <https://amindraa05.github.io/listing-short-bot/monitor.html> ·
**research findings:** <https://amindraa05.github.io/listing-short-bot/>

There is also **no clean holdout left**: all 115 events were used to sweep the entry hour,
pick the exits and repair filters. Forward data is the only uncontaminated evidence that
remains, and collecting it is the entire purpose of this bot.

## Two arms

The backtest could not settle its own central question — whether the entry belongs at
T+12h or T+18h — so both run forward, side by side, each on its own book. Full reasoning
and the frozen numbers are in **[PREREG_ARMS.md](PREREG_ARMS.md)**, written before either
arm had traded.

```
signal      a new USDT pair starts trading on Binance spot
filter      a Gate perpetual must exist by THAT ARM's entry hour
direction   short, never long
take profit 15%          shared
stop loss   15%          shared (not optional: 5 of 115 events would have liquidated a 1x short)
max hold    72h          shared
leverage    1x           shared
size        20% of that arm's own equity

  arm t12   entry T+12h   the operator's hypothesis, stated before any data was pulled
  arm t18   entry T+18h   the middle of a broad elevated plateau, T+14h..T+24h
```

**Why run the tuned hour at all?** Because refusing a parameter for having come from a
sweep is a rule about *reporting a backtest*, not about choosing what to run forward —
forward data cannot be overfitted. Choosing is a forecast, and the backtest cannot make
it: paired on the same 115 listings, T+18h minus T+12h is **+1.82pp at t 1.50**, CI
−0.56pp to +4.20pp. So both run, both were declared in advance, and the bar for two
pre-declared configurations is `2.0 + 0.35 × ln(2) = 2.24` — essentially free.

**Why T+18h and not T+22h, which measured best?** Because 22h *is* the sweep peak. The
whole T+14h–T+24h band is elevated and the risk mechanism behind it is monotone — stop
hits fall 39 → 31 → 30 and median adverse excursion falls 10.2% → 9.6% → 6.9% as the
entry moves later, because the violent part of the pump is front-loaded. Past ~24h the
fall has already happened and the edge decays. T+18h is chosen as the middle of that
shape, not the top of the search.

Sizing is the one number the operator set deliberately: 20% of that arm's equity. The
bootstrapped p90 drawdown was 35.8% at 30% and scales roughly linearly, so expect about
**24%** at 20% — size against that, not against the kinder 16.7% the historical trade
ordering happened to produce.

**Do not tune any of it, and do not drop an arm.** Either action turns this back into a
sweep, just on newer data. A trailing take-profit was tested against a properly sealed
holdout and refuted on DEV, so the holdout was never spent.

## Honest fills

The backtest assumed a flat 0.3% spread because historical new-listing spreads are
published nowhere — it was named as the most fragile input, and at 1% the edge lost its
bar. A testnet would not fix that, because testnet books are synthetic.

So every paper fill here **walks the live Gate order book**, consuming levels until the
intended notional is filled, and records the VWAP actually achieved. Measured on real
books:

```
BTC_USDT    $1000   slip  0.01 bps    1 level
AERO_USDT   $1000   slip 11.6  bps    6 levels
PENGU_USDT  $1000   slip 34.5  bps   37 levels   total book depth $1,138
```

That last row is the finding the backtest could not have produced: on the thin, hyped
tokens this strategy targets, a $1,000 order consumes most of the visible book. **The
strategy has a capacity ceiling.** A book too thin to fill the size is refused, not
filled at a fiction.

Fees are Gate's real 0.05% taker per side. Funding is fetched per contract and signed so
that a positive rate is a **credit** to the short, which on a hyped listing it usually is.

## Running it

```bash
python -m listingbot.cli tick      # one cycle — what the timer calls
python -m listingbot.cli status    # per-arm results, plus the paired t18-minus-t12 test
python -m listingbot.cli ledger    # every closed position, by arm, with measured slippage
python -m listingbot.cli export    # CSV dump of every table
python -m listingbot.cli publish   # regenerate docs/monitor.html and git push it
```

Stdlib only. No pip, no venv, no dependencies.

## Deployment

```bash
sudo bash deploy/install.sh
sudo bash deploy/uninstall.sh      # data preserved unless --purge-data
```

The target host also runs live trading, so the install is built to make collision
impossible rather than unlikely:

- **binds no port** — outbound HTTPS only, so nothing contends with nginx, IB Gateway
  or any other listener
- touches no nginx config, certificate, domain or shared file
- installs no packages
- runs as its own unprivileged system user with no login shell
- every unit is prefixed `listingbot-`, so it cannot clash with existing units
- capped at `MemoryMax=256M`, `CPUQuota=15%`, `Nice=10`, `IOSchedulingClass=idle` —
  live trading always wins
- `ProtectSystem=strict` with a single writable path, its own data directory
- `uninstall.sh` refuses to delete a directory lacking the installer's marker file

## The monitor page

`tick` rewrites `data/monitor.html` every cycle, and `publish` commits it to `docs/` so
GitHub Pages serves it. **This is a file, not a service** — nothing listens on a port,
which is the same reason the install cannot collide with anything else on the host.

It is public, and it has no login. A password on a static page is theatre: the page is
already served to anyone who asks, and any check written into it is visible in the source.
The three real options are a private repo, an SSH tunnel to the host, or accepting that
$1,000 of paper money running a rule whose code is public is not a secret. This runs on
the third; the page carries `noindex` so it will not turn up in search results.

## Reading the results

At roughly 5 listings a month:

| if the true mean is | events for t = 2.24 | months |
|---|---|---|
| +2.71%, the t12 backtest | 146 | 29 |
| +4.86%, the t18 backtest | 45 | 9 |

**Three months is about 15 events per arm and cannot confirm anything** — the mean would
carry a ±3.8pp error bar. What it can do is detect a broken strategy: if the true win rate
is 63%, there is only a 3.5% chance of observing 40% or worse across 15 trades.

**Pre-agreed stop signal, per arm: a win rate at or below 40% after 15 closed trades.**

The paired comparison converges faster than either arm alone, because pairing removes the
between-listing variance — the same reason the backtest's own 115-listing comparison
stalled at t 1.50 while the unpaired means looked far apart.

## What is still wrong with the underlying research

- no clean holdout exists for either arm's backtest; forward data is the only clean test
- the entry hour is the open question, not a settled parameter
- four measurement bugs were found during the work and **every fix helped the result** —
  each was independently demonstrable, but a run of favourable errors suggests the
  undiscovered ones are probably favourable too
- funding was not charged in the backtest at all; this bot measures it
- the sample spans 1.9 years and one market regime
- Binance-futures, Bybit, MEXC and Bitget were unreachable from the research network, so
  shortability was undercounted
