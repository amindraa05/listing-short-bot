"""SQLite persistence. One file, no server, no port — nothing for the host's existing
services to collide with.

Every table carries enough detail to re-audit a decision months later: the book that was
quoted, the levels consumed, the slippage measured. A forward test whose fills cannot be
reconstructed is just a claim.
"""
import json
import os
import sqlite3
import time

from . import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- snapshot of Binance USDT symbols, used to diff for new listings
CREATE TABLE IF NOT EXISTS known_symbols (
  symbol TEXT PRIMARY KEY,
  base TEXT NOT NULL,
  first_seen_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL UNIQUE,
  base TEXT NOT NULL,
  listed_ms INTEGER,             -- first traded HOUR on Binance spot
  detected_ms INTEGER NOT NULL,
  perp_venue TEXT,
  perp_symbol TEXT,
  perp_launch_ms INTEGER,
  gap_hours REAL,                -- perp launch minus spot listing
  eligible INTEGER NOT NULL DEFAULT 0,
  ineligible_reason TEXT,
  entry_due_ms INTEGER,
  status TEXT NOT NULL DEFAULT 'watching',
  notes TEXT
);

-- One row per (listing, arm). The listing facts live in events; what each arm intends
-- to do about them lives here, because eligibility depends on the arm's entry hour: a
-- perp that appears at +15h is tradeable by t18 and not by t12.
CREATE TABLE IF NOT EXISTS arm_plans (
  event_id INTEGER NOT NULL REFERENCES events(id),
  arm TEXT NOT NULL,
  eligible INTEGER NOT NULL DEFAULT 0,
  ineligible_reason TEXT,
  entry_due_ms INTEGER,
  status TEXT NOT NULL DEFAULT 'watching',
  PRIMARY KEY (event_id, arm)
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id),
  arm TEXT NOT NULL DEFAULT 't12',
  base TEXT NOT NULL,
  perp_symbol TEXT NOT NULL,
  side TEXT NOT NULL DEFAULT 'short',
  opened_ms INTEGER NOT NULL,
  entry_vwap REAL NOT NULL,
  entry_mid REAL,
  entry_slippage_bps REAL,
  entry_spread_bps REAL,
  entry_fee_usdt REAL,
  notional_usdt REAL NOT NULL,
  equity_at_open REAL NOT NULL,
  tp_price REAL NOT NULL,
  sl_price REAL NOT NULL,
  deadline_ms INTEGER NOT NULL,
  closed_ms INTEGER,
  exit_vwap REAL,
  exit_mid REAL,
  exit_slippage_bps REAL,
  exit_fee_usdt REAL,
  exit_reason TEXT,
  funding_frac REAL DEFAULT 0,
  funding_periods INTEGER DEFAULT 0,
  gross_pct REAL,
  net_pct REAL,
  pnl_usdt REAL,
  mae_pct REAL DEFAULT 0,        -- worst adverse excursion seen while open
  mfe_pct REAL DEFAULT 0,
  -- execution: what was intended, what was actually achievable, and how it got there
  target_notional_usdt REAL,     -- before the liquidity gate
  participation_pct REAL,        -- of the entry hour's traded volume
  sized_down INTEGER DEFAULT 0,
  slices_planned INTEGER DEFAULT 1,
  slices_done INTEGER DEFAULT 1,
  fill_complete INTEGER DEFAULT 1,
  entry_book_depth_usdt REAL,
  status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  ts_ms INTEGER NOT NULL,
  kind TEXT NOT NULL,            -- 'entry' | 'exit'
  detail_json TEXT NOT NULL      -- the full book quote, for later audit
);

CREATE TABLE IF NOT EXISTS marks (
  position_id INTEGER NOT NULL REFERENCES positions(id),
  ts_ms INTEGER NOT NULL,
  price REAL NOT NULL,
  PRIMARY KEY (position_id, ts_ms)
);

