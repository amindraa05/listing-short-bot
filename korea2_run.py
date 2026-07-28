"""Run the frozen rule on Upbit listings, priced on USDT. Plus the declared placebo control.

PREREG_KOREA.md was committed to git before this computed anything. It declares the primary
(67 clean tokens), the bar (2.73 for a fourth replication), the price-series priority, the
placebo control, and what each outcome will be taken to mean.

Run:  python korea2_run.py
"""
import json
import math
import os
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

D = r"C:\CLAUDECODE\listings\data"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
TP, SL, HOLD, LIQ = 0.15, 0.15, 72, 0.95
SPREAD, TAKER = 0.003, 0.00075
ARMS = {"t12": 12, "t18": 18}
BAR = 2.73
WINDOW_H = 115
PLACEBO_OFFSETS_D = [30, 60, 120, 240]
RNG = np.random.default_rng(20260728)


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=25) as f:
                return json.loads(f.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError):
            time.sleep(0.7 * (i + 1))
    return None


def _f(rows):
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["t", "o", "h", "l", "c"]).sort_values(
        "t").reset_index(drop=True)


def s_binance(b, ms):
    d = get(f"https://data-api.binance.vision/api/v3/klines?symbol={b}USDT"
            f"&interval=1h&startTime={ms}&limit={WINDOW_H}")
    return _f([[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])]
               for x in (d or [])])


def s_bybit(b, ms):
    d = get(f"https://api.bybit.nl/v5/market/kline?category=spot&symbol={b}USDT"
            f"&interval=60&start={ms}&end={ms + WINDOW_H*3600_000}&limit=1000")
    r = (d or {}).get("result") or {}
    return _f([[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])]
               for x in r.get("list", [])])


def s_okx(b, ms):
    d = get(f"https://www.okx.com/api/v5/market/history-candles?instId={b}-USDT"
            f"&bar=1H&after={ms + WINDOW_H*3600_000}&limit=300")
    return _f([[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])]
               for x in (d or {}).get("data", []) if int(x[0]) >= ms])


def s_kucoin(b, ms):
    d = get(f"https://api.kucoin.com/api/v1/market/candles?type=1hour&symbol={b}-USDT"
            f"&startAt={ms//1000}&endAt={ms//1000 + WINDOW_H*3600}")
    # KuCoin: [t, open, close, high, low, volume, turnover]
    return _f([[int(x[0])*1000, float(x[1]), float(x[3]), float(x[4]), float(x[2])]
               for x in (d or {}).get("data", [])])


def s_gate(b, ms):
    d = get(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={b}_USDT"
            f"&interval=1h&from={ms//1000}&to={ms//1000 + WINDOW_H*3600}")
    # Gate: [t, quoteVol, close, high, low, open, baseVol, closed]
    return _f([[int(x[0])*1000, float(x[5]), float(x[3]), float(x[4]), float(x[2])]
               for x in (d or []) if isinstance(d, list)])


ORDER = [("binance", s_binance), ("bybit", s_bybit), ("okx", s_okx),
         ("kucoin", s_kucoin), ("gate", s_gate)]

UP = "https://api.upbit.com/v1"


