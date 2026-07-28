"""Frozen configuration for the listing-short paper trader.

THE RULE IS FROZEN AND MUST NOT BE TUNED. Its whole value is that these numbers were not
chosen by looking at outcomes.

TWO ARMS run side by side, both declared in PREREG_ARMS.md before either had traded:

  t12   entry T+12h, perp required by T+12h   the operator's original hypothesis,
                                              stated before any data was pulled
  t18   entry T+18h, perp required by T+18h   the middle of a broad elevated plateau
                                              (T+14h..T+24h), NOT the sweep peak, which
                                              was T+22h

Running both is a deliberate answer to a correct argument: forward data cannot be
overfitted, so a parameter's history is not a reason to refuse it going forward. What it
IS a reason for is refusing to report its backtest as independent evidence. The backtest
cannot separate the two hours — paired on the same 115 listings the difference is +1.82pp
at t 1.50 — so the arms settle it on clean data instead. Two pre-declared configurations
carry a bar of 2.0 + 0.35*ln(2) = 2.24, which costs essentially nothing.

Shared and frozen across both arms: TP 15%, SL 15%, hold 72h, 1x, 20% of that arm's own
equity. Each arm keeps a SEPARATE 1,000 USDT book so one arm's drawdown cannot distort the
other's sizing.

Backtest expectation to judge each arm against:
  t12   n 115 over 1.89 years, mean +2.71%, median +14.77%, win 62.6%, t 1.99, sd 14.6%
  t18   n 134,                 mean +4.86%, median +14.77%, win 68.7%, t 4.03
Neither is a confirmed edge; t12 failed the backtest's own bar of 3.55. At ~5 events a
month, 15 events cannot confirm anything — but a win rate at or below 40% after 15 closed
trades means that arm is broken and stops.

DO NOT edit the arm table below, and DO NOT drop an arm once trades exist. Either action
turns this back into a sweep, just on newer data.
"""

# ---- the two frozen arms ---------------------------------------------------
# Each arm's perp requirement equals its entry hour, and that is not a tunable: at a
# T+18h entry a perp existing by T+18h is genuinely shortable, and pairing a T+12h claim
# with a T+18h event set is precisely the error that accounted for half the fall from
# $6,180 to $2,269 in the research.
# Each arm names its SIGNAL venue. Execution is always the Gate USDT perpetual — the venue
# supplies the listing timestamp and nothing else, which is what removed the FX objection
# from the Korean data. See PREREG_VENUES.md.
ARMS = {
    "t12": {"signal_venue": "binance", "entry_hours": 12, "label": "Binance T+12h",
            "note": "the operator's hypothesis, never swept",
            "backtest": {"n": 115, "mean": 2.71, "median": 14.77, "win": 62.6,
                         "t": 1.99, "sd": 14.6}},
    "t18": {"signal_venue": "binance", "entry_hours": 18, "label": "Binance T+18h",
            "note": "a swept plateau that failed to replicate; kept because the freeze "
                    "forbids dropping an arm",
            "backtest": {"n": 134, "mean": 4.86, "median": 14.77, "win": 68.7,
                         "t": 4.03, "sd": 14.6}},
    "cb12": {"signal_venue": "coinbase", "entry_hours": 12, "label": "Coinbase T+12h",
             "note": "clean out-of-sample: +2.76% on 48 tokens",
             "backtest": {"n": 48, "mean": 2.76, "median": 4.38, "win": 66.7,
                          "t": 1.64, "sd": 11.6}},
    "up12": {"signal_venue": "upbit", "entry_hours": 12, "label": "Upbit T+12h",
             "note": "clean out-of-sample: +3.99% on 63 tokens, placebo-controlled",
             "backtest": {"n": 63, "mean": 3.99, "median": 11.25, "win": 65.1,
                          "t": 2.55, "sd": 12.4}},
}
SIGNAL_VENUES = ["binance", "coinbase", "upbit"]
ARM_IDS = list(ARMS)
DEFAULT_ARM = "t12"


def arms_for(venue):
    return [a for a in ARM_IDS if ARMS[a]["signal_venue"] == venue]


def arm_venue(arm):
    return ARMS[arm]["signal_venue"]


def arm_entry_hours(arm):
    return ARMS[arm]["entry_hours"]


def arm_perp_by_hours(arm):
    """Identical to the entry hour, by construction. Named separately because the two
    are conceptually different and a future reader should see they cannot drift apart."""
    return ARMS[arm]["entry_hours"]


# ---- the frozen rule, shared by both arms ----------------------------------
ENTRY_HOURS = 12          # retained for the t12 arm and for anything reading one number
TAKE_PROFIT = 0.15        # fraction, favourable
STOP_LOSS = 0.15          # fraction, adverse
MAX_HOLD_HOURS = 72
LEVERAGE = 1.0
POSITION_PCT = 0.17       # SOLVED, not chosen. Size and drawdown are near-proportional
                          # in this strategy, so a drawdown target has exactly one size
                          # that meets it. Bisecting against a bootstrapped p90 drawdown
                          # on the clean out-of-sample sample: a 20% target solves to 17%.
                          #
                          # Was 20%, picked by hand before the drawdown could be targeted.
                          # Changed at 0 closed positions, and it cannot bias the test:
                          # the statistic is the PERCENTAGE return per trade, which size
                          # does not touch. See Amendment 2 in PREREG_ARMS.md.

