"""Command line: tick, status, ledger, export.

`tick` is what the systemd timer calls. Everything else is for a human reading results.
"""
import argparse
import csv
import json
import logging
import os
import sys
import time

from . import config as C
from . import engine, report, store

BACKTEST = {"n": 115, "mean": 2.71, "median": 14.77, "win": 62.6, "t": 1.99,
            "sd": 14.6, "bar": 3.55}


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


def cmd_status(args):
    cx = store.connect()
    eq = store.get_equity(cx)
    started = cx.execute("SELECT value FROM meta WHERE key='started_ms'").fetchone()
    days = ((store.now_ms() - int(started["value"])) / 86400_000) if started else 0
    closed = cx.execute(
        "SELECT net_pct, pnl_usdt, exit_reason FROM positions WHERE status='closed'"
    ).fetchall()
    openp = store.open_positions(cx)
    ev = {r["status"]: r["n"] for r in cx.execute(
        "SELECT status, COUNT(*) n FROM events GROUP BY status")}

    print("=" * 78)
    print("  LISTING-SHORT PAPER TEST")
    print("=" * 78)
    print(f"  running for            {days:.1f} days")
    print(f"  rule                   entry T+{C.ENTRY_HOURS}h, TP {C.TAKE_PROFIT*100:.0f}%, "
          f"SL {C.STOP_LOSS*100:.0f}%, hold {C.MAX_HOLD_HOURS}h, size "
          f"{C.POSITION_PCT*100:.0f}%")
    print(f"  paper equity           {eq:,.2f} {C.CURRENCY}  "
          f"(from {C.PAPER_START_EQUITY:,.2f})")
    print(f"  events by status       " + ("  ".join(f"{k}:{v}" for k, v in ev.items())
                                          or "none yet"))
    print(f"  positions              {len(closed)} closed, {len(openp)} open")

    if closed:
        nets = [c["net_pct"] for c in closed if c["net_pct"] is not None]
        wins = sum(1 for n in nets if n > 0)
        mean = sum(nets) / len(nets)
        reasons = {}
        for c in closed:
            reasons[c["exit_reason"]] = reasons.get(c["exit_reason"], 0) + 1
        print(f"\n  LIVE RESULT SO FAR")
        print(f"    n                    {len(nets)}")
        print(f"    mean                 {mean:+.2f}%")
        print(f"    win rate             {wins/len(nets)*100:.1f}%")
        print(f"    exits                " + "  ".join(f"{k}:{v}" for k, v in reasons.items()))
        if len(nets) > 2:
            sd = (sum((x - mean) ** 2 for x in nets) / (len(nets) - 1)) ** 0.5
            t = mean / (sd / len(nets) ** 0.5) if sd > 0 else 0.0
            print(f"    sd                   {sd:.1f}%")
            print(f"    t                    {t:+.2f}   (bar {BACKTEST['bar']})")
        print(f"\n  BACKTEST EXPECTATION, for comparison")
        print(f"    n {BACKTEST['n']}  mean {BACKTEST['mean']:+.2f}%  "
              f"win {BACKTEST['win']}%  t {BACKTEST['t']}  sd {BACKTEST['sd']}%")
        print(f"\n  The backtest did NOT clear its bar of {BACKTEST['bar']}. This test is")
        print(f"  the missing evidence, not a confirmation of a known edge.")
        if len(nets) < 15:
            print(f"  {15-len(nets)} more trades before even a disaster check is meaningful.")
        elif wins / len(nets) <= 0.40:
            print(f"  WIN RATE AT OR BELOW 40% — this is the pre-agreed stop signal.")
    else:
        print("\n  no closed positions yet")

    if openp:
        print(f"\n  OPEN")
        print(f"  {'token':10s} {'entry':>12s} {'TP':>12s} {'SL':>12s} {'age':>7s} "
              f"{'worst':>8s}")
        for p in openp:
            age = (store.now_ms() - p["opened_ms"]) / 3_600_000
            print(f"  {p['base']:10s} {p['entry_vwap']:12.8g} {p['tp_price']:12.8g} "
                  f"{p['sl_price']:12.8g} {age:6.1f}h {p['mae_pct']:+7.1f}%")
    print("=" * 78)
    return 0


def cmd_ledger(args):
    cx = store.connect()
    rows = cx.execute(
        "SELECT p.*, e.gap_hours FROM positions p JOIN events e ON e.id=p.event_id "
        "WHERE p.status='closed' ORDER BY p.opened_ms").fetchall()
    if not rows:
        print("no closed positions yet")
        return 0
    print(f"  {'opened':17s} {'token':9s} {'gap':>7s} {'entry slip':>11s} "
          f"{'exit slip':>10s} {'fund':>7s} {'gross':>8s} {'net':>8s} {'reason':10s}")
    for p in rows:
        opened = time.strftime("%Y-%m-%d %H:%M", time.gmtime(p["opened_ms"] / 1000))
        gap = p["gap_hours"]
        gap_s = "-" if gap is None else f"{gap:+.0f}h"
        print(f"  {opened:17s} {p['base']:9s} {gap_s:>7s} "
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
    # So publish when the SUBSTANCE changes, plus a floor so the stamp never looks dead.
    fp = "|".join(str(x) for x in cx.execute(
        "SELECT (SELECT COUNT(*) FROM events), (SELECT COUNT(*) FROM positions), "
        "(SELECT COUNT(*) FROM positions WHERE status='closed'), "
        "(SELECT ROUND(COALESCE(SUM(pnl_usdt),0),4) FROM positions)").fetchone())
    prev = cx.execute("SELECT value FROM meta WHERE key='publish_fp'").fetchone()
    last = cx.execute("SELECT value FROM meta WHERE key='publish_ms'").fetchone()
    age_h = (store.now_ms() - int(last["value"])) / 3_600_000 if last else 1e9
    if not args.force and prev and prev["value"] == fp and age_h < args.max_age_hours:
        log.info("state unchanged and last publish %.1fh ago — skipping", age_h)
        return 0

    docs = os.path.join(repo, "docs")
    os.makedirs(docs, exist_ok=True)
    dest = os.path.join(docs, "monitor.html")
    report.write(cx, dest)

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