CREATE TABLE IF NOT EXISTS runs (
  ts_ms INTEGER PRIMARY KEY,
  new_events INTEGER DEFAULT 0,
  opened INTEGER DEFAULT 0,
  closed INTEGER DEFAULT 0,
  errors TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_plans_status ON arm_plans(status, entry_due_ms);
"""

# NOT in SCHEMA: an index on positions(arm) cannot be created until the column exists,
# and CREATE TABLE IF NOT EXISTS will not add a column to a table already present. On a
# database written before the arms this ran before the ALTER and aborted every tick.
POST_MIGRATION_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_positions_arm ON positions(arm, status);
"""


def _migrate(cx):
    """Add what the two-arm design needs without dropping anything already recorded.

    Written to be safe on a database that has already traded: a position that predates
    the arms belongs to t12, which is what the column DEFAULT says.
    """
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(positions)")}
    if "arm" not in cols:
        cx.execute("ALTER TABLE positions ADD COLUMN arm TEXT NOT NULL DEFAULT 't12'")
    for col, ddl in (("target_notional_usdt", "REAL"),
                     ("participation_pct", "REAL"),
                     ("sized_down", "INTEGER DEFAULT 0"),
                     ("slices_planned", "INTEGER DEFAULT 1"),
                     ("slices_done", "INTEGER DEFAULT 1"),
                     ("fill_complete", "INTEGER DEFAULT 1"),
                     ("entry_book_depth_usdt", "REAL")):
        if col not in cols:
            cx.execute(f"ALTER TABLE positions ADD COLUMN {col} {ddl}")

    # Per-arm books. The single pre-arm 'equity' key becomes t12's, so a test already
    # running keeps its history instead of silently restarting at 1,000.
    old = cx.execute("SELECT value FROM meta WHERE key='equity'").fetchone()
    for arm in C.ARM_IDS:
        k = "equity:" + arm
        if cx.execute("SELECT 1 FROM meta WHERE key=?", (k,)).fetchone() is None:
            v = (old["value"] if old and arm == C.DEFAULT_ARM
                 else str(C.PAPER_START_EQUITY))
            cx.execute("INSERT INTO meta(key,value) VALUES(?,?)", (k, v))

    # Events recorded before arm_plans existed are flagged, not fixed here: building a
    # plan needs the venue lookups that belong to the tick, not to a migration.
    cx.execute("INSERT OR IGNORE INTO arm_plans(event_id,arm,eligible,status) "
               "SELECT e.id, ?, 0, 'needs_replan' FROM events e "
               "WHERE NOT EXISTS (SELECT 1 FROM arm_plans p WHERE p.event_id=e.id)",
               (C.DEFAULT_ARM,))
    cx.executescript(POST_MIGRATION_SCHEMA)
    cx.commit()


def now_ms():
    return int(time.time() * 1000)


def connect():
    os.makedirs(C.DATA_DIR, exist_ok=True)
    cx = sqlite3.connect(C.DB_PATH, timeout=30)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA busy_timeout=15000")
    cx.executescript(SCHEMA)
    if cx.execute("SELECT 1 FROM meta WHERE key='started_ms'").fetchone() is None:
        cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('started_ms',?)",
                   (str(now_ms()),))
    # Rewritten on every connect, so the recorded rule always matches the code that ran.
    cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('rule',?)",
               (json.dumps({"arms": {a: C.ARMS[a]["entry_hours"] for a in C.ARM_IDS},
                            "tp": C.TAKE_PROFIT, "sl": C.STOP_LOSS,
                            "hold_h": C.MAX_HOLD_HOURS, "size_pct": C.POSITION_PCT,
                            "start_equity_per_arm": C.PAPER_START_EQUITY}),))
    cx.commit()
    _migrate(cx)
    return cx


def get_equity(cx, arm=None):
    """Equity of one arm, or the sum across arms when arm is None."""
    if arm is None:
        return sum(get_equity(cx, a) for a in C.ARM_IDS)
    r = cx.execute("SELECT value FROM meta WHERE key=?", ("equity:" + arm,)).fetchone()
    return float(r["value"]) if r else C.PAPER_START_EQUITY


