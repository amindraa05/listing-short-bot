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
ARMS = {
    "t12": {"entry_hours": 12, "label": "T+12h",
            "note": "the operator's hypothesis, never swept",
            "backtest": {"n": 115, "mean": 2.71, "median": 14.77, "win": 62.6,
                         "t": 1.99, "sd": 14.6}},
    "t18": {"entry_hours": 18, "label": "T+18h",
            "note": "middle of the T+14-24h plateau; the sweep peak was T+22h",
            "backtest": {"n": 134, "mean": 4.86, "median": 14.77, "win": 68.7,
                         "t": 4.03, "sd": 14.6}},
}
ARM_IDS = list(ARMS)
DEFAULT_ARM = "t12"


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
POSITION_PCT = 0.20       # of equity per position, set by the operator.
                          # For context on what that implies: the backtest's
                          # bootstrapped p90 drawdown was 35.8% at 30% sizing and
                          # scales roughly linearly, so ~24% at 20%. The historical
                          # ordering gave a kinder 16.7%; size against the p90.

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
