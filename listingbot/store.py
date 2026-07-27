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

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id),
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
"""


def now_ms():
    return int(time.time() * 1000)


def connect():
    os.makedirs(C.DATA_DIR, exist_ok=True)
    cx = sqlite3.connect(C.DB_PATH, timeout=30)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA busy_timeout=15000")
    cx.executescript(SCHEMA)
    cur = cx.execute("SELECT value FROM meta WHERE key='equity'")
    if cur.fetchone() is None:
        cx.execute("INSERT INTO meta(key,value) VALUES('equity',?)",
                   (str(C.PAPER_START_EQUITY),))
        cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('started_ms',?)",
                   (str(now_ms()),))
        cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('rule',?)",
                   (json.dumps({"entry_h": C.ENTRY_HOURS, "tp": C.TAKE_PROFIT,
                                "sl": C.STOP_LOSS, "hold_h": C.MAX_HOLD_HOURS,
                                "size_pct": C.POSITION_PCT}),))
        cx.commit()
    return cx


def get_equity(cx):
    r = cx.execute("SELECT value FROM meta WHERE key='equity'").fetchone()
    return float(r["value"]) if r else C.PAPER_START_EQUITY


def set_equity(cx, v):
    cx.execute("UPDATE meta SET value=? WHERE key='equity'", (str(v),))


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


def events_awaiting_entry(cx, ts_ms):
    return cx.execute(
        "SELECT * FROM events WHERE eligible=1 AND status='watching' "
        "AND entry_due_ms IS NOT NULL AND entry_due_ms<=? ORDER BY entry_due_ms",
        (ts_ms,)).fetchall()


def stale_events(cx, ts_ms, days):
    return cx.execute(
        "SELECT * FROM events WHERE status IN ('watching','pending_perp') "
        "AND detected_ms < ?", (ts_ms - days * 86400_000,)).fetchall()


def open_positions(cx):
    return cx.execute("SELECT * FROM positions WHERE status='open'").fetchall()


def record_run(cx, new_events=0, opened=0, closed=0, errors=None):
    cx.execute("INSERT OR REPLACE INTO runs(ts_ms,new_events,opened,closed,errors) "
               "VALUES(?,?,?,?,?)",
               (now_ms(), new_events, opened, closed,
                json.dumps(errors) if errors else None))
    cx.commit()
