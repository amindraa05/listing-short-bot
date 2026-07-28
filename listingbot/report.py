"""Generate the paper-trade monitor as a single self-contained HTML file.

Written after every tick so the page is never stale. No web server, no port, no nginx —
the file is published by committing it, which is why this bot still binds nothing on a
host that also runs live trading.

Two arms run side by side (see PREREG_ARMS.md), so the page has to answer two questions
without letting either flatter the other:

  * per arm, how does the live result sit against that arm's backtest expectation
  * across arms, is t18 minus t12 positive ON LISTINGS BOTH TRADED — the paired test the
    backtest could not settle, and the reason two arms exist at all

The pre-agreed stop signal is evaluated per arm rather than described, and the trade count
needed before any of it means anything is shown as a progress bar.
"""
import html
import json
import math
import os
import time

from . import config as C
from . import store

BAR = 2.4854              # 2.0 + 0.35*ln(4), for the four pre-declared arms
CAP = 1                   # reporting overlay only; collection is uncapped by design
COOLDOWN_D = 7
STOP_SIGNAL_TRADES = 15
STOP_SIGNAL_WINRATE = 40.0
RESEARCH_URL = "https://amindraa05.github.io/listing-short-bot/"
PREREG_URL = ("https://github.com/amindraa05/listing-short-bot/blob/main/"
              "PREREG_VENUES.md")