# ---- paper account ---------------------------------------------------------
# Per arm, not shared: each book starts here and compounds independently.
PAPER_START_EQUITY = 1000.0
CURRENCY = "USDT"

# ---- venue costs, real ------------------------------------------------------
GATE_TAKER_FEE = 0.00075  # 0.075% per side — Gate's own contract spec reports exactly
                          # this on all 850 USDT perps. The 0.05% assumed here until
                          # 2026-07-28 was a guess, and it understated the round trip by
                          # a third. Corrected before any trade closed. VIP tiers reduce
                          # it; the forward test uses the undiscounted rate, because a
                          # cost the account might not get is not a cost to assume away.
# Funding is fetched live per contract, never assumed. A short RECEIVES funding when
# the rate is positive, which on a hyped new listing it usually is.

# ---- eligibility -----------------------------------------------------------
QUOTE_ASSET = "USDT"
# A perpetual must exist by the entry hour. This is not a tunable filter: you cannot
# short what has no perp, and requiring it also excludes stablecoins, liquid-staking
# tokens and tokenised equities, none of which the thesis is about.
# Per-arm; this constant is the widest of them, used only for deciding whether an event
# is worth tracking at all.
PERP_MUST_EXIST_BY_HOURS = max(a["entry_hours"] for a in ARMS.values())
MIN_BOOK_NOTIONAL_USDT = 200.0   # refuse to paper-fill into a book too thin to be real

# ---- liquidity discipline ---------------------------------------------------
# Measured 2026-07-28 on 135 events: median traded volume in the entry hour is $2.9M on
# Binance spot, and the Gate perp runs a median 2.07x that, so about $6M. Against that a
# small order is invisible. Against the tail it is not — RED's entry hour traded $1,072,
# and its first hour had traded $203k, so the collapse is real rather than a data gap.
#
# The budget is set from what execution cost does to the edge, not from taste. Extra
# slippage of 0.25% eats 9% of the 2.71% edge and takes t from 1.99 to 1.80; 1.00% eats
# 37% and takes t to 1.25. So a 1% tolerance is not a safety margin, it is most of the
# thesis.
MAX_PARTICIPATION_PCT = 3.0      # of the entry hour's traded volume; above this, size down
PARTICIPATION_FLOOR_USDT = 50.0  # below this the gate stops mattering, so stop applying it

# Slicing. A single order is only realistic while it is small against the visible book;
# beyond that the book has to be given time to refill. Note the two are different things:
# AKE trades $4.4M an hour with $42 resting on the bid, so volume is in the flow, not in
# the book, and above the trigger there is no size that a single sweep can do honestly.
SLICE_TRIGGER_BOOK_FRAC = 0.25   # slice once the order exceeds this share of visible depth
SLICE_MAX = 6                    # at one slice per tick, 6 x 5min = a 30 minute window
SLICE_MIN_USDT = 100.0           # never cut a slice smaller than this

# ---- operational -----------------------------------------------------------
SCAN_INTERVAL_MINUTES = 5
EVENT_TRACK_DAYS = 10     # stop tracking an event after this
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ---- reporting-only overlays -----------------------------------------------
# The concurrency cap and the token cooldown are NOT applied when collecting trades.
# Amendment 1 of PREREG_ARMS.md established that a gate may size down and must never skip,
# because skipping removes sample points and biases the test. These are computed from the
# recorded trades in the monitor instead. Measured on the clean large-venue history, a cap
# of 1 gave +64.4% CAGR at an 11.2% drawdown against +59.9% at 19.0% for a cap of 2.
REPORT_CONCURRENCY_CAP = 1
REPORT_COOLDOWN_DAYS = 7

# The combined book: every venue's signals merged into ONE account, each token traded once.
# Size is not guessed. Size and drawdown are near-proportional here, so the size is SOLVED
# from a drawdown target on the clean historical sample and the answer recorded below:
#
#   DD target   size   CAGR at the clean +3.46%/trade   peak exposure
#      10%        9%            +26.9%                       9%
#      15%       14%            +45.5%                      14%
#      20%       17%            +58.9%                      17%
#      25%       23%            +85.3%                      23%
#      30%       28%           +111.2%                      28%
#
# At the parameter-free +1.18%/trade the same 20% drawdown buys only +12.8%, and that gap is
# the cost of the entry hour not being identifiable across venues.
COMBINED_DD_TARGET_PCT = 20
COMBINED_SIZE = POSITION_PCT
COMBINED_SIZE_TABLE = {10: 0.09, 15: 0.14, 20: 0.17, 25: 0.23, 30: 0.28}

# ---- endpoints -------------------------------------------------------------
BINANCE_SPOT = "https://data-api.binance.vision/api/v3"
COINBASE_EXCHANGE = "https://api.exchange.coinbase.com"
UPBIT = "https://api.upbit.com/v1"
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
