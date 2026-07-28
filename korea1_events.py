"""Step 1 for Korea: enumerate listing events. NO returns computed here.

The operator corrected the design and the correction is right: we do not trade in Korea. The
Korean listing is only the SIGNAL — a large domestic retail audience arriving at once — and
the trade is a USDT-margined perpetual somewhere else. So the price series must be a USDT
series too. That removes the objection that killed the first version of this idea: a KRW path
measures the token and the won together, and the kimchi premium would have been baked into
every number.

Consequence for the method: the Korean venue supplies only the timestamp. Everything else —
eligibility, pricing, exits — is unchanged from the frozen rule.

Upbit exposes no listing-time field, so anchors come from candles: one cheap probe per market
to reject anything that predates the window, then a walk back to the earliest daily candle for
the survivors. Bithumb times out from the research network and is probed from the VPS.

Run:  python korea1_events.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot"))
from listingbot import venues                # noqa: E402

D = r"C:\CLAUDECODE\listings\data"
UP = "https://api.upbit.com/v1"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
WINDOW_DAYS = 730
NOW_MS = int(time.time() * 1000)


def get(url, tries=3, pause=0.12):
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=25) as f:
                d = json.loads(f.read())
            time.sleep(pause)
            return d
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError):
            time.sleep(0.6 * (i + 1))
    return None


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000))


def upbit_markets():
    d = get(f"{UP}/market/all?isDetails=true")
    out = {}
    for x in (d or []):
        m = x.get("market", "")
        if not (m.startswith("KRW-") or m.startswith("USDT-")):
            continue
        base = m.split("-", 1)[1].upper()
        # prefer KRW as the signal market: it is the one Korean retail actually buys
        if base not in out or m.startswith("KRW-"):
            out[base] = m
    return out


def predates_window(market):
    """One request. If a daily candle exists before the window opens, this is not a new
    listing and no further calls are spent on it."""
    cutoff = NOW_MS - WINDOW_DAYS * 86400_000
    d = get(f"{UP}/candles/days?market={market}&to={iso(cutoff)}&count=1")
    return bool(d)


def earliest_day_ms(market):
    """Walk daily candles back until a page returns fewer than requested."""
    to = None
    oldest = None
    for _ in range(6):
        u = f"{UP}/candles/days?market={market}&count=200"
        if to:
            u += f"&to={iso(to)}"
        d = get(u)
        if not d:
            break
        ts = [int(time.mktime(time.strptime(x["candle_date_time_utc"],
                                            "%Y-%m-%dT%H:%M:%S"))) * 1000 for x in d]
        oldest = min(ts) if oldest is None else min(oldest, min(ts))
        if len(d) < 200:
            break
        to = oldest
    return oldest


def bithumb_from_vps():
    """Bithumb is unreachable locally; ask the VPS for its pair list."""
    import subprocess
    try:
        r = subprocess.run(
            ["ssh", "vector-vps",
             "curl -s --max-time 20 https://api.bithumb.com/public/ticker/ALL_KRW"],
            capture_output=True, text=True, timeout=90)
        d = json.loads(r.stdout)
        if d.get("status") == "0000":
            return sorted(k.upper() for k in d["data"] if k != "date")
    except Exception:                                       # noqa: BLE001
        pass
    return []


def main():
    print("=" * 112)
    print("  KOREA, STEP 1 — the sample, with no outcome computed")
    print("=" * 112)
    print("  the Korean venue supplies the TIMESTAMP only; the trade and the price series")
    print("  are USDT, so the kimchi premium and the won never enter the measurement")

    mk = upbit_markets()
    print(f"\n  Upbit KRW/USDT markets, one per token: {len(mk)}")

    inwin = {}
    checked = 0
    for base, market in sorted(mk.items()):
        checked += 1
        if predates_window(market):
            continue
        d = earliest_day_ms(market)
        if d and (NOW_MS - d) <= WINDOW_DAYS * 86400_000:
            inwin[base] = {"market": market, "first_day_ms": d}
        if checked % 60 == 0:
            print(f"    probed {checked}/{len(mk)}, inside the window: {len(inwin)}")
    print(f"  Upbit listings inside the {WINDOW_DAYS}d window: {len(inwin)}")

    bt = bithumb_from_vps()
    print(f"  Bithumb KRW pairs seen from the VPS: {len(bt)}"
          f"{'  (unreachable)' if not bt else ''}")
    if bt:
        extra = sorted(set(bt) - set(mk))
        print(f"    tokens on Bithumb but not on Upbit: {len(extra)}")
        print("    Bithumb has no per-pair listing-time endpoint and its candlestick feed")
        print("    returns a fixed window, so anchors cannot be derived the same way.")
        print("    It is recorded here and NOT used as a signal source.")

    rows = []
    for base, r in inwin.items():
        rows.append({"base": base, "market": r["market"],
                     "first_day_ms": r["first_day_ms"],
                     "age_days": round((NOW_MS - r["first_day_ms"]) / 86400_000, 1),
                     "on_bithumb": base in set(bt)})
    T = pd.DataFrame(rows).sort_values("first_day_ms").reset_index(drop=True)

    print("\n" + "-" * 112)
    print("  FROZEN FEASIBILITY RULE — a Gate perpetual must exist by the entry hour")
    print("-" * 112)
    pi = venues.perp_index()
    gl, gap = [], []
    for _, r in T.iterrows():
        p = pi.get(r.base)
        if p and p.get("venue") == "gate":
            gl.append(p["launch_ms"])
            gap.append((p["launch_ms"] - r.first_day_ms) / 3_600_000)
        else:
            gl.append(None)
            gap.append(None)
    T["gate_launch_ms"], T["gap_h"] = gl, gap
    for h in (12, 18):
        print(f"  perp by T+{h}h: {int((T.gap_h.notna() & (T.gap_h <= h)).sum())}")

    print("\n" + "-" * 112)
    print("  OVERLAP — with the Binance study and with every replication already run")
    print("-" * 112)
    B = pd.read_csv(os.path.join(D, "listings_joined.csv"))
    anch = json.load(open(os.path.join(D, "true_anchors.json")))
    bmap = {r.base.upper(): int(anch[r.symbol]) for _, r in B.iterrows()
            if r.symbol in anch}
    used = set()
    for f in ("bybit_results.csv", "pool_results.csv", "coinbase_results.csv"):
        p = os.path.join(D, f)
        if os.path.exists(p):
            used |= set(pd.read_csv(p).base.str.upper())

    E = T[T.gap_h.notna() & (T.gap_h <= 18)].copy()
    E["bn_ms"] = E.base.map(bmap)
    E["sep_d"] = (E.first_day_ms - E.bn_ms) / 86400_000
    E["in_binance_study"] = E.bn_ms.notna()
    E["overlaps_binance"] = E.in_binance_study & (E.sep_d.abs() < 3)
    E["clean"] = ~E.in_binance_study
    E["weak"] = E.in_binance_study & ~E.overlaps_binance

    print(f"  eligible Upbit events: {len(E)}")
    print(f"    token never in the Binance study            : {int(E.clean.sum())}")
    print(f"    shared, but Upbit listing 3+ days apart      : {int(E.weak.sum())}")
    print(f"    shared AND within 3 days (not independent)   : {int(E.overlaps_binance.sum())}")
    print(f"    token already appearing in an earlier replication: "
          f"{int(E.base.isin(used).sum())}")
    if int(E.in_binance_study.sum()):
        print(f"    median separation for shared tokens: "
              f"{E[E.in_binance_study].sep_d.abs().median():.0f} days")

    import math
    sd = 14.61
    for label, n in (("clean", int(E.clean.sum())),
                     ("clean + weak", int((E.clean | E.weak).sum()))):
        if n > 2:
            print(f"\n  power at {label} n={n}:")
            for m in (1.18, 2.76, 8.53):
                print(f"    true mean {m:+.2f}% -> expected t {m/(sd/math.sqrt(n)):.2f}")

    T.to_csv(os.path.join(D, "korea_events.csv"), index=False)
    E.to_csv(os.path.join(D, "korea_eligible.csv"), index=False)
    print(f"\n  written to {os.path.join(D, 'korea_events.csv')} and korea_eligible.csv")
    print("  NO returns computed. Pre-register before running the rule.")
    print("=" * 112)


if __name__ == "__main__":
    main()
