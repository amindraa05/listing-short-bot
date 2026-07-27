"""The tick: detect listings, open paper shorts at T+12h, manage them to exit.

Deliberate properties, each one a lesson from the research:

  * the anchor is the first traded HOUR, never midnight of the listing day
  * eligibility requires a perp by the entry hour, and that is a rule not a filter —
    you cannot short what has no perpetual
  * both fills walk the live order book, so slippage is measured rather than assumed
  * funding is fetched per contract and signed correctly: a short RECEIVES a positive rate
  * the stop is enforced before the target on every check, and a 1x short is force-closed
    near +95% because pretending it survives is fiction
  * nothing here can place a real order; there is no signing code in the project
"""
import json
import logging
import math

from . import config as C
from . import fills, report, store, venues

log = logging.getLogger("listingbot")


def _hours(ms):
    return ms / 3_600_000.0


def scan_new_listings(cx):
    """Diff Binance's USDT universe, then classify each genuinely new symbol."""
    symbols = venues.binance_usdt_symbols()
    if not symbols:
        log.warning("Binance returned no symbols; skipping scan")
        return 0
    new, gone = store.diff_symbols(cx, symbols)
    if gone:
        log.info("delisted since last run: %s", ", ".join(gone))
    if not new:
        return 0

    pi = venues.perp_index()
    added = 0
    for sym in new:
        base = symbols[sym]
        listed_ms = venues.binance_first_hour_ms(sym)
        detected = store.now_ms()
        perp = pi.get(base.upper())
        gap_h = None
        eligible, reason, entry_due, status = 0, None, None, "watching"

        if listed_ms is None:
            reason = "no kline yet; will re-check on a later run"
            status = "pending_perp"
        else:
            entry_due = listed_ms + C.ENTRY_HOURS * 3_600_000
            if perp is None:
                reason = ("no perpetual on Gate, OKX or KuCoin — usually a stablecoin, "
                          "liquid-staking token or tokenised equity")
                status = "pending_perp"
            else:
                gap_h = _hours(perp["launch_ms"] - listed_ms)
                if gap_h > C.PERP_MUST_EXIST_BY_HOURS:
                    reason = (f"perp arrived {gap_h:.1f}h after the listing, later than "
                              f"the T+{C.ENTRY_HOURS}h entry")
                    status = "skipped"
                elif perp["venue"] != "gate":
                    reason = (f"perp is on {perp['venue']}, and paper fills are priced "
                              f"on Gate's book only")
                    status = "skipped"
                else:
                    eligible = 1

        store.add_event(
            cx, symbol=sym, base=base, listed_ms=listed_ms, detected_ms=detected,
            perp_venue=(perp or {}).get("venue"),
            perp_symbol=(perp or {}).get("symbol"),
            perp_launch_ms=(perp or {}).get("launch_ms"),
            gap_hours=gap_h, eligible=eligible, ineligible_reason=reason,
            entry_due_ms=entry_due, status=status)
        added += 1
        log.info("NEW %s (%s) listed=%s perp=%s gap=%s eligible=%s %s",
                 sym, base,
                 "?" if listed_ms is None else f"{listed_ms}",
                 (perp or {}).get("symbol", "none"),
                 "?" if gap_h is None else f"{gap_h:+.1f}h",
                 eligible, reason or "")
    return added


