"""Command line: tick, status, ledger, export.

`tick` is what the systemd timer calls. Everything else is for a human reading results.
"""
import argparse
import csv
import json
import hashlib
import logging
import math
import os
import re
import sys
import time

from . import config as C
from . import engine, report, store

BAR = 2.4854          # 2.0 + 0.35*ln(4), for the four pre-declared arms


def _log(verbose=False):
    os.makedirs(C.DATA_DIR, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(message)s"
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format=fmt, datefmt="%Y-%m-%dT%H:%M:%SZ",
                        handlers=[logging.FileHandler(C.LOG_PATH),
                                  logging.StreamHandler(sys.stdout)])
    logging.Formatter.converter = time.gmtime


def cmd_tick(args):
    _log(args.verbose)
    cx = store.connect()
    r = engine.tick(cx)
    logging.getLogger("listingbot").info(
        "tick done: %d new, %d opened, %d closed, equity %.2f%s",
        r["new_events"], r["opened"], r["closed"], store.get_equity(cx),
        f", {len(r['errors'])} errors" if r["errors"] else "")
    return 1 if r["errors"] else 0


def _arm_stats(rows):
    nets = [r["net_pct"] for r in rows if r["net_pct"] is not None]
    if not nets:
        return None
    mean = sum(nets) / len(nets)
    st = {"n": len(nets), "mean": mean,
          "win": sum(1 for x in nets if x > 0) / len(nets) * 100,
          "pnl": sum(r["pnl_usdt"] or 0 for r in rows)}
    if len(nets) > 2:
        sd = (sum((x - mean) ** 2 for x in nets) / (len(nets) - 1)) ** 0.5
        st["sd"] = sd
        st["t"] = mean / (sd / math.sqrt(len(nets))) if sd else 0.0
    return st


def cmd_status(args):
    cx = store.connect()
    started = cx.execute("SELECT value FROM meta WHERE key='started_ms'").fetchone()
    days = ((store.now_ms() - int(started["value"])) / 86400_000) if started else 0
    closed = cx.execute("SELECT * FROM positions WHERE status='closed'").fetchall()
    openp = store.open_positions(cx)

    print("=" * 90)
    print(f"  LISTING-SHORT PAPER TEST — {len(C.ARM_IDS)} arms on "
          f"{len(C.SIGNAL_VENUES)} venues, separate books")
    print("=" * 90)
    print(f"  running for   {days:.1f} days")
    print(f"  shared        TP {C.TAKE_PROFIT*100:.0f}%  SL {C.STOP_LOSS*100:.0f}%  "
          f"hold {C.MAX_HOLD_HOURS}h  size {C.POSITION_PCT*100:.0f}% of the arm's book")
    print(f"  bar           t {BAR:.2f}  (2.0 + 0.35*ln({len(C.ARM_IDS)}), "
          f"{len(C.ARM_IDS)} pre-declared arms)")
    print(f"  signal venues " + "  ".join(
        f"{v}:{','.join(C.arms_for(v))}" for v in C.SIGNAL_VENUES))
    print("  execution     Gate USDT perpetual on every arm; the venue supplies only the "
          "listing hour")

    for a in C.ARM_IDS:
        cfg = C.ARMS[a]
        bt = cfg["backtest"]
        rows = [r for r in closed if r["arm"] == a]
        eq = store.get_equity(cx, a)
        opn = [r for r in openp if r["arm"] == a]
        print()
        print(f"  [{a}] {cfg['label']} ({C.arm_venue(a)}) — {cfg['note']}")
        print(f"      book              {eq:,.2f} {C.CURRENCY} "
              f"({(eq/C.PAPER_START_EQUITY-1)*100:+.2f}% from "
              f"{C.PAPER_START_EQUITY:,.0f})")
        print(f"      positions         {len(rows)} closed, {len(opn)} open")
        st = _arm_stats(rows)
        if st:
            print(f"      mean / win        {st['mean']:+.2f}%  {st['win']:.1f}%"
                  f"      backtest {bt['mean']:+.2f}%  {bt['win']}%")
            if "t" in st:
                print(f"      t                 {st['t']:+.2f}"
                      f"               backtest {bt['t']:+.2f}")
            if st["n"] < 15:
                print(f"      {15-st['n']} more closed trades before the stop check means "
                      f"anything")
            elif st["win"] <= 40:
                print("      WIN RATE AT OR BELOW 40% — pre-agreed stop signal for this arm")
        else:
            print(f"      no closed positions yet   "
                  f"(backtest {bt['mean']:+.2f}%, win {bt['win']}%, t {bt['t']:+.2f})")

    # The paired test is the reason both arms exist: same listing, both arms, so the
    # between-listing variance that left the backtest at t 1.50 cancels out.
    by = {a: {r["base"]: r for r in closed if r["arm"] == a} for a in C.ARM_IDS}
    if len(C.ARM_IDS) >= 2:
        lo, hi = C.ARM_IDS[0], C.ARM_IDS[1]
        shared = sorted(set(by[lo]) & set(by[hi]))
        d = [by[hi][b]["net_pct"] - by[lo][b]["net_pct"] for b in shared]
        print()
        print(f"  PAIRED  {hi} minus {lo}, on listings both arms closed")
        if len(d) < 3:
            print(f"      {len(d)} pair(s) so far — needs at least 3")
        else:
            mean = sum(d) / len(d)
            sd = (sum((x - mean) ** 2 for x in d) / (len(d) - 1)) ** 0.5
            se = sd / math.sqrt(len(d))
            t = mean / se if se else 0.0
            print(f"      n {len(d)}   mean {mean:+.2f} pp   t {t:+.2f}   "
                  f"95% CI {mean-1.96*se:+.2f} .. {mean+1.96*se:+.2f} pp")
            print(f"      {hi} better on {sum(1 for x in d if x > 0)}, "
                  f"worse on {sum(1 for x in d if x < 0)}")
            print(f"      backtest said +1.82 pp at t 1.50 — inconclusive, which is why "
                  f"this is measured forward")

    plans = cx.execute("SELECT arm, status, COUNT(*) n FROM arm_plans "
                       "GROUP BY arm, status ORDER BY arm, status").fetchall()
    if plans:
        print()
        print("  LISTING PLANS BY ARM")
        for a in C.ARM_IDS:
            bits = "  ".join(f"{r['status']}:{r['n']}" for r in plans if r["arm"] == a)
            print(f"      {a:5s} {bits or 'none yet'}")

    if openp:
        print()
        print(f"  OPEN")
        print(f"  {'arm':5s} {'token':10s} {'entry':>12s} {'TP':>12s} {'SL':>12s} "
              f"{'age':>7s} {'worst':>8s}")
        for p in openp:
            age = (store.now_ms() - p["opened_ms"]) / 3_600_000
            print(f"  {p['arm']:5s} {p['base']:10s} {p['entry_vwap']:12.8g} "
                  f"{p['tp_price']:12.8g} {p['sl_price']:12.8g} {age:6.1f}h "
                  f"{p['mae_pct']:+7.1f}%")
    print("=" * 90)
    print("  No arm is a confirmed edge. The pooled clean out-of-sample estimate is")
    print("  +3.46% on 111 events at t 3.03, which SITS ON its bar rather than past it.")
    print("  PREREG_ARMS.md and PREREG_VENUES.md freeze all four; none may be dropped.")
    print("=" * 90)
    return 0