def upbit_first_hour_ms(market, day_ms):
    """The hour UPBIT itself first traded the pair. This is the anchor.

    The first run of this file anchored on the daily candle's midnight UTC. Because these
    tokens already trade on other venues, the USDT series HAS a candle at midnight, so
    nothing was lost and nothing looked wrong -- and it produced a spurious +5.91% at
    t 5.76 on the t18 arm. Upbit lists in the Korean afternoon, roughly 06:00-10:00 UTC,
    so "midnight + 18h" was really 8-12h past the listing, beyond the pump's peak, while
    "midnight + 12h" was 2-6h past it and still inside the pump. The two arms were
    measuring two different events and neither was the one under test.

    Third time this project has had to fix a midnight anchor.
    """
    to = time.strftime("%Y-%m-%dT%H:%M:%S",
                       time.gmtime((day_ms + 200 * 3600_000) / 1000))
    d = get(f"{UP}/candles/minutes/60?market={market}&to={to}&count=200")
    if not d:
        return None
    ts = []
    for x in d:
        try:
            ts.append(int(time.mktime(time.strptime(
                x["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S"))) * 1000)
        except (KeyError, ValueError):
            continue
    ts = [t for t in ts if t >= day_ms]
    return min(ts) if ts else None


def series(base, ms):
    """First usable USDT series in the declared priority order, with its anchor."""
    for name, fn in ORDER:
        try:
            K = fn(base, ms)
        except Exception:                                   # noqa: BLE001
            K = None
        if K is not None and len(K) >= 40:
            return K, int(K.t.iloc[0]), name
        time.sleep(0.02)
    return None, None, None


def short(K, anchor_ms, entry_h):
    e = K[K.t <= anchor_ms + entry_h * 3600_000]
    if e.empty:
        return None, "no bar at the entry hour"
    i0 = e.index[-1]
    if (anchor_ms + entry_h * 3600_000 - K.t.iloc[i0]) / 3600_000 > 2:
        return None, "entry bar more than 2h stale"
    if len(K) - i0 - 1 < HOLD * 0.5:
        return None, "less than half the hold window after the entry"
    en = float(K.c.iloc[i0]) * (1 - SPREAD / 2)
    if en <= 0:
        return None, "non-positive entry"
    w = K.iloc[i0 + 1:].head(HOLD)
    if w.empty:
        return None, "no bars after the entry"
    tp, hard = en * (1 - TP), en * (1 + LIQ)
    sl = min(en * (1 + SL), hard)
    o, h, l, c = (w[x].to_numpy() for x in ("o", "h", "l", "c"))
    px, why, bars = None, "time", len(w)
    for j in range(len(w)):
        if j > 0 and o[j] >= sl:
            px, why, bars = o[j], "stop", j + 1
            break
        if h[j] >= sl:
            px, why, bars = sl, "stop", j + 1
            break
        if l[j] <= tp:
            px, why, bars = tp, "target", j + 1
            break
    if px is None:
        px = c[-1]
    ex = px * (1 + SPREAD / 2)
    return {"pnl_pct": ((en - ex) / en - 2 * TAKER) * 100, "reason": why, "bars": bars,
            "mae_pct": (float(w.h.max()) / en - 1) * 100}, None


def st(v):
    v = np.asarray(list(v), float)
    if len(v) < 3:
        return None
    m, sd = v.mean(), v.std(ddof=1)
    se = sd / math.sqrt(len(v))
    return {"n": len(v), "mean": m, "med": float(np.median(v)),
            "win": (v > 0).mean() * 100, "sd": sd, "se": se,
            "t": m / se if se else 0.0, "lo": m - 1.96 * se, "hi": m + 1.96 * se}


def show(label, x):
    if not x:
        print(f"  {label:46s} n<3")
        return
    v = ("CLEARS THE BAR" if x["t"] >= BAR else
         ("positive, below the bar" if x["mean"] > 0 else "NEGATIVE"))
    print(f"  {label:46s} n {x['n']:>3d}  mean {x['mean']:+6.2f}%  med {x['med']:+7.2f}%  "
          f"win {x['win']:>5.1f}%  t {x['t']:+5.2f}  CI [{x['lo']:+6.2f},{x['hi']:+6.2f}]  {v}")


def main():
    E = pd.read_csv(os.path.join(D, "korea_eligible.csv"))
    print("=" * 124)
    print("  KOREA (UPBIT) — the frozen rule, signal from Korea, price and trade in USDT")
    print("=" * 124)
    print(f"  bar t {BAR:.2f} (fourth replication, two arms: 2.0 + 0.35*ln(8))")
    print(f"  eligible events {len(E)}   clean primary {int(E.clean.sum())}")

    rows, lost, cache = [], {}, {}
    for i, (_, r) in enumerate(E.iterrows(), 1):
        anchor = upbit_first_hour_ms(r["market"], int(r.first_day_ms))
        if anchor is None:
            lost["no Upbit hourly candle at the listing"] = \
                lost.get("no Upbit hourly candle at the listing", 0) + 1
            continue
        K, _, src = series(r.base, anchor)
        if K is None:
            lost["no usable USDT series"] = lost.get("no usable USDT series", 0) + 1
            continue
        # the USDT series must actually cover the anchor rather than start days later
        drift_h = (int(K.t.iloc[0]) - anchor) / 3_600_000
        if drift_h > 2:
            lost["USDT series starts more than 2h after the listing"] = \
                lost.get("USDT series starts more than 2h after the listing", 0) + 1
            continue
        cache[r.base] = (r["market"], anchor)
        for arm, h in ARMS.items():
            if r.gap_h > h:
                lost[f"{arm}: perp not present by the entry hour"] = \
                    lost.get(f"{arm}: perp not present by the entry hour", 0) + 1
                continue
            tr, why = short(K, anchor, h)
            if tr is None:
                lost[f"{arm}: {why}"] = lost.get(f"{arm}: {why}", 0) + 1
                continue
            rows.append({"arm": arm, "base": r.base, "price_src": src,
                         "gap_h": r.gap_h, "clean": bool(r.clean), "weak": bool(r.weak),
                         "anchor_ms": anchor,
                         "anchor_offset_h": (anchor - int(r.first_day_ms)) / 3_600_000,
                         "series_drift_h": drift_h,
                         **tr})
        if i % 25 == 0:
            print(f"    processed {i}/{len(E)}")

    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(D, "korea_results.csv"), index=False)

    print("\n" + "=" * 124)
    print("  PRIMARY — clean tokens, never in the Binance study")
    print("=" * 124)
    for arm in ARMS:
        show(f"arm {arm} (T+{ARMS[arm]}h) clean", st(R[(R.arm == arm) & R.clean].pnl_pct))

    print("\n" + "=" * 124)
    print("  SECONDARY — clean plus shared-but-separated (median 79 days apart)")
    print("=" * 124)
    for arm in ARMS:
        show(f"arm {arm} (T+{ARMS[arm]}h) clean+weak",
             st(R[(R.arm == arm) & (R.clean | R.weak)].pnl_pct))

    print("\n" + "=" * 124)
    print("  CONTEXT — everything eligible, including the 27 that overlap Binance windows")
    print("=" * 124)
    for arm in ARMS:
        show(f"arm {arm} (T+{ARMS[arm]}h) all", st(R[R.arm == arm].pnl_pct))
        show(f"arm {arm} overlapping only (contaminated)",
             st(R[(R.arm == arm) & ~R.clean & ~R.weak].pnl_pct))

    print("\n" + "=" * 124)
    print("  BY PRICE SOURCE — this mattered before, 1.2pp between venues")
    print("=" * 124)
    for src in sorted(R.price_src.dropna().unique()):
        show(f"t12 clean, priced on {src}",
             st(R[(R.arm == "t12") & R.clean & (R.price_src == src)].pnl_pct))

    print("\n" + "=" * 124)
    print("  EXIT MIX")
    print("=" * 124)
    print(f"  {'sample':22s}{'target':>8}{'stop':>7}{'time':>7}{'median MAE':>12}"
          f"{'liq unstopped':>15}")
    print(f"  {'Binance t12 (n115)':22s}{61:>8}{39:>7}{15:>7}{'~10%':>12}{'7':>15}")
    for lab, sub in (("Korea t12 clean", R[(R.arm == "t12") & R.clean]),
                     ("Korea t18 clean", R[(R.arm == "t18") & R.clean])):
        if sub.empty:
            continue
        vc = sub.reason.value_counts()
        print(f"  {lab:22s}{vc.get('target',0):>8}{vc.get('stop',0):>7}"
              f"{vc.get('time',0):>7}{sub.mae_pct.median():>11.1f}%"
              f"{int((sub.mae_pct>95).sum()):>15}")

    # ---- the declared placebo control -------------------------------------
    print("\n" + "=" * 124)
    print("  PLACEBO CONTROL — same tokens, same rule, dates unrelated to any listing")
    print("=" * 124)
    # BOTH arms get a control. The first run controlled only t12 while the positive
    # result sat on t18, which left the headline entirely untested.
    clean_bases = R[(R.arm == "t12") & R.clean].base.unique()
    plac = []
    for i, b in enumerate(clean_bases, 1):
        _, anchor = cache.get(b, (None, None))
        if anchor is None:
            continue
        for off in PLACEBO_OFFSETS_D:
            start = anchor + off * 86400_000
            if start > (time.time() - 8 * 86400) * 1000:
                continue
            K, _, src = series(b, start)
            if K is None:
                continue
            base_anchor = int(K.t.iloc[0])
            for arm, h in ARMS.items():
                tr, _ = short(K, base_anchor, h)
                if tr:
                    plac.append({"base": b, "off": off, "arm": arm, **tr})
        if i % 20 == 0:
            print(f"    {i}/{len(clean_bases)} tokens, {len(plac)} placebo trades")
    P = pd.DataFrame(plac)
    P.to_csv(os.path.join(D, "korea_placebo.csv"), index=False)
    for arm in ARMS:
        real = st(R[(R.arm == arm) & R.clean].pnl_pct)
        pl = st(P[P.arm == arm].pnl_pct) if len(P) else None
        show(f"REAL {arm} — entered at the Upbit listing", real)
        show(f"PLACEBO {arm} — arbitrary dates", pl)
        if real and pl:
            sed = math.sqrt(real["se"]**2 + pl["se"]**2)
            d = real["mean"] - pl["mean"]
            verdict = "beyond drift" if abs(d / sed) >= 2 else "not separable from drift"
            print(f"    listing minus placebo: {d:+.2f} pp   se {sed:.2f}   "
                  f"t {d/sed:+.2f}   -> {verdict}")
        print()

    # ---- the pooled large-venue estimate ----------------------------------
    print("\n" + "=" * 124)
    print("  THE POOLED LARGE-VENUE ESTIMATE — the number this whole exercise converges on")
    print("=" * 124)
    cb = pd.read_csv(os.path.join(D, "coinbase_results.csv"))
    cbc = cb[(cb.arm == "t12") & cb.clean].pnl_pct.to_numpy()
    kr = R[(R.arm == "t12") & R.clean].pnl_pct.to_numpy()
    pool = pd.read_csv(os.path.join(D, "pool_results.csv"))
    sm = pool[pool.arm == "t12"].pnl_pct.to_numpy()
    show("Coinbase clean", st(cbc))
    show("Upbit clean", st(kr))
    show("LARGE-VENUE CLEAN POOLED", st(np.concatenate([cbc, kr])))
    show("small-venue pool (for contrast)", st(sm))
    L, S = st(np.concatenate([cbc, kr])), st(sm)
    if L and S:
        sed = math.sqrt(L["se"]**2 + S["se"]**2)
        d = L["mean"] - S["mean"]
        print(f"\n  large minus small: {d:+.2f} pp   se {sed:.2f}   t {d/sed:+.2f}")

    print("\n" + "=" * 124)
    print("  EVENTS LOST")
    print("=" * 124)
    for k, v in sorted(lost.items(), key=lambda kv: -kv[1]):
        print(f"    {v:>3d}  {k}")
    o = R[R.arm == "t12"].anchor_offset_h
    dr = R[R.arm == "t12"].series_drift_h
    print(f"\n  Upbit first traded hour, offset from midnight UTC: "
          f"median {o.median():.1f}h  p25 {o.quantile(.25):.1f}h  "
          f"p75 {o.quantile(.75):.1f}h")
    print(f"  USDT series drift from that anchor: median {dr.median():.2f}h  "
          f"max {dr.max():.2f}h  (anything above 2h was dropped)")
    print("  A median offset near zero would mean the midnight bug is still present.")
    print(f"  per-event results written to {os.path.join(D, 'korea_results.csv')}")
    print("=" * 124)


if __name__ == "__main__":
    main()
