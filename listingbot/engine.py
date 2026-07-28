"""The tick: detect listings, open paper shorts for each arm at its entry hour, manage
them to exit.

TWO ARMS run side by side (see PREREG_ARMS.md): t12 enters at T+12h, t18 at T+18h, each
with its own separate 1,000 USDT book. A listing is usually traded by both, and that is
the point — the arms are compared pairwise on the same listings, which is what removes the
between-listing variance that left the backtest comparison at t 1.50.

Deliberate properties, each one a lesson from the research:

  * the anchor is the first traded HOUR, never midnight of the listing day
  * eligibility requires a perp by the entry hour, and that is a rule not a filter —
    you cannot short what has no perpetual. It is therefore PER ARM: a perp appearing at
    +15h is tradeable by t18 and not by t12, and half the fall from $6,180 to $2,269 in
    the research came from getting exactly that wrong
  * both fills walk the live order book, so slippage is measured rather than assumed
  * the intended size is checked against the entry hour's TRADED VOLUME before anything
    is sent, and cut to fit if it is too large a share of it
  * an order too big for the visible book is sliced across ticks instead of swept, since
    on these contracts the liquidity is in the flow and not in the book
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


def plan_arms(cx, e):
    """Decide, per arm, whether this listing is tradeable and when.

    Called from the scan and again from the recheck, because a perp arriving later can
    turn a skip into a trade for the later arm only.
    """
    listed_ms, gap_h = e["listed_ms"], e["gap_hours"]
    venue, psym = e["perp_venue"], e["perp_symbol"]
    for arm in C.ARM_IDS:
        h = C.arm_entry_hours(arm)
        if listed_ms is None:
            store.set_plan(cx, e["id"], arm, eligible=0, entry_due_ms=None,
                           status="watching",
                           ineligible_reason="no kline yet; re-checked on a later run")
            continue
        due = listed_ms + h * 3_600_000
        if psym is None:
            store.set_plan(cx, e["id"], arm, eligible=0, entry_due_ms=due,
                           status="watching",
                           ineligible_reason="no perpetual on Gate, OKX or KuCoin yet")
        elif venue != "gate":
            store.set_plan(cx, e["id"], arm, eligible=0, entry_due_ms=due,
                           status="skipped",
                           ineligible_reason=f"perp is on {venue}; paper fills are "
                                             f"priced on Gate's book only")
        elif gap_h is not None and gap_h > C.arm_perp_by_hours(arm):
            store.set_plan(cx, e["id"], arm, eligible=0, entry_due_ms=due,
                           status="skipped",
                           ineligible_reason=f"perp arrived {gap_h:+.1f}h after the "
                                             f"listing, after this arm's T+{h}h entry")
        else:
            store.set_plan(cx, e["id"], arm, eligible=1, entry_due_ms=due,
                           status="watching", ineligible_reason=None)


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
        gap_h = (_hours(perp["launch_ms"] - listed_ms)
                 if perp and listed_ms is not None else None)
        # The event row holds only what is true of the listing itself. Whether it is
        # tradeable, and when, differs per arm and lives in arm_plans.
        waiting = listed_ms is None or perp is None
        eid = store.add_event(
            cx, symbol=sym, base=base, listed_ms=listed_ms, detected_ms=detected,
            perp_venue=(perp or {}).get("venue"),
            perp_symbol=(perp or {}).get("symbol"),
            perp_launch_ms=(perp or {}).get("launch_ms"),
            gap_hours=gap_h, eligible=0,
            status="pending_perp" if waiting else "watching")
        if eid:
            plan_arms(cx, cx.execute("SELECT * FROM events WHERE id=?",
                                     (eid,)).fetchone())
            plans = store.plans_for(cx, eid)
            log.info("NEW %s (%s) perp=%s gap=%s  %s", sym, base,
                     (perp or {}).get("symbol", "none"),
                     "?" if gap_h is None else f"{gap_h:+.1f}h",
                     "  ".join(f"{a}={'yes' if plans[a]['eligible'] else 'no'}"
                               for a in C.ARM_IDS if a in plans))
        added += 1
    return added


def replan_orphans(cx):
    """Build arm plans for events that predate them, or that a migration flagged."""
    for e in store.events_needing_plans(cx):
        plan_arms(cx, e)
        log.info("built arm plans for %s", e["symbol"])


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
        cx.execute("UPDATE events SET perp_venue=?,perp_symbol=?,perp_launch_ms=?,"
                   "gap_hours=?,status='watching' WHERE id=?",
                   (perp["venue"], perp["symbol"], perp["launch_ms"], gap_h, e["id"]))
        cx.commit()
        fresh = cx.execute("SELECT * FROM events WHERE id=?", (e["id"],)).fetchone()
        plan_arms(cx, fresh)
        plans = store.plans_for(cx, e["id"])
        elig = [a for a in C.ARM_IDS if plans.get(a, {})["eligible"]]
        log.info("%s: perp %s at %+.1fh — eligible for %s",
                 e["symbol"], perp["symbol"], gap_h,
                 ", ".join(elig) if elig else "no arm")
    cx.commit()


def plan_size(contract, equity):
    """Decide what can honestly be traded, before anything is sent.

    Two separate limits, because they fail in different ways:

      participation  the order as a share of what the contract actually TRADES in an
                     hour. Too large and the price moves because of you. Measured at
                     3% because extra slippage of 0.25% already eats 9% of the 2.71%
                     edge, and 1% eats 37%.
      book depth     the order as a share of what is RESTING right now. Too large and a
                     single sweep is fiction, so the order is sliced instead.

    Returning a smaller notional is safe for the forward test: the statistical test is on
    percentage returns, and cutting the notional changes the dollar P&L without touching
    the percentage. Skipping an event would NOT be safe, because that removes it from the
    sample, so this function never skips — it sizes down, and lets the existing
    book-too-thin rule be the only thing that refuses.
    """
    want = equity * C.POSITION_PCT
    note = None
    hourly = venues.gate_hourly_volume(contract)
    part = (want / hourly * 100) if hourly else None

    if hourly and want > C.PARTICIPATION_FLOOR_USDT:
        cap = hourly * C.MAX_PARTICIPATION_PCT / 100
        if want > cap:
            note = (f"sized down from {want:.0f} to {cap:.0f} USDT: the entry hour "
                    f"traded {hourly:,.0f} and {want:.0f} would have been "
                    f"{part:.1f}% of it")
            # No floor here. MIN_BOOK_NOTIONAL_USDT is a minimum BOOK DEPTH, and using it
            # as a minimum order size pushed the order back above the very cap this gate
            # exists to enforce — CHIP came out at 3.77% against a 3.00% limit. The
            # book-depth check inside fills.quote is what refuses an unfillable order.
            want = cap
            part = want / hourly * 100

    ob = venues.gate_order_book(contract, limit=100)
    depth = fills.book_depth_usdt(ob["bids"]) if ob and ob["bids"] else 0.0
    slices = 1
    if depth > 0 and want > depth * C.SLICE_TRIGGER_BOOK_FRAC:
        slices = min(C.SLICE_MAX,
                     max(2, math.ceil(want / (depth * C.SLICE_TRIGGER_BOOK_FRAC))))
        if want / slices < C.SLICE_MIN_USDT:
            slices = max(1, int(want // C.SLICE_MIN_USDT))
    return {"notional": want, "hourly_volume": hourly, "participation": part,
            "slices": max(1, slices), "book_depth": depth, "note": note}


def open_due_positions(cx):
    """One position per (listing, arm) whose entry hour has arrived.

    Each arm sizes against its OWN book, so a drawdown in one cannot shrink the other's
    positions and the two return series stay independently comparable.
    """
    ts = store.now_ms()
    opened = 0
    for e in store.plans_awaiting_entry(cx, ts):
        arm = e["arm"]
        late_h = _hours(ts - e["entry_due_ms"])
        if late_h > 2.0:
            store.set_plan(cx, e["id"], arm, status="missed",
                           ineligible_reason=f"entry window missed by {late_h:.1f}h")
            log.warning("%s/%s: entry missed by %.1fh — not chasing it",
                        e["symbol"], arm, late_h)
            continue

        equity = store.get_equity(cx, arm)
        plan = plan_size(e["perp_symbol"], equity)
        if plan["note"]:
            log.info("%s/%s: %s", e["symbol"], arm, plan["note"])
        first = plan["notional"] / plan["slices"]

        q, err = fills.quote(e["perp_symbol"], "sell", first)
        if q is None:
            log.warning("%s/%s: cannot open — %s", e["symbol"], arm, err)
            store.set_plan(cx, e["id"], arm, status="skipped",
                           ineligible_reason=f"entry fill impossible: {err}")
            continue

        entry = q["vwap"]
        pid_cur = cx.execute(
            "INSERT INTO positions(event_id,arm,base,perp_symbol,opened_ms,entry_vwap,"
            "entry_mid,entry_slippage_bps,entry_spread_bps,entry_fee_usdt,notional_usdt,"
            "equity_at_open,tp_price,sl_price,deadline_ms,target_notional_usdt,"
            "participation_pct,sized_down,slices_planned,slices_done,fill_complete,"
            "entry_book_depth_usdt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e["id"], arm, e["base"], e["perp_symbol"], ts, entry, q["mid"],
             q["slippage_bps"], q["spread_bps"], q["fee_usdt"], q["notional_usdt"],
             equity, entry * (1 - C.TAKE_PROFIT), entry * (1 + C.STOP_LOSS),
             ts + C.MAX_HOLD_HOURS * 3_600_000, plan["notional"], plan["participation"],
             1 if plan["note"] else 0, plan["slices"], 1,
             1 if plan["slices"] == 1 else 0, plan["book_depth"]))
        pid = pid_cur.lastrowid
        cx.execute("INSERT INTO fills(position_id,ts_ms,kind,detail_json) VALUES(?,?,?,?)",
                   (pid, ts, "entry", json.dumps(q)))
        cx.commit()
        store.set_plan(cx, e["id"], arm, status="traded")
        opened += 1
        log.info("OPEN %s short %s @ %.8g (mid %.8g, slip %.1fbps, spread %.1fbps, "
                 "%d levels) notional %.2f of %.2f%s  part %s  TP %.8g SL %.8g",
                 arm, e["perp_symbol"], entry, q["mid"], q["slippage_bps"],
                 q["spread_bps"] or -1, q["levels_consumed"], q["notional_usdt"],
                 plan["notional"],
                 f" (slice 1/{plan['slices']})" if plan["slices"] > 1 else "",
                 "?" if plan["participation"] is None else f"{plan['participation']:.2f}%",
                 entry * (1 - C.TAKE_PROFIT), entry * (1 + C.STOP_LOSS))
    return opened


def continue_filling(cx):
    """Execute the next slice of any position still filling, one slice per tick.

    Slicing the ENTRY only. A stop or a target has to cross immediately — waiting for a
    better fill while the position runs against you is a worse trade than the slippage
    it saves. The time exit could be sliced too and is not, because at the sizes this
    account runs it would never trigger; that is the next piece if the capital grows.
    """
    ts = store.now_ms()
    for p in store.filling_positions(cx):
        done, planned = p["slices_done"], p["slices_planned"]
        remaining = (p["target_notional_usdt"] or p["notional_usdt"]) - p["notional_usdt"]
        if done >= planned or remaining < C.SLICE_MIN_USDT:
            cx.execute("UPDATE positions SET fill_complete=1 WHERE id=?", (p["id"],))
            cx.commit()
            continue
        size = min(remaining, (p["target_notional_usdt"] or 0) / max(1, planned))
        q, err = fills.quote(p["perp_symbol"], "sell", size)
        if q is None:
            # The book thinned out mid-fill. Stop here and trade what was achieved
            # rather than pretending the rest filled somewhere.
            log.warning("%s: slice %d/%d abandoned (%s) — running with %.2f of %.2f",
                        p["perp_symbol"], done + 1, planned, err,
                        p["notional_usdt"], p["target_notional_usdt"])
            cx.execute("UPDATE positions SET fill_complete=1 WHERE id=?", (p["id"],))
            cx.commit()
            continue

        filled = p["notional_usdt"] + q["notional_usdt"]
        vwap = ((p["entry_vwap"] * p["notional_usdt"] + q["vwap"] * q["notional_usdt"])
                / filled)
        cx.execute(
            "UPDATE positions SET entry_vwap=?, notional_usdt=?, "
            "entry_fee_usdt=entry_fee_usdt+?, slices_done=slices_done+1, "
            "fill_complete=?, tp_price=?, sl_price=? WHERE id=?",
            (vwap, filled, q["fee_usdt"], 1 if done + 1 >= planned else 0,
             vwap * (1 - C.TAKE_PROFIT), vwap * (1 + C.STOP_LOSS), p["id"]))
        cx.execute("INSERT INTO fills(position_id,ts_ms,kind,detail_json) VALUES(?,?,?,?)",
                   (p["id"], ts, "entry", json.dumps(q)))
        cx.commit()
        log.info("FILL %s slice %d/%d  %.2f @ %.8g (slip %.1fbps) -> %.2f of %.2f, "
                 "vwap %.8g", p["perp_symbol"], done + 1, planned, q["notional_usdt"],
                 q["vwap"], q["slippage_bps"], filled, p["target_notional_usdt"], vwap)


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
    arm = p["arm"]
    store.set_equity(cx, arm, store.get_equity(cx, arm) + pnl)
    cx.commit()
    log.info("CLOSE %s %s %s @ %.8g  gross %+.2f%% fee %-.2f%% funding %+.3f%% "
             "net %+.2f%%  pnl %+.2f USDT  book %.2f",
             arm, p["perp_symbol"], reason, exit_vwap, gross * 100, fee_frac * 100,
             fr * 100, net * 100, pnl, store.get_equity(cx, arm))
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
        cx.execute("UPDATE arm_plans SET status='expired',ineligible_reason="
                   "COALESCE(ineligible_reason,'no perp within the tracking window') "
                   "WHERE event_id=? AND status='watching'", (e["id"],))
    cx.commit()


def tick(cx):
    errors = []
    new = opened = closed = 0
    for label, fn in (("scan", lambda: scan_new_listings(cx)),
                      ("replan", lambda: replan_orphans(cx)),
                      ("recheck", lambda: recheck_pending(cx)),
                      ("open", lambda: open_due_positions(cx)),
                      ("fill", lambda: continue_filling(cx)),
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