def cmd_ledger(args):
    cx = store.connect()
    rows = cx.execute(
        "SELECT p.*, e.gap_hours FROM positions p JOIN events e ON e.id=p.event_id "
        "WHERE p.status='closed' ORDER BY p.opened_ms").fetchall()
    if not rows:
        print("no closed positions yet")
        return 0
    print(f"  {'arm':5s} {'opened':17s} {'token':9s} {'gap':>7s} {'entry slip':>11s} "
          f"{'exit slip':>10s} {'fund':>7s} {'gross':>8s} {'net':>8s} {'reason':10s}")
    for p in rows:
        opened = time.strftime("%Y-%m-%d %H:%M", time.gmtime(p["opened_ms"] / 1000))
        arm = p["arm"]
        gap = p["gap_hours"]
        gap_s = "-" if gap is None else f"{gap:+.0f}h"
        print(f"  {arm:5s} {opened:17s} {p['base']:9s} {gap_s:>7s} "
              f"{p['entry_slippage_bps']:10.1f}b {p['exit_slippage_bps']:9.1f}b "
              f"{p['funding_frac']*100:+6.2f}% {p['gross_pct']:+7.2f}% "
              f"{p['net_pct']:+7.2f}% {p['exit_reason']:10s}")
    return 0


def cmd_export(args):
    cx = store.connect()
    out = args.out or os.path.join(C.DATA_DIR, "export")
    os.makedirs(out, exist_ok=True)
    for table in ("events", "positions", "fills", "runs"):
        rows = cx.execute(f"SELECT * FROM {table}").fetchall()
        path = os.path.join(out, f"{table}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                for r in rows:
                    w.writerow(dict(r))
        print(f"  {table:10s} {len(rows):5d} rows -> {path}")
    summary = {"equity": store.get_equity(cx),
               "rule": {"entry_h": C.ENTRY_HOURS, "tp": C.TAKE_PROFIT,
                        "sl": C.STOP_LOSS, "hold_h": C.MAX_HOLD_HOURS,
                        "size_pct": C.POSITION_PCT},
               "backtest_expectation": BACKTEST}
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  summary.json written")
    return 0


# Lines that change on every render regardless of what happened. Stripping them is what
# lets the fingerprint mean "the page says something different" rather than "time passed".
_VOLATILE = re.compile(
    r"updated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"
    r"|last tick \d+ min ago"
    r"|>\d+(?:\.\d+)?d<"                      # running-for, in days
    r"|\d+ ticks in 24h"
    r"|\d+(?:\.\d+)?h</td>",                  # position ages
    re.I)


def _page_fingerprint(html):
    return hashlib.sha256(_VOLATILE.sub("", html).encode("utf-8")).hexdigest()[:32]


def cmd_publish(args):
    """Regenerate the monitor page and push it to the repo's docs/ directory.

    Publishing by git commit rather than by running a web server is deliberate: the
    host also runs the operator's live trading, and this bot binds no port.
    """
    import subprocess
    _log(args.verbose)
    log = logging.getLogger("listingbot")
    cx = store.connect()
    repo = args.repo or os.environ.get("LISTINGBOT_REPO", "/opt/listing-bot/repo")
    if not os.path.isdir(os.path.join(repo, ".git")):
        log.error("no git repo at %s", repo)
        return 1
    # A commit per tick would bury the repository in 288 noise commits a day, because
    # the page carries a "last updated" stamp that changes even when nothing happened.
    # So publish only when the SUBSTANCE changes, plus a floor so the stamp never looks
    # abandoned.
    #
    # The fingerprint is the rendered page with the volatile lines stripped out, NOT a
    # summary of the database. A database summary misses a change to the page itself:
    # the first two-arm build was skipped by exactly that bug, leaving a stale
    # single-arm page published while the host was already running both arms.
    docs = os.path.join(repo, "docs")
    os.makedirs(docs, exist_ok=True)
    dest = os.path.join(docs, "monitor.html")
    html = report.render(report.gather(cx))
    fp = _page_fingerprint(html)
    prev = cx.execute("SELECT value FROM meta WHERE key='publish_fp'").fetchone()
    last = cx.execute("SELECT value FROM meta WHERE key='publish_ms'").fetchone()
    age_h = (store.now_ms() - int(last["value"])) / 3_600_000 if last else 1e9
    if not args.force and prev and prev["value"] == fp and age_h < args.max_age_hours:
        log.info("page unchanged and last publish %.1fh ago — skipping", age_h)
        return 0
    with open(dest, "w", encoding="utf-8") as f:
        f.write(html)

    def git(*a, check=True):
        return subprocess.run(["git", "-C", repo, *a], capture_output=True,
                              text=True, check=check, timeout=120)

    try:
        git("add", "docs/monitor.html")
        if not git("status", "--porcelain", "docs/monitor.html").stdout.strip():
            log.info("monitor unchanged, nothing to publish")
            return 0
        eq = store.get_equity(cx)
        n = cx.execute("SELECT COUNT(*) n FROM positions WHERE status='closed'"
                       ).fetchone()["n"]
        git("-c", "user.name=listingbot", "-c", "user.email=listingbot@localhost",
            "-c", "commit.gpgsign=false", "commit", "-m",
            f"monitor: {n} closed, equity {eq:.2f}")
        for attempt in range(3):
            try:
                git("pull", "--rebase", "--autostash", "origin", "main")
                git("push", "origin", "main")
                store.set_meta(cx, "publish_fp", fp)
                store.set_meta(cx, "publish_ms", str(store.now_ms()))
                log.info("published monitor (%d closed, equity %.2f)", n, eq)
                return 0
            except subprocess.CalledProcessError as e:
                log.warning("push attempt %d failed: %s", attempt + 1,
                            (e.stderr or "")[-200:])
                time.sleep(3 * (attempt + 1))
        return 1
    except subprocess.CalledProcessError as e:
        log.error("git failed: %s", (e.stderr or "")[-300:])
        return 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="listingbot",
                                description="Paper-trade the Binance listing short. "
                                            "Records only; cannot place real orders.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick", help="one cycle: scan, open, manage (called by the timer)")
    sub.add_parser("status", help="human summary against the backtest expectation")
    sub.add_parser("ledger", help="every closed position with measured slippage")
    ex = sub.add_parser("export", help="dump tables to CSV")
    ex.add_argument("--out")
    pb = sub.add_parser("publish", help="regenerate the monitor page and git push it")
    pb.add_argument("--repo")
    pb.add_argument("--force", action="store_true",
                    help="publish even when nothing substantive changed")
    pb.add_argument("--max-age-hours", type=float, default=6.0,
                    help="publish anyway once the page is this stale (default 6)")
    args = ap.parse_args(argv)
    return {"tick": cmd_tick, "status": cmd_status, "ledger": cmd_ledger,
            "export": cmd_export, "publish": cmd_publish}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
