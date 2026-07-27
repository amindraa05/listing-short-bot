# listing-short-bot

Paper-trades one hypothesis: **a new Binance spot listing pumps, then falls, and the fall
can be shorted on a perpetual.** It records; it cannot place a real order. There is no
signing code and no API key anywhere in this repository.

## Why it exists

The backtest behind this rule **did not clear its own significance bar**, and the reason
that matters is worth stating precisely rather than burying:

| | value |
|---|---|
| events | 115 over 1.89 years |
| mean per trade | +2.71% |
| median | +14.77% |
| win rate | 62.6% |
| t | **1.99** against a bar of **3.55** |
| DEV subset that chose no parameter | t **1.14** |

A tuned version reached t 4.03 by entering at T+18h — the peak of a ten-hour sweep. That
number is not used here. The rule below uses T+12h, which came from the operator's own
observation before any data was pulled.

**Live results:** <https://amindraa05.github.io/listing-short-bot/monitor.html> ·
**research findings:** <https://amindraa05.github.io/listing-short-bot/>

There is also **no clean holdout left**: all 115 events were used to sweep the entry hour,
pick the exits and repair filters. Forward data is the only uncontaminated evidence that
remains, and collecting it is the entire purpose of this bot.

## The frozen rule

```
signal      a new USDT pair starts trading on Binance spot
filter      a perpetual must already exist by the entry hour (Gate / OKX / KuCoin)
direction   short, never long
entry       T+12h after the first traded HOUR — not midnight of the listing day
take profit 15%
stop loss   15%   (not optional: 5 of 115 events would have liquidated a 1x short)
max hold    72h
leverage    1x
size        20% of paper equity
```

Sizing is the one number the operator set deliberately rather than inheriting from the
research: 20% of equity per position. The bootstrapped p90 drawdown was 35.8% at 30% and
scales roughly linearly, so expect about **24%** at 20% — size against that figure, not
against the kinder 16.7% the historical trade ordering happened to produce.

**Do not tune the rest.** Their only value is that they were not chosen by looking at
outcomes. Changing one voids the forward test. A trailing take-profit was tested against
a properly sealed holdout and refuted on DEV, so the holdout was never spent.

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
python -m listingbot.cli status    # live results against the backtest expectation
python -m listingbot.cli ledger    # every closed position with measured slippage
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

| if the true edge is | events for t = 2.0 | months |
|---|---|---|
| the honest +2.71% | 117 | 23 |
| the tuned +4.86% | 36 | 7 |
| the best cohort +8.68% | 11 | 2 |

**Three months is about 15 events and cannot confirm anything** — the mean would carry a
±3.8pp error bar. What it can do is detect a broken strategy: if the true win rate is 63%,
there is only a 3.5% chance of observing 40% or worse across 15 trades.

**Pre-agreed stop signal: a win rate at or below 40% after 15 closed trades.**

## What is still wrong with the underlying research

- no clean holdout exists for the fixed-target rule
- four measurement bugs were found during the work and **every fix helped the result** —
  each was independently demonstrable, but a run of favourable errors suggests the
  undiscovered ones are probably favourable too
- funding was not charged in the backtest at all; this bot measures it
- the sample spans 1.9 years and one market regime
- Binance-futures, Bybit, MEXC and Bitget were unreachable from the research network, so
  shortability was undercounted