def recheck_pending(cx):
    """A perp can appear after the listing. Re-evaluate anything still pending."""
    rows = cx.execute("SELECT * FROM events WHERE status='pending_perp'").fetchall()
    if not rows:
        return
    pi = venues.perp_index()
    for e in rows:
        listed_ms = e["listed_ms"]
        if listed_ms is None:
            listed_ms = venues.binance_first_hour_ms(e["symbol"])
            if listed_ms is None:
                continue
            cx.execute("UPDATE events SET listed_ms=?, entry_due_ms=? WHERE id=?",
                       (listed_ms, listed_ms + C.ENTRY_HOURS * 3_600_000, e["id"]))
        perp = pi.get(e["base"].upper())
        if perp is None:
            continue
        gap_h = _hours(perp["launch_ms"] - listed_ms)
        if gap_h <= C.PERP_MUST_EXIST_BY_HOURS and perp["venue"] == "gate":
            cx.execute(
                "UPDATE events SET perp_venue=?,perp_symbol=?,perp_launch_ms=?,"
                "gap_hours=?,eligible=1,ineligible_reason=NULL,status='watching' "
                "WHERE id=?",
                (perp["venue"], perp["symbol"], perp["launch_ms"], gap_h, e["id"]))
            log.info("%s became eligible: perp %s at %+.1fh",
                     e["symbol"], perp["symbol"], gap_h)
        else:
            cx.execute(
                "UPDATE events SET perp_venue=?,perp_symbol=?,perp_launch_ms=?,"
                "gap_hours=?,status='skipped',ineligible_reason=? WHERE id=?",
                (perp["venue"], perp["symbol"], perp["launch_ms"], gap_h,
                 f"perp on {perp['venue']} at {gap_h:+.1f}h", e["id"]))
    cx.commit()


def open_due_positions(cx):
    ts = store.now_ms()
    opened = 0
    for e in store.events_awaiting_entry(cx, ts):
        late_h = _hours(ts - e["entry_due_ms"])
        if late_h > 2.0:
            cx.execute("UPDATE events SET status='missed',ineligible_reason=? WHERE id=?",
                       (f"entry window missed by {late_h:.1f}h", e["id"]))
            log.warning("%s: entry missed by %.1fh — not chasing it",
                        e["symbol"], late_h)
            continue

        equity = store.get_equity(cx)
        notional = equity * C.POSITION_PCT
        q, err = fills.quote(e["perp_symbol"], "sell", notional)
        if q is None:
            log.warning("%s: cannot open — %s", e["symbol"], err)
            cx.execute("UPDATE events SET status='skipped',ineligible_reason=? WHERE id=?",
                       (f"entry fill impossible: {err}", e["id"]))
            cx.commit()
            continue

        entry = q["vwap"]
        pid_cur = cx.execute(
            "INSERT INTO positions(event_id,base,perp_symbol,opened_ms,entry_vwap,"
            "entry_mid,entry_slippage_bps,entry_spread_bps,entry_fee_usdt,notional_usdt,"
            "equity_at_open,tp_price,sl_price,deadline_ms) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e["id"], e["base"], e["perp_symbol"], ts, entry, q["mid"],
             q["slippage_bps"], q["spread_bps"], q["fee_usdt"], q["notional_usdt"],
             equity, entry * (1 - C.TAKE_PROFIT), entry * (1 + C.STOP_LOSS),
             ts + C.MAX_HOLD_HOURS * 3_600_000))
        pid = pid_cur.lastrowid
        cx.execute("INSERT INTO fills(position_id,ts_ms,kind,detail_json) VALUES(?,?,?,?)",
                   (pid, ts, "entry", json.dumps(q)))
        cx.execute("UPDATE events SET status='traded' WHERE id=?", (e["id"],))
        cx.commit()
        opened += 1
        log.info("OPEN short %s @ %.8g (mid %.8g, slip %.1fbps, spread %.1fbps, "
                 "%d levels) notional %.2f TP %.8g SL %.8g",
                 e["perp_symbol"], entry, q["mid"], q["slippage_bps"],
                 q["spread_bps"] or -1, q["levels_consumed"], q["notional_usdt"],
                 entry * (1 - C.TAKE_PROFIT), entry * (1 + C.STOP_LOSS))
    return opened