def set_equity(cx, arm, v):
    cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
               ("equity:" + arm, str(v)))


def set_meta(cx, key, value):
    cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
    cx.commit()


def bootstrap_symbols(cx, symbols):
    """First run stores the snapshot without flagging anything as new — there is no
    prior state to diff against, so calling 470 existing pairs 'new' would be wrong."""
    ts = now_ms()
    cx.executemany(
        "INSERT OR IGNORE INTO known_symbols(symbol,base,first_seen_ms) VALUES(?,?,?)",
        [(s, b, ts) for s, b in symbols.items()])
    cx.commit()


def diff_symbols(cx, symbols):
    have = {r["symbol"] for r in cx.execute("SELECT symbol FROM known_symbols")}
    if not have:
        bootstrap_symbols(cx, symbols)
        return [], []
    new = sorted(set(symbols) - have)
    gone = sorted(have - set(symbols))
    ts = now_ms()
    for s in new:
        cx.execute("INSERT OR IGNORE INTO known_symbols(symbol,base,first_seen_ms) "
                   "VALUES(?,?,?)", (s, symbols[s], ts))
    cx.commit()
    return new, gone


def add_event(cx, **kw):
    cols = ",".join(kw)
    qs = ",".join("?" for _ in kw)
    cx.execute(f"INSERT OR IGNORE INTO events({cols}) VALUES({qs})",
               tuple(kw.values()))
    cx.commit()
    r = cx.execute("SELECT id FROM events WHERE symbol=?", (kw["symbol"],)).fetchone()
    return r["id"] if r else None


def set_plan(cx, event_id, arm, **kw):
    cx.execute("INSERT OR IGNORE INTO arm_plans(event_id,arm) VALUES(?,?)",
               (event_id, arm))
    if kw:
        sets = ",".join(k + "=?" for k in kw)
        cx.execute("UPDATE arm_plans SET " + sets + " WHERE event_id=? AND arm=?",
                   tuple(kw.values()) + (event_id, arm))
    cx.commit()


def plans_awaiting_entry(cx, ts_ms):
    """Every (listing, arm) whose entry hour has arrived, joined to the listing facts."""
    return cx.execute(
        "SELECT p.arm AS arm, p.entry_due_ms AS entry_due_ms, e.* FROM arm_plans p "
        "JOIN events e ON e.id=p.event_id WHERE p.eligible=1 AND p.status='watching' "
        "AND p.entry_due_ms IS NOT NULL AND p.entry_due_ms<=? "
        "ORDER BY p.entry_due_ms", (ts_ms,)).fetchall()


def plans_for(cx, event_id):
    return {r["arm"]: r for r in cx.execute(
        "SELECT * FROM arm_plans WHERE event_id=?", (event_id,))}


def events_needing_plans(cx):
    """Events with no arm plan yet, or one a migration left for the tick to build."""
    return cx.execute(
        "SELECT DISTINCT e.* FROM events e LEFT JOIN arm_plans p ON p.event_id=e.id "
        "WHERE p.event_id IS NULL OR p.status='needs_replan'").fetchall()


def stale_events(cx, ts_ms, days):
    return cx.execute(
        "SELECT * FROM events WHERE status IN ('watching','pending_perp') "
        "AND detected_ms < ?", (ts_ms - days * 86400_000,)).fetchall()


def open_positions(cx):
    return cx.execute("SELECT * FROM positions WHERE status='open'").fetchall()


def filling_positions(cx):
    """Open but not yet fully filled. They already carry exposure, so the exit checks
    must see them too — a partially filled short is a short."""
    return cx.execute("SELECT * FROM positions WHERE status='open' AND "
                      "fill_complete=0 ORDER BY id").fetchall()


def record_run(cx, new_events=0, opened=0, closed=0, errors=None):
    cx.execute("INSERT OR REPLACE INTO runs(ts_ms,new_events,opened,closed,errors) "
               "VALUES(?,?,?,?,?)",
               (now_ms(), new_events, opened, closed,
                json.dumps(errors) if errors else None))
    cx.commit()
