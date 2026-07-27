"""Frozen configuration for the listing-short paper trader.

THE RULE IS FROZEN AND MUST NOT BE TUNED. Its whole value is that these numbers were
not chosen by looking at outcomes:

  entry T+12h   the operator's original observation, stated before any data was pulled
  TP 15%        inside the operator's original "15-20%" framing
  SL 15%        the one contaminated parameter — picked from a grid, and flagged as such
  hold 72h      unchanged throughout the research

T+18h and T+21h measured better in backtest. They are deliberately NOT used, because
they were the peak of a ten-hour sweep. Changing any value here voids the forward test,
because the point of the exercise is to see whether the untuned rule survives contact
with data nobody has looked at.

Backtest expectation to judge the live results against:
  n 115 over 1.89 years, mean +2.71%, median +14.77%, win 62.6%, t 1.99, sd 14.6%
  Bar was 3.55, so the rule did NOT clear it. This forward test is the missing evidence.
  At ~5 events/month, 15 events cannot confirm an edge — but if the win rate comes in
  at 40% or below, the strategy is broken and should be stopped.
"""

# ---- the frozen rule -------------------------------------------------------
ENTRY_HOURS = 12          # hours after the first traded hour on Binance spot
TAKE_PROFIT = 0.15        # fraction, favourable
STOP_LOSS = 0.15          # fraction, adverse
MAX_HOLD_HOURS = 72
LEVERAGE = 1.0
POSITION_PCT = 0.10       # of notional equity, per position. 10% not 30%: the
                          # backtest's p90 drawdown was 35.8% at 30%, and n=115 is
                          # not enough confidence for that.

# ---- paper account ---------------------------------------------------------
PAPER_START_EQUITY = 1000.0
CURRENCY = "USDT"

# ---- venue costs, real ------------------------------------------------------
GATE_TAKER_FEE = 0.0005   # 0.05% per side
# Funding is fetched live per contract, never assumed. A short RECEIVES funding when
# the rate is positive, which on a hyped new listing it usually is.

# ---- eligibility -----------------------------------------------------------
QUOTE_ASSET = "USDT"
# A perpetual must exist by the entry hour. This is not a tunable filter: you cannot
# short what has no perp, and requiring it also excludes stablecoins, liquid-staking
# tokens and tokenised equities, none of which the thesis is about.
PERP_MUST_EXIST_BY_HOURS = ENTRY_HOURS
MIN_BOOK_NOTIONAL_USDT = 200.0   # refuse to paper-fill into a book too thin to be real

# ---- operational -----------------------------------------------------------
SCAN_INTERVAL_MINUTES = 5
EVENT_TRACK_DAYS = 10     # stop tracking an event after this
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ---- endpoints -------------------------------------------------------------
BINANCE_SPOT = "https://data-api.binance.vision/api/v3"
GATE_FUTURES = "https://api.gateio.ws/api/v4/futures/usdt"
OKX_PUBLIC = "https://www.okx.com/api/v5/public"
KUCOIN_FUTURES = "https://api-futures.kucoin.com/api/v1"

# ---- paths -----------------------------------------------------------------
import os

BASE_DIR = os.environ.get("LISTINGBOT_HOME",
                          os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "listingbot.sqlite")
LOG_PATH = os.path.join(DATA_DIR, "listingbot.log")
