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

BAR = 2.2426              # 2.0 + 0.35*ln(2), for the two pre-declared configurations
STOP_SIGNAL_TRADES = 15
STOP_SIGNAL_WINRATE = 40.0
RESEARCH_URL = "https://amindraa05.github.io/listing-short-bot/"
PREREG_URL = ("https://github.com/amindraa05/listing-short-bot/blob/main/"
              "PREREG_ARMS.md")


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

    # The paired test: same listing, both arms, both closed. This is the comparison the
    # two-arm design exists for — it removes the between-listing variance that left the
    # backtest's own comparison at t 1.50.
    by_arm = {a: {r["base"]: r for r in arms[a]["closed"]} for a in C.ARM_IDS}
    a1, a2 = C.ARM_IDS[0], C.ARM_IDS[1] if len(C.ARM_IDS) > 1 else C.ARM_IDS[0]
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

    last_run = cx.execute("SELECT * FROM runs ORDER BY ts_ms DESC LIMIT 1").fetchone()
    return {"arms": arms, "paired": paired, "closed": closed, "open": openp,
            "events": events, "plans": plans, "last_run": last_run,
            "started_ms": int(started["value"]) if started else store.now_ms(),
            "runs_24h": cx.execute("SELECT COUNT(*) n FROM runs WHERE ts_ms>?",
                                   (store.now_ms() - 86400_000,)).fetchone()["n"]}


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
        f'<td class="m dim">{r["notional_usdt"]:.2f}</td></tr>'
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

    # ---- costs, pooled across arms ----------------------------------------
    pool = _stats(d["closed"])

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
  <h1>Listing-short forward test &mdash; two arms</h1>
  <p class="lede">Live paper trading of a rule whose backtest <strong>did not</strong>
  settle its own central question: whether the entry belongs at T+12h or T+18h. Both arms
  were <a href="{PREREG_URL}">declared in advance</a> and neither may be dropped. Fills
  walk the real Gate order book; fees and funding are the venue's own. No real orders are
  placed and no API key exists.
  <a href="{RESEARCH_URL}">Research findings &rarr;</a></p>

  <section>
    <h2>The two arms, each on its own book</h2>
    <div class="arms">{"".join(panels)}</div>
  </section>

  <section>
    <h2>Paired comparison &mdash; the question this design exists to answer</h2>
    {pair_body}
  </section>

  <section>
    <h2>Combined paper account</h2>
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
    <h2>Frozen, shared by both arms</h2>
    <div class="rule"><dl>
      <dt>signal</dt><dd>new USDT pair starts trading on Binance spot</dd>
      <dt>filter</dt><dd>a Gate perpetual must exist by that arm's entry hour</dd>
      <dt>direction</dt><dd>short, never long</dd>
      <dt>take profit</dt><dd>{C.TAKE_PROFIT*100:.0f}%</dd>
      <dt>stop loss</dt><dd>{C.STOP_LOSS*100:.0f}%</dd>
      <dt>max hold</dt><dd>{C.MAX_HOLD_HOURS}h</dd>
      <dt>size</dt><dd>{C.POSITION_PCT*100:.0f}% of that arm's own equity, 1&times;</dd>
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
