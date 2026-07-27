"""Generate the paper-trade monitor as a single self-contained HTML file.

Written after every tick so the page is never stale. No web server, no port, no nginx —
the file is published by committing it, which is why this bot still binds nothing on a
host that also runs live trading.

The page is built to make the honest reading unavoidable: the backtest expectation sits
next to the live result, the pre-agreed stop signal is evaluated rather than described,
and the trade count needed before any of it means anything is shown as a progress bar.
"""
import html
import json
import os
import sqlite3
import time

from . import config as C
from . import store

BACKTEST = {"n": 115, "mean": 2.71, "median": 14.77, "win": 62.6, "t": 1.99,
            "sd": 14.6, "bar": 3.55, "years": 1.89}
STOP_SIGNAL_TRADES = 15
STOP_SIGNAL_WINRATE = 40.0
RESEARCH_URL = "https://amindraa05.github.io/listing-short-bot/"


def _fmt_ts(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else "-"


def gather(cx):
    eq = store.get_equity(cx)
    started = cx.execute("SELECT value FROM meta WHERE key='started_ms'").fetchone()
    started_ms = int(started["value"]) if started else store.now_ms()
    closed = cx.execute(
        "SELECT p.*, e.gap_hours FROM positions p LEFT JOIN events e ON e.id=p.event_id "
        "WHERE p.status='closed' ORDER BY p.opened_ms").fetchall()
    openp = cx.execute(
        "SELECT p.*, e.gap_hours FROM positions p LEFT JOIN events e ON e.id=p.event_id "
        "WHERE p.status='open' ORDER BY p.opened_ms").fetchall()
    events = cx.execute(
        "SELECT * FROM events ORDER BY detected_ms DESC LIMIT 40").fetchall()
    last_run = cx.execute("SELECT * FROM runs ORDER BY ts_ms DESC LIMIT 1").fetchone()
    runs_24h = cx.execute("SELECT COUNT(*) n FROM runs WHERE ts_ms > ?",
                          (store.now_ms() - 86400_000,)).fetchone()["n"]

    nets = [r["net_pct"] for r in closed if r["net_pct"] is not None]
    stats = {"n": len(nets)}
    if nets:
        mean = sum(nets) / len(nets)
        wins = sum(1 for x in nets if x > 0)
        stats.update({
            "mean": mean, "win": wins / len(nets) * 100,
            "median": sorted(nets)[len(nets) // 2],
            "best": max(nets), "worst": min(nets),
            "sum_usdt": sum(r["pnl_usdt"] or 0 for r in closed),
        })
        if len(nets) > 2:
            sd = (sum((x - mean) ** 2 for x in nets) / (len(nets) - 1)) ** 0.5
            stats["sd"] = sd
            stats["t"] = mean / (sd / len(nets) ** 0.5) if sd > 0 else 0.0
        slips = [r["entry_slippage_bps"] for r in closed
                 if r["entry_slippage_bps"] is not None]
        if slips:
            stats["mean_entry_slip"] = sum(slips) / len(slips)
        xs = [r["exit_slippage_bps"] for r in closed
              if r["exit_slippage_bps"] is not None]
        if xs:
            stats["mean_exit_slip"] = sum(xs) / len(xs)
        fnd = [r["funding_frac"] or 0 for r in closed]
        if fnd:
            stats["mean_funding"] = sum(fnd) / len(fnd) * 100
    return {"equity": eq, "started_ms": started_ms, "closed": closed, "open": openp,
            "events": events, "last_run": last_run, "runs_24h": runs_24h,
            "stats": stats}


def _chip(state, text):
    return f'<span class="chip {state}">{html.escape(text)}</span>'


def render(d):
    s = d["stats"]
    eq = d["equity"]
    days = (store.now_ms() - d["started_ms"]) / 86400_000
    pnl_pct = (eq / C.PAPER_START_EQUITY - 1) * 100
    n = s["n"]

    # the pre-agreed stop rule, evaluated rather than described
    if n < STOP_SIGNAL_TRADES:
        verdict_state, verdict = "mid", (
            f"{STOP_SIGNAL_TRADES - n} more closed trades before the stop check is even "
            f"meaningful. Nothing here should change your mind yet.")
    elif s.get("win", 100) <= STOP_SIGNAL_WINRATE:
        verdict_state, verdict = "no", (
            f"STOP SIGNAL REACHED — win rate {s['win']:.1f}% at or below "
            f"{STOP_SIGNAL_WINRATE:.0f}% after {n} trades. This was agreed in advance as "
            f"the point to stop.")
    else:
        verdict_state, verdict = "ok", (
            f"Win rate {s['win']:.1f}% over {n} trades is above the {STOP_SIGNAL_WINRATE:.0f}% "
            f"stop line. Not a confirmation — confirming the honest effect size needs "
            f"about 117 trades.")

    prog = min(100, n / STOP_SIGNAL_TRADES * 100)

    def gap(r):
        return "-" if r["gap_hours"] is None else f'{r["gap_hours"]:+.0f}h'

    open_rows = "".join(
        f'<tr><td class="sym">{html.escape(r["base"])}</td>'
        f'<td class="m">{r["entry_vwap"]:.8g}</td>'
        f'<td class="m dim">{r["tp_price"]:.8g}</td>'
        f'<td class="m dim">{r["sl_price"]:.8g}</td>'
        f'<td class="m">{(store.now_ms()-r["opened_ms"])/3_600_000:.1f}h</td>'
        f'<td class="m {"neg" if (r["mae_pct"] or 0) > 7 else "dim"}">'
        f'+{r["mae_pct"] or 0:.1f}%</td>'
        f'<td class="m dim">+{r["mfe_pct"] or 0:.1f}%</td>'
        f'<td class="m dim">{r["notional_usdt"]:.2f}</td></tr>'
        for r in d["open"]) or '<tr><td colspan="8" class="dim">no open positions</td></tr>'

    closed_rows = "".join(
        f'<tr><td class="m">{_fmt_ts(r["opened_ms"])}</td>'
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
        '<tr><td colspan="10" class="dim">no closed positions yet</td></tr>'

    ev_rows = "".join(
        f'<tr><td class="m">{_fmt_ts(r["detected_ms"])}</td>'
        f'<td class="sym">{html.escape(r["base"])}</td>'
        f'<td class="m dim">{gap(r)}</td>'
        f'<td>{_chip("ok" if r["status"]=="traded" else ("mid" if r["status"] in ("watching","pending_perp") else "no"), r["status"])}</td>'
        f'<td class="dim small">{html.escape((r["ineligible_reason"] or "")[:96])}</td></tr>'
        for r in d["events"]) or '<tr><td colspan="5" class="dim">no listings detected yet</td></tr>'

    lr = d["last_run"]
    stale_min = (store.now_ms() - lr["ts_ms"]) / 60000 if lr else 9999
    health = ("ok" if stale_min < 15 else "no")
    errs = ""
    if lr and lr["errors"]:
        try:
            errs = " · ".join(json.loads(lr["errors"]))[:200]
        except Exception:  # noqa: BLE001
            errs = str(lr["errors"])[:200]

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
.wrap{{max-width:1100px;margin:0 auto;padding:36px 22px 64px}}
.m{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.small{{font-size:0.8rem}}
h1{{font-size:clamp(1.5rem,3vw,2rem);margin:0 0 6px;letter-spacing:-0.02em;
  font-weight:700;text-wrap:balance}}
h2{{font-size:0.76rem;letter-spacing:0.13em;text-transform:uppercase;color:var(--muted);
  font-family:var(--mono);font-weight:600;margin:0 0 12px;padding-bottom:8px;
  border-bottom:1px solid var(--line)}}
.eyebrow{{font-family:var(--mono);font-size:0.72rem;letter-spacing:0.15em;
  text-transform:uppercase;color:var(--accent);margin-bottom:9px}}
.lede{{color:var(--muted);max-width:70ch;margin:0 0 26px}}
section{{margin-bottom:34px}}
.banner{{border:1px solid var(--line);border-left:3px solid var(--warn);
  background:var(--panel);padding:16px 20px;border-radius:3px;margin-bottom:26px}}
.banner.ok{{border-left-color:var(--good)}} .banner.no{{border-left-color:var(--bad)}}
.banner p{{margin:0;max-width:74ch}}
.bar{{height:5px;background:var(--line);border-radius:3px;margin-top:12px;overflow:hidden}}
.bar span{{display:block;height:100%;background:var(--accent)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(144px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden}}
.kpi{{background:var(--panel);padding:14px 16px}}
.kpi .k{{font-family:var(--mono);font-size:0.66rem;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--muted)}}
.kpi .v{{font-family:var(--mono);font-size:1.45rem;letter-spacing:-0.02em;margin-top:3px;
  font-variant-numeric:tabular-nums}}
.kpi .s{{font-family:var(--mono);font-size:0.7rem;color:var(--muted);margin-top:2px}}
.v.pos{{color:var(--good)}} .v.neg{{color:var(--bad)}}
.cmp{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:3px;overflow:hidden}}
.cmp>div{{background:var(--panel);padding:15px 17px}}
.cmp>div.live{{background:var(--accent-soft)}}
.cmp h3{{font-family:var(--mono);font-size:0.68rem;letter-spacing:0.1em;
  text-transform:uppercase;margin:0 0 8px;color:var(--muted);font-weight:600}}
.cmp dl{{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;margin:0;
  font-family:var(--mono);font-size:0.82rem}}
.cmp dt{{color:var(--muted)}} .cmp dd{{margin:0;font-variant-numeric:tabular-nums}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:3px;
  background:var(--panel)}}
table{{width:100%;border-collapse:collapse;font-size:0.82rem}}
th{{text-align:left;font-family:var(--mono);font-size:0.66rem;letter-spacing:0.08em;
  text-transform:uppercase;color:var(--muted);font-weight:600;padding:9px 11px;
  border-bottom:1px solid var(--line)}}
td{{padding:7px 11px;border-bottom:1px solid var(--line);white-space:nowrap}}
tr:last-child td{{border-bottom:0}}
td.sym{{font-family:var(--mono);font-weight:600}}
td.dim{{color:var(--muted)}} td.pos{{color:var(--good)}} td.neg{{color:var(--bad)}}
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
@media (max-width:620px){{.cmp{{grid-template-columns:1fr}}}}
</style>
</head><body>

<div class="wrap">
  <div class="eyebrow">Paper trade monitor &middot; updated {_fmt_ts(store.now_ms())} UTC</div>
  <h1>Listing-short forward test</h1>
  <p class="lede">Live paper trading of a rule whose backtest <strong>did not</strong> clear
  its own significance bar. Fills walk the real Gate order book, fees and funding are the
  venue's own. No real orders are placed and no API key exists.
  <a href="{RESEARCH_URL}">Research findings &rarr;</a></p>

  <div class="banner {verdict_state}">
    <p>{html.escape(verdict)}</p>
    <div class="bar"><span style="width:{prog:.0f}%"></span></div>
  </div>

  <section>
    <h2>Paper account</h2>
    <div class="kpis">
      <div class="kpi"><div class="k">Equity</div>
        <div class="v {"pos" if pnl_pct >= 0 else "neg"}">{eq:,.2f}</div>
        <div class="s">{pnl_pct:+.2f}% from {C.PAPER_START_EQUITY:,.0f}</div></div>
      <div class="kpi"><div class="k">Closed</div><div class="v">{n}</div>
        <div class="s">of {STOP_SIGNAL_TRADES} for the first check</div></div>
      <div class="kpi"><div class="k">Open</div><div class="v">{len(d["open"])}</div>
        <div class="s">max hold {C.MAX_HOLD_HOURS}h</div></div>
      <div class="kpi"><div class="k">Win rate</div>
        <div class="v">{f'{s["win"]:.1f}%' if n else '—'}</div>
        <div class="s">backtest {BACKTEST["win"]}%</div></div>
      <div class="kpi"><div class="k">Mean / trade</div>
        <div class="v">{f'{s["mean"]:+.2f}%' if n else '—'}</div>
        <div class="s">backtest {BACKTEST["mean"]:+.2f}%</div></div>
      <div class="kpi"><div class="k">Running</div><div class="v">{days:.1f}d</div>
        <div class="s">{d["runs_24h"]} ticks in 24h</div></div>
    </div>
  </section>

  <section>
    <h2>Live against the backtest expectation</h2>
    <div class="cmp">
      <div><h3>Backtest, untuned configuration</h3><dl>
        <dt>events</dt><dd>{BACKTEST["n"]} over {BACKTEST["years"]} years</dd>
        <dt>mean</dt><dd>{BACKTEST["mean"]:+.2f}%</dd>
        <dt>median</dt><dd>{BACKTEST["median"]:+.2f}%</dd>
        <dt>win rate</dt><dd>{BACKTEST["win"]}%</dd>
        <dt>sd</dt><dd>{BACKTEST["sd"]}%</dd>
        <dt>t</dt><dd>{BACKTEST["t"]} &nbsp;vs bar {BACKTEST["bar"]} &mdash; failed</dd>
      </dl></div>
      <div class="live"><h3>Live paper result</h3><dl>
        <dt>events</dt><dd>{n}</dd>
        <dt>mean</dt><dd>{f'{s["mean"]:+.2f}%' if n else '—'}</dd>
        <dt>median</dt><dd>{f'{s["median"]:+.2f}%' if n else '—'}</dd>
        <dt>win rate</dt><dd>{f'{s["win"]:.1f}%' if n else '—'}</dd>
        <dt>sd</dt><dd>{f'{s["sd"]:.1f}%' if s.get("sd") else '—'}</dd>
        <dt>t</dt><dd>{f'{s["t"]:+.2f}' if s.get("t") is not None else '—'}</dd>
      </dl></div>
    </div>
  </section>

  <section>
    <h2>Measured costs &mdash; the thing the backtest could only assume</h2>
    <div class="kpis">
      <div class="kpi"><div class="k">Entry slippage</div>
        <div class="v">{f'{s["mean_entry_slip"]:.1f}b' if s.get("mean_entry_slip") is not None else '—'}</div>
        <div class="s">vs mid, book-walked</div></div>
      <div class="kpi"><div class="k">Exit slippage</div>
        <div class="v">{f'{s["mean_exit_slip"]:.1f}b' if s.get("mean_exit_slip") is not None else '—'}</div>
        <div class="s">vs mid</div></div>
      <div class="kpi"><div class="k">Funding</div>
        <div class="v">{f'{s["mean_funding"]:+.3f}%' if s.get("mean_funding") is not None else '—'}</div>
        <div class="s">per trade, + = credit to short</div></div>
      <div class="kpi"><div class="k">Taker fee</div>
        <div class="v">{C.GATE_TAKER_FEE*100:.2f}%</div>
        <div class="s">per side, both legs</div></div>
      <div class="kpi"><div class="k">Total P&amp;L</div>
        <div class="v {"pos" if s.get("sum_usdt", 0) >= 0 else "neg"}">
          {f'{s["sum_usdt"]:+.2f}' if n else '—'}</div>
        <div class="s">USDT, paper</div></div>
    </div>
  </section>

  <section>
    <h2>Open positions</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Token</th><th>Entry</th><th>TP</th><th>SL</th><th>Age</th>
      <th>Worst</th><th>Best</th><th>Notional</th></tr></thead>
      <tbody>{open_rows}</tbody></table></div>
  </section>

  <section>
    <h2>Closed positions</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Opened</th><th>Token</th><th>Perp gap</th><th>In slip</th>
      <th>Out slip</th><th>Funding</th><th>Gross</th><th>Net</th><th>USDT</th>
      <th>Exit</th></tr></thead>
      <tbody>{closed_rows}</tbody></table></div>
  </section>

  <section>
    <h2>Listings seen, and why most are skipped</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>Detected</th><th>Token</th><th>Perp gap</th><th>Status</th>
      <th>Reason</th></tr></thead>
      <tbody>{ev_rows}</tbody></table></div>
  </section>

  <section>
    <h2>The frozen rule</h2>
    <div class="rule"><dl>
      <dt>signal</dt><dd>new USDT pair starts trading on Binance spot</dd>
      <dt>filter</dt><dd>a perpetual must exist by the entry hour (Gate / OKX / KuCoin)</dd>
      <dt>direction</dt><dd>short, never long</dd>
      <dt>entry</dt><dd>T+{C.ENTRY_HOURS}h from the first traded hour</dd>
      <dt>take profit</dt><dd>{C.TAKE_PROFIT*100:.0f}%</dd>
      <dt>stop loss</dt><dd>{C.STOP_LOSS*100:.0f}%</dd>
      <dt>max hold</dt><dd>{C.MAX_HOLD_HOURS}h</dd>
      <dt>size</dt><dd>{C.POSITION_PCT*100:.0f}% of paper equity, 1&times;</dd>
    </dl></div>
  </section>

  <footer>
    <span>health {_chip(health, "ok" if health == "ok" else "stale")}
      last tick {stale_min:.0f} min ago</span>
    <span>paper only &mdash; no orders, no keys</span>
    {f'<span style="color:var(--bad)">errors: {html.escape(errs)}</span>' if errs else ''}
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
    cx = store.connect()
    print(write(cx))
