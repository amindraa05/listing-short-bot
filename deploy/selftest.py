"""End-to-end self test: force a paper trade through every exit path.

Runs against an ISOLATED database so the real forward-test record is never touched.
Fills are genuine — the order book is walked live — so this proves the parts that
matter: book walking, fee accounting, funding sign, and each of the four exits.

A synthetic event is injected with a listing time chosen so BOTH arms' entries fall due
right now, which also proves the two books stay separate. Everything downstream is the
production code path, unmodified.

Usage:  LISTINGBOT_HOME=/tmp/lb-selftest python3 deploy/selftest.py [CONTRACT]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from listingbot import config as C          # noqa: E402
from listingbot import engine, fills, store, venues   # noqa: E402

CONTRACT = sys.argv[1] if len(sys.argv) > 1 else "SOL_USDT"
BASE = CONTRACT.split("_")[0]


def hr(t):
    print("\n" + "=" * 84)
    print(f"  {t}")
    print("=" * 84)


def mark(contract):
    t = venues.gate_ticker(contract)
    return (t or {}).get("last") or (t or {}).get("mark")


def inject(cx, tag, arm):
    """Insert an event whose entry for `arm` is due now, tagged so tests stay separate."""
    now = store.now_ms()
    h = C.arm_entry_hours(arm)
    listed = now - int(h * 3_600_000)
    sym = f"{BASE}{tag}USDT"
    eid = store.add_event(cx, symbol=sym, base=f"{BASE}{tag}", listed_ms=listed,
                          detected_ms=now, perp_venue="gate", perp_symbol=CONTRACT,
                          perp_launch_ms=listed - 3_600_000, gap_hours=-1.0,
                          eligible=0, status="watching",
                          notes="SELFTEST — synthetic event")
    # Only the arm under test is armed; the other is parked so one synthetic listing
    # does not silently open two positions and confuse the exit being checked.
    for a in C.ARM_IDS:
        if a == arm:
            store.set_plan(cx, eid, a, eligible=1, status="watching",
                           entry_due_ms=listed + h * 3_600_000)
        else:
            store.set_plan(cx, eid, a, eligible=0, status="skipped",
                           ineligible_reason="selftest: not the arm under test")
    return eid


def open_one(cx, tag, arm=None):
    arm = arm or C.DEFAULT_ARM
    inject(cx, tag, arm)
    n = engine.open_due_positions(cx)
    if not n:
        print(f"  FAILED to open ({tag}/{arm})")
        return None
    p = cx.execute("SELECT * FROM positions WHERE status='open' "
                   "ORDER BY id DESC LIMIT 1").fetchone()
    print(f"  opened id={p['id']} arm={p['arm']}  entry {p['entry_vwap']:.8g}  "
          f"mid {p['entry_mid']:.8g}  slip {p['entry_slippage_bps']:+.2f}bps  "
          f"spread {p['entry_spread_bps']:.2f}bps  notional {p['notional_usdt']:.2f}  "
          f"fee {p['entry_fee_usdt']:.4f}")
    print(f"  TP {p['tp_price']:.8g}   SL {p['sl_price']:.8g}   "
          f"deadline in {(p['deadline_ms']-store.now_ms())/3_600_000:.1f}h")
    return p


def force(cx, pid, **cols):
    sets = ",".join(f"{k}=?" for k in cols)
    cx.execute(f"UPDATE positions SET {sets} WHERE id=?",
               tuple(cols.values()) + (pid,))
    cx.commit()


def main():
    print("=" * 84)
    print("  LISTINGBOT SELF TEST — isolated database, real order books")
    print("=" * 84)
    print(f"  db        {C.DB_PATH}")
    print(f"  contract  {CONTRACT}")
    print(f"  arms      " + "  ".join(f"{a}=T+{C.arm_entry_hours(a)}h"
                                       for a in C.ARM_IDS))
    print(f"  shared    TP {C.TAKE_PROFIT*100:.0f}%  SL {C.STOP_LOSS*100:.0f}%  "
          f"hold {C.MAX_HOLD_HOURS}h  size {C.POSITION_PCT*100:.0f}% of the arm's book")
    if "selftest" not in C.DB_PATH:
        print("\n  REFUSING: set LISTINGBOT_HOME to a path containing 'selftest' so the")
        print("  real forward-test database cannot be written to by this script.")
        return 1

    cx = store.connect()
    px = mark(CONTRACT)
    if not px:
        print(f"  no mark price for {CONTRACT} — cannot run")
        return 1
    print(f"  live mark {px:.8g}")

    hr("0. BOOK QUOTE — is a fill even possible at this size?")
    eq = store.get_equity(cx, C.DEFAULT_ARM)
    q, err = fills.quote(CONTRACT, "sell", eq * C.POSITION_PCT)
    if q is None:
        print(f"  book refused the size: {err}")
        return 1
    print(f"  bid {q['best_bid']:.8g}  ask {q['best_ask']:.8g}  "
          f"spread {q['spread_bps']:.2f}bps")
    print(f"  vwap {q['vwap']:.8g} for {q['notional_usdt']:.2f} USDT across "
          f"{q['levels_consumed']} level(s), slip {q['slippage_bps']:+.2f}bps")
    print(f"  book depth on the bid side {q['book_depth_usdt']:,.0f} USDT")

    hr("1. TARGET EXIT — move TP above the market so the next check fires it")
    p = open_one(cx, "T")
    if p:
        force(cx, p["id"], tp_price=px * 1.02)
        print(f"  forced TP to {px*1.02:.8g} (above mark) -> expect 'target'")
        engine.manage_open_positions(cx)
        r = cx.execute("SELECT * FROM positions WHERE id=?", (p["id"],)).fetchone()
        print(f"  reason={r['exit_reason']}  gross {r['gross_pct']:+.3f}%  "
              f"funding {r['funding_frac']*100:+.4f}% ({r['funding_periods']}p)  "
              f"net {r['net_pct']:+.3f}%  pnl {r['pnl_usdt']:+.4f}  "
              f"book {store.get_equity(cx, r['arm']):.4f}")

    hr("2. STOP EXIT — move SL below the market")
    p = open_one(cx, "S")
    if p:
        force(cx, p["id"], sl_price=px * 0.98)
        print(f"  forced SL to {px*0.98:.8g} (below mark) -> expect 'stop'")
        engine.manage_open_positions(cx)
        r = cx.execute("SELECT * FROM positions WHERE id=?", (p["id"],)).fetchone()
        print(f"  reason={r['exit_reason']}  net {r['net_pct']:+.3f}%  "
              f"pnl {r['pnl_usdt']:+.4f}  book {store.get_equity(cx, r['arm']):.4f}")

    hr("3. TIME EXIT — put the deadline in the past")
    p = open_one(cx, "H")
    if p:
        force(cx, p["id"], deadline_ms=store.now_ms() - 1000)
        print("  forced deadline into the past -> expect 'time'")
        engine.manage_open_positions(cx)
        r = cx.execute("SELECT * FROM positions WHERE id=?", (p["id"],)).fetchone()
        print(f"  reason={r['exit_reason']}  net {r['net_pct']:+.3f}%  "
              f"pnl {r['pnl_usdt']:+.4f}")

    hr("4. LIQUIDATION GUARD — the safety net that must beat the stop")
    p = open_one(cx, "L")
    if p:
        force(cx, p["id"], entry_vwap=px / 1.96, sl_price=px * 9,
              tp_price=px / 100)
        print(f"  entry rewritten so the mark is +96% against the short, and the SL")
        print(f"  moved far away -> guard must fire before anything else")
        engine.manage_open_positions(cx)
        r = cx.execute("SELECT * FROM positions WHERE id=?", (p["id"],)).fetchone()
        print(f"  reason={r['exit_reason']}  net {r['net_pct']:+.2f}%  "
              f"(a real 1x short would already be gone here)")

    hr("5. ORDERING — stop must win when both stop and target are reachable")
    p = open_one(cx, "O")
    if p:
        force(cx, p["id"], sl_price=px * 0.99, tp_price=px * 1.01)
        print("  both triggers set so either could fire -> stop must win")
        engine.manage_open_positions(cx)
        r = cx.execute("SELECT * FROM positions WHERE id=?", (p["id"],)).fetchone()
        ok = r["exit_reason"] == "stop"
        print(f"  reason={r['exit_reason']}  {'CORRECT' if ok else 'WRONG — adverse must be checked first'}")

    hr("6. SEPARATE BOOKS — a loss in one arm must not touch the other")
    before = {a: store.get_equity(cx, a) for a in C.ARM_IDS}
    other = C.ARM_IDS[1] if len(C.ARM_IDS) > 1 else C.ARM_IDS[0]
    p = open_one(cx, "X", arm=other)
    if p:
        force(cx, p["id"], sl_price=px * 0.98)
        engine.manage_open_positions(cx)
        after = {a: store.get_equity(cx, a) for a in C.ARM_IDS}
        moved = [a for a in C.ARM_IDS if abs(after[a] - before[a]) > 1e-9]
        for a in C.ARM_IDS:
            print(f"  {a:5s} {before[a]:12.4f} -> {after[a]:12.4f}")
        ok = moved == [other]
        print(f"  only {other} moved: {'CORRECT' if ok else 'WRONG — books are shared'}")

    hr("PER-ARM POSITION SIZING")
    for a in C.ARM_IDS:
        print(f"  {a:5s} book {store.get_equity(cx, a):10.4f}  "
              f"next notional {store.get_equity(cx, a)*C.POSITION_PCT:8.2f}")

    hr("RESULT")
    rows = cx.execute("SELECT exit_reason, COUNT(*) n, ROUND(AVG(net_pct),4) avg_net "
                      "FROM positions WHERE status='closed' GROUP BY exit_reason").fetchall()
    for r in rows:
        print(f"  {r['exit_reason']:20s} n={r['n']}  avg net {r['avg_net']:+.4f}%")
    for a in C.ARM_IDS:
        rows = cx.execute("SELECT COUNT(*) n FROM positions WHERE arm=?", (a,)).fetchone()
        print(f"  arm {a:5s} positions {rows['n']}   book "
              f"{store.get_equity(cx, a):.4f}")
    tot = cx.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"]
    op = cx.execute("SELECT COUNT(*) n FROM positions WHERE status='open'").fetchone()["n"]
    fl = cx.execute("SELECT COUNT(*) n FROM fills").fetchone()["n"]
    print(f"\n  positions {tot} ({op} still open)   fills recorded {fl}")
    print(f"  total across arms {store.get_equity(cx):.4f} from "
          f"{C.PAPER_START_EQUITY*len(C.ARM_IDS):.2f}")
    print("\n  Every exit above was a real round trip through the live book, so the")
    print("  small negative net figures are the true cost of trading this size:")
    print("  spread crossed twice plus 0.05% taker each side, which is exactly what")
    print("  the forward test exists to measure.")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