def _close(cx, p, reason, ts):
    q, err = fills.quote(p["perp_symbol"], "buy", p["notional_usdt"])
    if q is None:
        log.error("%s: exit fill failed (%s) — leaving open, will retry next tick",
                  p["perp_symbol"], err)
        return False
    exit_vwap = q["vwap"]
    fr, fp = fills.funding_accrued(p["perp_symbol"], p["opened_ms"], ts)
    gross = (p["entry_vwap"] - exit_vwap) / p["entry_vwap"]
    fee_frac = (p["entry_fee_usdt"] + q["fee_usdt"]) / p["notional_usdt"]
    net = gross - fee_frac + fr           # positive funding is a credit to a short
    pnl = net * p["notional_usdt"]
    cx.execute(
        "UPDATE positions SET closed_ms=?,exit_vwap=?,exit_mid=?,exit_slippage_bps=?,"
        "exit_fee_usdt=?,exit_reason=?,funding_frac=?,funding_periods=?,gross_pct=?,"
        "net_pct=?,pnl_usdt=?,status='closed' WHERE id=?",
        (ts, exit_vwap, q["mid"], q["slippage_bps"], q["fee_usdt"], reason, fr, fp,
         gross * 100, net * 100, pnl, p["id"]))
    cx.execute("INSERT INTO fills(position_id,ts_ms,kind,detail_json) VALUES(?,?,?,?)",
               (p["id"], ts, "exit", json.dumps(q)))
    store.set_equity(cx, store.get_equity(cx) + pnl)
    cx.commit()
    log.info("CLOSE %s %s @ %.8g  gross %+.2f%% fee %-.2f%% funding %+.3f%% "
             "net %+.2f%%  pnl %+.2f USDT  equity %.2f",
             p["perp_symbol"], reason, exit_vwap, gross * 100, fee_frac * 100,
             fr * 100, net * 100, pnl, store.get_equity(cx))
    return True


def manage_open_positions(cx):
    ts = store.now_ms()
    closed = 0
    for p in store.open_positions(cx):
        t = venues.gate_ticker(p["perp_symbol"])
        px = (t or {}).get("last") or (t or {}).get("mark")
        if not px:
            log.warning("%s: no mark price this tick", p["perp_symbol"])
            continue
        cx.execute("INSERT OR REPLACE INTO marks(position_id,ts_ms,price) VALUES(?,?,?)",
                   (p["id"], ts, px))
        adverse = (px / p["entry_vwap"] - 1) * 100
        favour = (1 - px / p["entry_vwap"]) * 100
        cx.execute("UPDATE positions SET mae_pct=MAX(mae_pct,?), mfe_pct=MAX(mfe_pct,?) "
                   "WHERE id=?", (adverse, favour, p["id"]))
        cx.commit()

        # adverse always evaluated first — the conservative convention
        if px >= p["entry_vwap"] * (1 + 0.95):
            if _close(cx, p, "liquidation_guard", ts):
                closed += 1
            continue
        if px >= p["sl_price"]:
            if _close(cx, p, "stop", ts):
                closed += 1
            continue
        if px <= p["tp_price"]:
            if _close(cx, p, "target", ts):
                closed += 1
            continue
        if ts >= p["deadline_ms"]:
            if _close(cx, p, "time", ts):
                closed += 1
    return closed


def expire_stale(cx):
    ts = store.now_ms()
    for e in store.stale_events(cx, ts, C.EVENT_TRACK_DAYS):
        cx.execute("UPDATE events SET status='expired' WHERE id=?", (e["id"],))
    cx.commit()


def tick(cx):
    errors = []
    new = opened = closed = 0
    for label, fn in (("scan", lambda: scan_new_listings(cx)),
                      ("recheck", lambda: recheck_pending(cx)),
                      ("open", lambda: open_due_positions(cx)),
                      ("manage", lambda: manage_open_positions(cx)),
                      ("expire", lambda: expire_stale(cx))):
        try:
            r = fn()
            if label == "scan":
                new = r or 0
            elif label == "open":
                opened = r or 0
            elif label == "manage":
                closed = r or 0
        except Exception as e:                                  # noqa: BLE001
            log.exception("%s failed", label)
            errors.append(f"{label}: {type(e).__name__}: {e}")
    store.record_run(cx, new, opened, closed, errors or None)
    # The monitor page is regenerated every tick so it can never be stale. It is a
    # file, not a server — this bot still binds no port on a host running live trading.
    try:
        report.write(cx)
    except Exception as e:                                      # noqa: BLE001
        log.warning("monitor page not written: %s", e)
        errors.append(f"report: {type(e).__name__}: {e}")
    return {"new_events": new, "opened": opened, "closed": closed, "errors": errors}