def _fmt_ts(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else "-"


def _stats(rows):
    nets = [r["net_pct"] for r in rows if r["net_pct"] is not None]
    st = {"n": len(nets)}
    if not nets:
        return st
    mean = sum(nets) / len(nets)
    st.update({"mean": mean, "win": sum(1 for x in nets if x > 0) / len(nets) * 100,
               "median": sorted(nets)[len(nets) // 2],
               "sum_usdt": sum(r["pnl_usdt"] or 0 for r in rows)})
    if len(nets) > 2:
        sd = (sum((x - mean) ** 2 for x in nets) / (len(nets) - 1)) ** 0.5
        st["sd"] = sd
        st["t"] = mean / (sd / math.sqrt(len(nets))) if sd > 0 else 0.0
    for key, col in (("slip_in", "entry_slippage_bps"), ("slip_out", "exit_slippage_bps")):
        v = [r[col] for r in rows if r[col] is not None]
        if v:
            st[key] = sum(v) / len(v)
    f = [r["funding_frac"] or 0 for r in rows]
    if f:
        st["funding"] = sum(f) / len(f) * 100
    return st


def gather(cx):
    started = cx.execute("SELECT value FROM meta WHERE key='started_ms'").fetchone()
    closed = cx.execute(
        "SELECT p.*, e.gap_hours FROM positions p LEFT JOIN events e ON e.id=p.event_id "
        "WHERE p.status='closed' ORDER BY p.opened_ms").fetchall()
    openp = cx.execute(
        "SELECT p.*, e.gap_hours FROM positions p LEFT JOIN events e ON e.id=p.event_id "
        "WHERE p.status='open' ORDER BY p.opened_ms").fetchall()
    events = cx.execute(
        "SELECT * FROM events ORDER BY detected_ms DESC LIMIT 30").fetchall()
    plans = {}
    for r in cx.execute("SELECT * FROM arm_plans"):
        plans.setdefault(r["event_id"], {})[r["arm"]] = r

    arms = {}
    for a in C.ARM_IDS:
        rows = [r for r in closed if r["arm"] == a]
        arms[a] = {"stats": _stats(rows), "closed": rows,
                   "open": [r for r in openp if r["arm"] == a],
                   "equity": store.get_equity(cx, a)}

    # The paired test compares the two BINANCE arms only. It exists to settle the entry
    # hour on one venue's listings, so pairing it against an arm fed by a different venue
    # would compare two different event sets and mean nothing.
    by_arm = {a: {r["base"]: r for r in arms[a]["closed"]} for a in C.ARM_IDS}
    binance_arms = [a for a in C.ARM_IDS if C.arm_venue(a) == "binance"]
    a1 = binance_arms[0]
    a2 = binance_arms[1] if len(binance_arms) > 1 else binance_arms[0]
    shared = sorted(set(by_arm[a1]) & set(by_arm[a2]))
    diffs = [(b, by_arm[a2][b]["net_pct"] - by_arm[a1][b]["net_pct"]) for b in shared]
    paired = {"n": len(diffs), "pairs": diffs, "lo": a1, "hi": a2}
    if len(diffs) > 2:
        d = [x for _, x in diffs]
        mean = sum(d) / len(d)
        sd = (sum((x - mean) ** 2 for x in d) / (len(d) - 1)) ** 0.5
        se = sd / math.sqrt(len(d))
        paired.update({"mean": mean, "sd": sd, "se": se,
                       "t": mean / se if se else 0.0,
                       "wins": sum(1 for x in d if x > 0),
                       "losses": sum(1 for x in d if x < 0)})

    # A cap-1 portfolio computed from the recorded trades. It is NOT applied to
    # collection: Amendment 1 established that a gate may size down and must never skip,
    # because skipping removes sample points. So the cap is an overlay on the record, and
    # both figures are published side by side.
    cap = _capped_portfolio(closed)

    last_run = cx.execute("SELECT * FROM runs ORDER BY ts_ms DESC LIMIT 1").fetchone()
    return {"arms": arms, "paired": paired, "cap": cap, "closed": closed, "open": openp,
            "events": events, "plans": plans, "last_run": last_run,
            "started_ms": int(started["value"]) if started else store.now_ms(),
            "runs_24h": cx.execute("SELECT COUNT(*) n FROM runs WHERE ts_ms>?",
                                   (store.now_ms() - 86400_000,)).fetchone()["n"]}


def _capped_portfolio(closed, size=None, cap=CAP, cooldown_d=COOLDOWN_D):
    """ONE account fed by every venue, each token traded once, at most `cap` open at a time.

    This is the combined book. It is computed from the record rather than collected
    separately, and that is not a shortcut — it is arithmetically the same thing, because
    every arm already takes every eligible listing. Computing it here keeps the per-arm
    measurement intact as well, which a fifth self-collecting arm would have destroyed.

    A trade is taken only if a slot is free and the token has not been traded within
    `cooldown_d` days. Cross-venue duplicates therefore resolve to ONE trade, and the
    FIRST venue to list wins — the thesis is that the pump follows the listing, so the
    earliest listing is the event.

    Size defaults to the drawdown-targeted figure rather than the per-arm size: on the
    clean historical sample, size and drawdown are near-proportional, so a 20% drawdown
    target solves to 17% per position and returned +58.9% CAGR at +3.46% per trade.
    """
    size = C.COMBINED_SIZE if size is None else size
    rows = sorted([r for r in closed if r["closed_ms"] and r["net_pct"] is not None],
                  key=lambda r: r["opened_ms"])
    eq = C.PAPER_START_EQUITY
    peak = eq
    open_slots = []            # (closed_ms, notional, net_pct)
    last_seen = {}
    taken = skipped_cap = skipped_cool = 0
    max_dd = 0.0
    for r in rows:
        now = r["opened_ms"]
        for sl in [x for x in open_slots if x[0] <= now]:
            eq += sl[1] * sl[2] / 100.0
            open_slots.remove(sl)
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100)
        if last_seen.get(r["base"], -1 << 62) > now - cooldown_d * 86400_000:
            skipped_cool += 1
            continue
        if len(open_slots) >= cap:
            skipped_cap += 1
            continue
        open_slots.append((r["closed_ms"], eq * size, r["net_pct"]))
        last_seen[r["base"]] = now
        taken += 1
    for sl in sorted(open_slots, key=lambda x: x[0]):
        eq += sl[1] * sl[2] / 100.0
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    venues_used = sorted({C.arm_venue(r["arm"]) for r in rows})
    return {"taken": taken, "skipped_cap": skipped_cap, "skipped_cool": skipped_cool,
            "equity": eq, "max_dd": max_dd, "size": size, "cap": cap,
            "venues": venues_used,
            "pnl_pct": (eq / C.PAPER_START_EQUITY - 1) * 100}


def _chip(state, text):
    return f'<span class="chip {state}">{html.escape(str(text))}</span>'


def _num(v, fmt="{:+.2f}%"):
    return "—" if v is None else fmt.format(v)


def _verdict(st):
    n = st["n"]
    if n < STOP_SIGNAL_TRADES:
        return "mid", (f"{STOP_SIGNAL_TRADES - n} more closed trades before the stop "
                       f"check means anything.")
    if st.get("win", 100) <= STOP_SIGNAL_WINRATE:
        return "no", (f"STOP SIGNAL — win rate {st['win']:.1f}% at or below "
                      f"{STOP_SIGNAL_WINRATE:.0f}% after {n} trades. Agreed in advance "
                      f"as the point to stop this arm.")
    return "ok", (f"Win rate {st['win']:.1f}% over {n} trades is above the "
                  f"{STOP_SIGNAL_WINRATE:.0f}% stop line. Not a confirmation.")


def render(d):
    arms, paired = d["arms"], d["paired"]
    days = (store.now_ms() - d["started_ms"]) / 86400_000
    total_eq = sum(arms[a]["equity"] for a in C.ARM_IDS)
    total_start = C.PAPER_START_EQUITY * len(C.ARM_IDS)

    # ---- per-arm panels ----------------------------------------------------
    panels = []
    for a in C.ARM_IDS:
        st, cfg = arms[a]["stats"], C.ARMS[a]
        bt, eq = cfg["backtest"], arms[a]["equity"]
        state, verdict = _verdict(st)
        pnl = (eq / C.PAPER_START_EQUITY - 1) * 100
        prog = min(100, st["n"] / STOP_SIGNAL_TRADES * 100)
        panels.append(f"""
    <div class="arm">
      <div class="arm-h"><span class="tag">{a}</span>
        <strong>{cfg["label"]}</strong>
        <span class="chip mid">{C.arm_venue(a)}</span>
        <span class="dim small">{html.escape(cfg["note"])}</span></div>
      <div class="arm-eq {"pos" if pnl >= 0 else "neg"}">{eq:,.2f}
        <span class="dim">{pnl:+.2f}% &middot; own book</span></div>
      <dl>
        <dt>closed</dt><dd>{st["n"]}</dd>
        <dt>open</dt><dd>{len(arms[a]["open"])}</dd>
        <dt>win rate</dt><dd>{_num(st.get("win"), "{:.1f}%")}
          <span class="dim">bt {bt["win"]}%</span></dd>
        <dt>mean</dt><dd>{_num(st.get("mean"))}
          <span class="dim">bt {bt["mean"]:+.2f}%</span></dd>
        <dt>median</dt><dd>{_num(st.get("median"))}
          <span class="dim">bt {bt["median"]:+.2f}%</span></dd>
        <dt>t</dt><dd>{_num(st.get("t"), "{:+.2f}")}
          <span class="dim">bar {BAR:.2f}</span></dd>
        <dt>P&amp;L</dt><dd>{_num(st.get("sum_usdt"), "{:+.2f}")} USDT</dd>
      </dl>
      <div class="note {state}">{html.escape(verdict)}</div>
      <div class="bar"><span style="width:{prog:.0f}%"></span></div>
    </div>""")

    # ---- paired comparison -------------------------------------------------
    if paired["n"] < 3:
        pair_body = (f'<p class="dim">{paired["n"]} listing(s) so far have been closed by '
                     f'both arms. This test needs at least three before it says anything, '
                     f'and it is the reason both arms exist.</p>')
    else:
        sig = ("ok" if paired["t"] >= BAR else
               ("no" if paired["t"] <= -BAR else "mid"))
        reading = {"ok": f'{paired["hi"]} is ahead by more than the bar',
                   "no": f'{paired["lo"]} is ahead by more than the bar',
                   "mid": "not distinguishable from noise yet"}[sig]
        rows = "".join(
            f'<tr><td class="sym">{html.escape(b)}</td>'
            f'<td class="m {"pos" if x > 0 else "neg"}">{x:+.2f} pp</td></tr>'
            for b, x in sorted(paired["pairs"], key=lambda kv: -kv[1]))
        pair_body = f"""
      <div class="pair">
        <div>
          <div class="big {"pos" if paired["mean"] > 0 else "neg"}">{paired["mean"]:+.2f} pp</div>
          <div class="dim small">mean of {paired["hi"]} minus {paired["lo"]},
            paired on {paired["n"]} listings both arms closed</div>
          <dl>
            <dt>t</dt><dd>{paired["t"]:+.2f} {_chip(sig, reading)}</dd>
            <dt>95% CI</dt><dd>{paired["mean"]-1.96*paired["se"]:+.2f} pp ..
              {paired["mean"]+1.96*paired["se"]:+.2f} pp</dd>
            <dt>sd</dt><dd>{paired["sd"]:.2f} pp</dd>
            <dt>split</dt><dd>{paired["hi"]} better on {paired["wins"]},
              worse on {paired["losses"]}</dd>
            <dt>backtest</dt><dd>+1.82 pp at t 1.50 &mdash; inconclusive, which is why
              this is being measured forward</dd>
          </dl>
        </div>
        <div class="tablewrap"><table>
          <thead><tr><th>Token</th><th>{paired["hi"]} &minus; {paired["lo"]}</th></tr></thead>
          <tbody>{rows}</tbody></table></div>
      </div>"""

    # ---- tables ------------------------------------------------------------
    def notional_cell(r):
        """Notional, and how it got there — sized down by the gate, or still filling."""
        bits = [f'{r["notional_usdt"]:.2f}']
        if not r["fill_complete"]:
            bits.append(f'slice {r["slices_done"]}/{r["slices_planned"]}')
        if r["sized_down"]:
            bits.append(f'cut from {r["target_notional_usdt"]:.0f}')
        if r["participation_pct"] is not None:
            bits.append(f'{r["participation_pct"]:.2f}% of the hour')
        head = bits[0]
        tail = " &middot; ".join(bits[1:])
        return (f'<td class="m dim">{head}'
                + (f'<div class="dim small">{tail}</div>' if tail else "")
                + "</td>")

    open_rows = "".join(
        f'<tr><td><span class="tag">{r["arm"]}</span></td>'
        f'<td class="sym">{html.escape(r["base"])}</td>'
        f'<td class="m">{r["entry_vwap"]:.8g}</td>'
        f'<td class="m dim">{r["tp_price"]:.8g}</td>'
        f'<td class="m dim">{r["sl_price"]:.8g}</td>'
        f'<td class="m">{(store.now_ms()-r["opened_ms"])/3_600_000:.1f}h</td>'
        f'<td class="m {"neg" if (r["mae_pct"] or 0) > 7 else "dim"}">'
        f'+{r["mae_pct"] or 0:.1f}%</td>'
        f'<td class="m dim">+{r["mfe_pct"] or 0:.1f}%</td>'
        + notional_cell(r) + "</tr>"
        for r in d["open"]) or '<tr><td colspan="9" class="dim">no open positions</td></tr>'

    def gap(r):
        return "-" if r["gap_hours"] is None else f'{r["gap_hours"]:+.0f}h'

    closed_rows = "".join(
        f'<tr><td><span class="tag">{r["arm"]}</span></td>'
        f'<td class="m">{_fmt_ts(r["opened_ms"])}</td>'
        f'<td class="sym">{html.escape(r["base"])}</td>'
        f'<td class="m dim">{gap(r)}</td>'
        f'<td class="m dim">{r["entry_slippage_bps"]:.1f}b</td>'
        f'<td class="m dim">{r["exit_slippage_bps"]:.1f}b</td>'
        f'<td class="m dim">{(r["funding_frac"] or 0)*100:+.3f}%</td>'
        f'<td class="m dim">{r["gross_pct"]:+.2f}%</td>'
        f'<td class="m {"pos" if r["net_pct"] > 0 else "neg"}">{r["net_pct"]:+.2f}%</td>'
        f'<td class="m {"pos" if (r["pnl_usdt"] or 0) > 0 else "neg"}">'
        f'{r["pnl_usdt"] or 0:+.2f}</td>'
        f'<td class="m dim">{html.escape(r["exit_reason"] or "")}</td></tr>'
        for r in reversed(d["closed"])) or \
        '<tr><td colspan="11" class="dim">no closed positions yet</td></tr>'

    def plan_cell(eid, arm):
        p = d["plans"].get(eid, {}).get(arm)
        if p is None:
            return '<td class="dim small">&mdash;</td>'
        st = p["status"]
        state = "ok" if st == "traded" else ("mid" if st == "watching" else "no")
        why = html.escape((p["ineligible_reason"] or "")[:70])
        detail = f'<div class="dim small">{why}</div>' if why else ""
        return "<td>" + _chip(state, st) + detail + "</td>"

    def event_row(r):
        cells = "".join(plan_cell(r["id"], a) for a in C.ARM_IDS)
        return (f'<tr><td class="m">{_fmt_ts(r["detected_ms"])}</td>'
                f'<td class="sym">{html.escape(r["base"])}</td>'
                f'<td class="m dim">{gap(r)}</td>{cells}</tr>')

    ev_rows = "".join(event_row(r) for r in d["events"]) or \
        f'<tr><td colspan="{3+len(C.ARM_IDS)}" class="dim">no listings detected yet</td></tr>'

    # ---- costs and execution, pooled across arms ---------------------------
    pool = _stats(d["closed"])
    parts = [r["participation_pct"] for r in d["closed"] + d["open"]
             if r["participation_pct"] is not None]
    depths = [r["entry_book_depth_usdt"] for r in d["closed"] + d["open"]
              if r["entry_book_depth_usdt"]]
    med_part = sorted(parts)[len(parts) // 2] if parts else None
    med_depth = sorted(depths)[len(depths) // 2] if depths else None

    lr = d["last_run"]
    stale_min = (store.now_ms() - lr["ts_ms"]) / 60000 if lr else 9999
    health = "ok" if stale_min < 15 else "no"
    errs = ""
    if lr and lr["errors"]:
        try:
            errs = " · ".join(json.loads(lr["errors"]))[:200]
        except Exception:                                       # noqa: BLE001
            errs = str(lr["errors"])[:200]

    arm_headers = "".join(f"<th>{a}</th>" for a in C.ARM_IDS)

    # the solved size table, measured on the clean historical sample
    SIZE_CAGR = {10: 26.9, 15: 45.5, 20: 58.9, 25: 85.3, 30: 111.2}
    size_rows = "".join(
        f'<tr{" class=\"hi\"" if dd == C.COMBINED_DD_TARGET_PCT else ""}>'
        f'<td class="m">{dd}%</td><td class="m">{sz*100:.0f}%</td>'
        f'<td class="m pos">+{SIZE_CAGR[dd]:.1f}%</td>'
        f'<td class="m dim">{sz*100:.0f}%</td></tr>'
        for dd, sz in sorted(C.COMBINED_SIZE_TABLE.items()))

    # per-venue anchor diagnostics, so a midnight-anchor regression is visible
    by_venue = {}
    for r in d["events"]:
        v = r["signal_venue"] if "signal_venue" in r.keys() else "binance"
        b = by_venue.setdefault(v, {"n": 0, "anchored": 0, "hours": []})
        b["n"] += 1
        if r["listed_ms"]:
            b["anchored"] += 1
            b["hours"].append(time.gmtime(r["listed_ms"] / 1000).tm_hour)
    def _anchor_row(v):
        b = by_venue.get(v)
        if not b:
            return (f'<tr><td class="sym">{v}</td><td class="m dim">0</td>'
                    f'<td class="m dim">0</td><td class="m dim">&mdash;</td></tr>')
        hh = sorted(b["hours"])
        med = f"{hh[len(hh)//2]:02d}:00" if hh else "&mdash;"
        return (f'<tr><td class="sym">{v}</td><td class="m">{b["n"]}</td>'
                f'<td class="m">{b["anchored"]}</td><td class="m">{med}</td></tr>')
    anchor_rows = "".join(_anchor_row(v) for v in C.SIGNAL_VENUES)

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Paper Trade Monitor — Listing Short</title>
<style>
:root {{ --ink:#0f141a; --paper:#f6f7f9; --panel:#fff; --line:#dfe4ea; --muted:#69737f;
  --accent:#2e6f96; --accent-soft:#e6eef4; --good:#2c7a56; --bad:#a63a37; --warn:#8a6a1f;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
@media (prefers-color-scheme:dark) {{ :root {{ --ink:#e7ecf1; --paper:#0d1218;
  --panel:#151c24; --line:#26303b; --muted:#8b97a5; --accent:#6aaed4;
  --accent-soft:#1a2a36; --good:#5fbf92; --bad:#e08079; --warn:#d0aa5c; }} }}
:root[data-theme="dark"] {{ --ink:#e7ecf1; --paper:#0d1218; --panel:#151c24;
  --line:#26303b; --muted:#8b97a5; --accent:#6aaed4; --accent-soft:#1a2a36;
  --good:#5fbf92; --bad:#e08079; --warn:#d0aa5c; }}
:root[data-theme="light"] {{ --ink:#0f141a; --paper:#f6f7f9; --panel:#fff;
  --line:#dfe4ea; --muted:#69737f; --accent:#2e6f96; --accent-soft:#e6eef4;
  --good:#2c7a56; --bad:#a63a37; --warn:#8a6a1f; }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1140px;margin:0 auto;padding:36px 22px 64px}}
.m{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.small{{font-size:0.78rem}} .dim{{color:var(--muted)}}
.pos{{color:var(--good)}} .neg{{color:var(--bad)}}
h1{{font-size:clamp(1.5rem,3vw,2rem);margin:0 0 6px;letter-spacing:-0.02em;
  font-weight:700;text-wrap:balance}}
h2{{font-size:0.76rem;letter-spacing:0.13em;text-transform:uppercase;color:var(--muted);
  font-family:var(--mono);font-weight:600;margin:0 0 12px;padding-bottom:8px;
  border-bottom:1px solid var(--line)}}
.eyebrow{{font-family:var(--mono);font-size:0.72rem;letter-spacing:0.15em;
  text-transform:uppercase;color:var(--accent);margin-bottom:9px}}
.lede{{color:var(--muted);max-width:72ch;margin:0 0 26px}}
section{{margin-bottom:34px}}
.tag{{font-family:var(--mono);font-size:0.68rem;font-weight:600;letter-spacing:0.06em;
  padding:2px 6px;border-radius:2px;background:var(--accent-soft);color:var(--accent)}}
.arms{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden}}
.arm{{background:var(--panel);padding:16px 18px}}
.arm-h{{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:10px}}
.arm-eq{{font-family:var(--mono);font-size:1.75rem;letter-spacing:-0.02em;
  font-variant-numeric:tabular-nums;margin-bottom:12px}}
.arm-eq span{{font-size:0.72rem;letter-spacing:0;margin-left:8px}}
.arm dl,.pair dl{{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;margin:0;
  font-family:var(--mono);font-size:0.82rem}}
.arm dt,.pair dt{{color:var(--muted)}}
.arm dd,.pair dd{{margin:0;font-variant-numeric:tabular-nums}}
.arm dd .dim{{font-size:0.72rem;margin-left:6px}}
.note{{margin-top:12px;font-size:0.82rem;border-left:3px solid var(--warn);
  padding:8px 12px;background:var(--paper);border-radius:2px}}
.note.ok{{border-left-color:var(--good)}} .note.no{{border-left-color:var(--bad)}}
.bar{{height:4px;background:var(--line);border-radius:3px;margin-top:10px;overflow:hidden}}
.bar span{{display:block;height:100%;background:var(--accent)}}
.pair{{display:grid;grid-template-columns:1.4fr 1fr;gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:3px;overflow:hidden}}
.pair > div{{background:var(--panel);padding:16px 18px}}
.pair .big{{font-family:var(--mono);font-size:2rem;letter-spacing:-0.02em;
  font-variant-numeric:tabular-nums}}
.pair dl{{margin-top:12px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden}}
.kpi{{background:var(--panel);padding:14px 16px}}
.kpi .k{{font-family:var(--mono);font-size:0.66rem;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--muted)}}
.kpi .v{{font-family:var(--mono);font-size:1.4rem;letter-spacing:-0.02em;margin-top:3px;
  font-variant-numeric:tabular-nums}}
.kpi .s{{font-family:var(--mono);font-size:0.7rem;color:var(--muted);margin-top:2px}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:3px;
  background:var(--panel)}}
.pair .tablewrap{{border:0;border-radius:0}}
table{{width:100%;border-collapse:collapse;font-size:0.82rem}}
th{{text-align:left;font-family:var(--mono);font-size:0.66rem;letter-spacing:0.08em;
  text-transform:uppercase;color:var(--muted);font-weight:600;padding:9px 11px;
  border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:7px 11px;border-bottom:1px solid var(--line);white-space:nowrap;
  vertical-align:top}}
tr:last-child td{{border-bottom:0}}
td.sym{{font-family:var(--mono);font-weight:600}}
.chip{{font-family:var(--mono);font-size:0.64rem;letter-spacing:0.06em;
  text-transform:uppercase;padding:2px 6px;border-radius:2px;border:1px solid currentColor}}
.chip.ok{{color:var(--good)}} .chip.no{{color:var(--bad)}} .chip.mid{{color:var(--warn)}}
.refutab {{ width:100%; border-collapse:collapse; font-family:var(--mono);
  font-size:0.76rem; margin:8px 0 12px; font-variant-numeric:tabular-nums; }}
.refutab th {{ text-align:left; font-size:0.62rem; letter-spacing:0.08em;
  text-transform:uppercase; color:var(--muted); padding:5px 9px 5px 0;
  border-bottom:1px solid var(--line); font-weight:600; }}
.refutab td {{ padding:4px 9px 4px 0; border-bottom:1px solid var(--line);
  white-space:nowrap; }}
.refutab tr:last-child td {{ border-bottom:0; }}
.refutab tr.hi td {{ background:var(--accent-soft); font-weight:600; }}
.rule{{background:var(--panel);border:1px solid var(--line);border-radius:3px;
  padding:15px 18px;font-family:var(--mono);font-size:0.82rem}}
.rule dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 18px;margin:0}}
.rule dt{{color:var(--muted)}} .rule dd{{margin:0}}
footer{{border-top:1px solid var(--line);padding-top:14px;font-family:var(--mono);
  font-size:0.7rem;color:var(--muted);display:flex;gap:16px;flex-wrap:wrap}}
a{{color:var(--accent)}}
@media (max-width:700px){{.pair{{grid-template-columns:1fr}}}}
</style>
</head><body>

<div class="wrap">
  <div class="eyebrow">Paper trade monitor &middot; updated {_fmt_ts(store.now_ms())} UTC</div>
  <h1>Listing-short forward test &mdash; {len(C.ARM_IDS)} arms, {len(C.SIGNAL_VENUES)} venues</h1>
  <p class="lede">Five pre-registered out-of-sample replications put this effect on
  large-audience venues and not on small ones, at +3.46% per trade across 111 clean events
  &mdash; <strong>sitting on its significance bar, not past it</strong>. Each arm listens to
  one venue and trades the same Gate USDT perpetual, so the venue supplies only the listing
  timestamp. Every arm was <a href="{PREREG_URL}">declared in advance</a> and none may be
  dropped. Fills walk the real order book; fees and funding are the venue's own. No real
  orders are placed and no API key exists.
  <a href="{RESEARCH_URL}">Research findings &rarr;</a></p>

  <section>
    <h2>The combined book &mdash; all venues, one account, one trade per token</h2>
    <div class="kpis">
      <div class="kpi"><div class="k">Equity</div>
        <div class="v {"pos" if d["cap"]["pnl_pct"] >= 0 else "neg"}">{d["cap"]["equity"]:,.2f}</div>
        <div class="s">{d["cap"]["pnl_pct"]:+.2f}% from {C.PAPER_START_EQUITY:,.0f}</div></div>
      <div class="kpi"><div class="k">Trades taken</div>
        <div class="v">{d["cap"]["taken"]}</div>
        <div class="s">{d["cap"]["skipped_cap"]} slot busy &middot;
          {d["cap"]["skipped_cool"]} duplicate token</div></div>
      <div class="kpi"><div class="k">Max drawdown</div>
        <div class="v neg">{d["cap"]["max_dd"]:.1f}%</div>
        <div class="s">target {C.COMBINED_DD_TARGET_PCT}% at p90</div></div>
      <div class="kpi"><div class="k">Size per trade</div>
        <div class="v">{d["cap"]["size"]*100:.0f}%</div>
        <div class="s">solved from the drawdown target</div></div>
      <div class="kpi"><div class="k">Peak exposure</div>
        <div class="v">{d["cap"]["cap"]*d["cap"]["size"]*100:.0f}%</div>
        <div class="s">{d["cap"]["cap"]} position &times; {d["cap"]["size"]*100:.0f}%</div></div>
      <div class="kpi"><div class="k">Venues feeding it</div>
        <div class="v">{len(C.SIGNAL_VENUES)}</div>
        <div class="s">{", ".join(C.SIGNAL_VENUES)}</div></div>
    </div>
    <div class="split">
      <div><div class="k">Size is solved, not guessed</div>
        <div class="v" style="color:var(--accent)">{C.COMBINED_SIZE*100:.0f}%</div>
        <div class="s">for a {C.COMBINED_DD_TARGET_PCT}% p90 drawdown</div>
        <p>Size and drawdown are near-proportional here, so the dial has one setting and one
        consequence. Measured on the clean historical sample at +3.46% per trade:</p>
        <table class="refutab"><thead><tr><th>DD target</th><th>size</th><th>CAGR</th>
        <th>peak exposure</th></tr></thead><tbody>{size_rows}</tbody></table>
        <p class="dim small">At the parameter-free +1.18% per trade the same 20% drawdown
        buys only <strong>+12.8%</strong>. That gap is the cost of the entry hour not being
        identifiable across venues.</p></div>
      <div><div class="k">Why a cap of one</div>
        <div class="v" style="color:var(--accent)">{d["cap"]["cap"]}</div>
        <div class="s">position at a time</div>
        <p>At a matched drawdown a cap of 2 earns about the same and needs roughly twice the
        peak exposure &mdash; at a 20% target, +69.8% on 32% exposure against +58.9% on 17%.
        Simultaneous shorts on new listings move together, so a second open position is
        leverage rather than diversification, and leverage is cheaper to buy by making the
        one position larger.</p>
        <p><strong>Duplicates resolve to one trade.</strong> When several venues list the
        same token the first to list wins and the token is then on a
        {C.REPORT_COOLDOWN_DAYS}-day cooldown &mdash; the thesis is that the pump follows
        the listing, so the earliest listing is the event. On history that bound 4 of 226
        signals; the venues mostly list months apart.</p></div>
    </div>
    <p class="dim small">This book is computed from the arms' own record rather than
    collected separately, which is arithmetically the same thing because every arm already
    takes every eligible listing &mdash; and it leaves the per-arm measurement intact, which
    a fifth self-collecting arm would have destroyed. The cap and the cooldown live here and
    not in collection because Amendment 1 of the pre-registration established that a gate may
    size down and must never skip an event: skipping removes sample points and biases the
    test.</p>
  </section>

  <section>
    <h2>The arms behind it, measured separately and uncapped</h2>
    <div class="arms">{"".join(panels)}</div>
  </section>

  <section>
    <h2>Paired comparison &mdash; the question this design exists to answer</h2>
    {pair_body}
  </section>

  <section>
    <h2>Anchor diagnostics &mdash; where this project keeps failing</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Signal venue</th><th>Listings seen</th><th>With an anchor</th>
      <th>Median first traded hour, UTC</th></tr></thead>
      <tbody>{anchor_rows}</tbody></table></div>
    <p class="dim small">Three separate midnight-anchor bugs have been found in this
    project, the most recent inside the Upbit study where it manufactured a +5.91% result
    at t&nbsp;5.76 that had to be withdrawn. Coinbase lists at a median 17:00 UTC and Upbit
    at a median 7h past midnight, so a median clustered at 00:00 here would mean the bug
    has returned.</p>
  </section>

  <section>
    <h2>All arms summed, for reference</h2>
    <div class="kpis">
      <div class="kpi"><div class="k">Total equity</div>
        <div class="v {"pos" if total_eq >= total_start else "neg"}">{total_eq:,.2f}</div>
        <div class="s">{(total_eq/total_start-1)*100:+.2f}% from {total_start:,.0f}</div></div>
      <div class="kpi"><div class="k">Closed</div><div class="v">{pool["n"]}</div>
        <div class="s">both arms</div></div>
      <div class="kpi"><div class="k">Entry slip</div>
        <div class="v">{_num(pool.get("slip_in"), "{:.1f}b")}</div>
        <div class="s">vs mid, book-walked</div></div>
      <div class="kpi"><div class="k">Exit slip</div>
        <div class="v">{_num(pool.get("slip_out"), "{:.1f}b")}</div>
        <div class="s">vs mid</div></div>
      <div class="kpi"><div class="k">Funding</div>
        <div class="v">{_num(pool.get("funding"), "{:+.3f}%")}</div>
        <div class="s">+ = credit to short</div></div>
      <div class="kpi"><div class="k">Running</div><div class="v">{days:.1f}d</div>
        <div class="s">{d["runs_24h"]} ticks in 24h</div></div>
    </div>
  </section>

  <section>
    <h2>Execution discipline</h2>
    <div class="kpis">
      <div class="kpi"><div class="k">Participation cap</div>
        <div class="v">{C.MAX_PARTICIPATION_PCT:.0f}%</div>
        <div class="s">of the entry hour's traded volume</div></div>
      <div class="kpi"><div class="k">Sized down</div>
        <div class="v">{sum(1 for r in d["closed"] + d["open"] if r["sized_down"])}</div>
        <div class="s">positions cut to fit</div></div>
      <div class="kpi"><div class="k">Sliced</div>
        <div class="v">{sum(1 for r in d["closed"] + d["open"] if (r["slices_planned"] or 1) > 1)}</div>
        <div class="s">split across ticks</div></div>
      <div class="kpi"><div class="k">Median participation</div>
        <div class="v">{_num(med_part, "{:.2f}%")}</div>
        <div class="s">measured, per position</div></div>
      <div class="kpi"><div class="k">Median book depth</div>
        <div class="v">{_num(med_depth, "${:,.0f}")}</div>
        <div class="s">visible bid side at entry</div></div>
    </div>
    <p class="dim small">Liquidity on these contracts sits in the flow, not the book &mdash;
    a contract can trade millions an hour with a few hundred dollars resting on the bid. The
    gate therefore sizes against traded volume, and never skips an event: removing one would
    bias the sample, while cutting the notional leaves the percentage return untouched.</p>
  </section>

  <section>
    <h2>Open positions</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Arm</th><th>Token</th><th>Entry</th><th>TP</th><th>SL</th>
      <th>Age</th><th>Worst</th><th>Best</th><th>Notional</th></tr></thead>
      <tbody>{open_rows}</tbody></table></div>
  </section>

  <section>
    <h2>Closed positions</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Arm</th><th>Opened</th><th>Token</th><th>Perp gap</th>
      <th>In slip</th><th>Out slip</th><th>Funding</th><th>Gross</th><th>Net</th>
      <th>USDT</th><th>Exit</th></tr></thead>
      <tbody>{closed_rows}</tbody></table></div>
  </section>

  <section>
    <h2>Listings seen, and what each arm decided</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Detected</th><th>Token</th><th>Perp gap</th>{arm_headers}</tr></thead>
      <tbody>{ev_rows}</tbody></table></div>
    <p class="dim small">A perp arriving between the two entry hours is tradeable by the
    later arm only. That is a feasibility rule, not a filter to tune &mdash; and getting
    it wrong accounted for half the difference between the research page's first headline
    and its current one.</p>
  </section>

  <section>
    <h2>Frozen, shared by every arm</h2>
    <div class="rule"><dl>
      <dt>signal</dt><dd>a new pair starts trading on that arm's venue</dd>
      <dt>anchor</dt><dd>that venue's own first traded hour, never midnight</dd>
      <dt>execution</dt><dd>Gate USDT perpetual, every arm</dd>
      <dt>filter</dt><dd>a Gate perpetual must exist by that arm's entry hour</dd>
      <dt>direction</dt><dd>short, never long</dd>
      <dt>take profit</dt><dd>{C.TAKE_PROFIT*100:.0f}%</dd>
      <dt>stop loss</dt><dd>{C.STOP_LOSS*100:.0f}%</dd>
      <dt>max hold</dt><dd>{C.MAX_HOLD_HOURS}h</dd>
      <dt>size</dt><dd>{C.POSITION_PCT*100:.0f}% &mdash; solved from a {C.COMBINED_DD_TARGET_PCT}% p90 drawdown target, not chosen</dd>
      <dt>stop signal</dt><dd>win rate &le;{STOP_SIGNAL_WINRATE:.0f}% after
        {STOP_SIGNAL_TRADES} closed trades, per arm</dd>
      <dt>bar</dt><dd>t {BAR:.2f} = 2.0 + 0.35&thinsp;&times;&thinsp;ln(2), for two
        pre-declared configurations</dd>
    </dl></div>
  </section>

  <footer>
    <span>health {_chip(health, "ok" if health == "ok" else "stale")}
      last tick {stale_min:.0f} min ago</span>
    <span>paper only &mdash; no orders, no keys</span>
    {f'<span class="neg">errors: {html.escape(errs)}</span>' if errs else ''}
  </footer>
</div>
</body></html>
"""


def write(cx, path=None):
    path = path or os.path.join(C.DATA_DIR, "monitor.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(gather(cx)))
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    print(write(store.connect()))
