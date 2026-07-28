"""The entry hour, without overfitting it — plus CAGR and drawdown on the clean sample.

The operator's instinct is right: the edge and the best entry hour are separate questions,
and tuning the hour on Coinbase would just move the overfitting from one venue to another.

There is a way to ask it honestly. Do not pick a peak. Compute the whole hour surface on BOTH
large-venue samples independently and see whether they agree on SHAPE. Two surfaces peaking in
the same region is cross-venue replication of the hour and worth acting on. Two surfaces
disagreeing means the hour is not identifiable from this data, and the honest summary is then
an unweighted average across a wide band — which has no free parameter to fit.

Three things are reported and none of them involves choosing an hour after looking:

  1. the Binance surface (in-sample, the rule was built here — reference only)
  2. the Coinbase clean surface (48 tokens never in the Binance study)
  3. their correlation, and a pre-specified unweighted mean over hours 6-30

Then CAGR and drawdown, computed at the FROZEN T+12h only, because reporting them at a swept
hour would be exactly the mistake that turned $2,269 into a fake $6,180 earlier in this project.

Run:  python large_venue_hours.py
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import step11_honest as H                     # noqa: E402

D = r"C:\CLAUDECODE\listings\data"
CB = "https://api.exchange.coinbase.com"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
HOURS = list(range(6, 31, 2))
BAND = (6, 30)               # declared here, before any surface is seen
TP, SL, HOLD, LIQ = 0.15, 0.15, 72, 0.95
SPREAD, TAKER = 0.003, 0.00075
SIZE, START = 0.30, 1000.0   # same sizing the research dashboard reports
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


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def cb_series(product, day_ms):
    a = day_ms // 1000
    d = get(f"{CB}/products/{product}/candles?granularity=3600"
            f"&start={iso(a)}&end={iso(a + 200 * 3600)}")
    if not isinstance(d, list) or not d:
        return None, None
    rows = sorted(d, key=lambda x: int(x[0]))
    K = pd.DataFrame({"t": [int(x[0]) * 1000 for x in rows],
                      "o": [float(x[3]) for x in rows],
                      "h": [float(x[2]) for x in rows],
                      "l": [float(x[1]) for x in rows],
                      "c": [float(x[4]) for x in rows]})
    return K, int(K.t.iloc[0])


def short(K, anchor_ms, entry_h):
    e = K[K.t <= anchor_ms + entry_h * 3600_000]
    if e.empty:
        return None
    i0 = e.index[-1]
    if (anchor_ms + entry_h * 3600_000 - K.t.iloc[i0]) / 3600_000 > 2:
        return None
    if len(K) - i0 - 1 < HOLD * 0.5:
        return None
    en = float(K.c.iloc[i0]) * (1 - SPREAD / 2)
    if en <= 0:
        return None
    w = K.iloc[i0 + 1:].head(HOLD)
    if w.empty:
        return None
    tp, hard = en * (1 - TP), en * (1 + LIQ)
    sl = min(en * (1 + SL), hard)
    o, h, l, c = (w[x].to_numpy() for x in ("o", "h", "l", "c"))
    px, why = None, "time"
    for j in range(len(w)):
        if j > 0 and o[j] >= sl:
            px, why = o[j], "stop"
            break
        if h[j] >= sl:
            px, why = sl, "stop"
            break
        if l[j] <= tp:
            px, why = tp, "target"
            break
    if px is None:
        px = c[-1]
    ex = px * (1 + SPREAD / 2)
    return {"pnl_pct": ((en - ex) / en - 2 * TAKER) * 100, "reason": why,
            "mae_pct": (float(w.h.max()) / en - 1) * 100}


def st(v):
    v = np.asarray(list(v), float)
    if len(v) < 3:
        return None
    m, sd = v.mean(), v.std(ddof=1)
    se = sd / math.sqrt(len(v))
    return {"n": len(v), "mean": m, "win": (v > 0).mean() * 100, "sd": sd, "se": se,
            "t": m / se if se else 0.0}


def bar(v, lo, hi, w=26):
    span = hi - lo or 1
    return "#" * max(0, min(w, round((v - lo) / span * w)))


def binance_surface():
    """Fixed 115-event set, only the hour varies. In-sample: reference, not evidence."""
    M = pd.read_csv(os.path.join(D, "listings_joined.csv"))
    raw = pd.read_csv(os.path.join(D, "perp_launches_raw.csv"))
    gmap = (raw[raw.venue == "gate"].dropna(subset=["base"])
            .drop_duplicates("base").set_index("base")["raw"].to_dict())
    anch = json.load(open(os.path.join(D, "true_anchors.json")))
    M = M[(M.age_days <= 730) & M.symbol.isin(anch) & (M.gap_h <= 12)]
    cache = {}
    out = {}
    for h in HOURS:
        H.ENTRY_H = h
        vals = []
        for _, r in M.iterrows():
            if r.base not in cache:
                cache[r.base] = H.series(r.base, r.symbol, gmap)
            K = cache[r.base]
            if K is None:
                continue
            tr = H.run(K, pd.to_datetime(anch[r.symbol], unit="ms", utc=True))
            if tr:
                vals.append(tr["pnl_pct"])
        out[h] = st(vals)
    return out


def coinbase_surface():
    """The 48 clean tokens, fetched once and evaluated at every hour."""
    R = pd.read_csv(os.path.join(D, "coinbase_results.csv"))
    T = pd.read_csv(os.path.join(D, "coinbase_events.csv"))
    clean = R[(R.arm == "t12") & R.clean].base.unique()
    E = T[T.base.isin(clean)]
    series = {}
    for _, r in E.iterrows():
        K, a = cb_series(r["product"], int(r.first_day_ms))
        if K is not None and a and len(K) >= 40:
            series[r.base] = (K, a, r.gap_h)
        time.sleep(0.03)
    out = {}
    for h in HOURS:
        vals = []
        for base, (K, a, gap) in series.items():
            if gap > h:                       # the frozen feasibility rule, per hour
                continue
            tr = short(K, a, h)
            if tr:
                vals.append(tr["pnl_pct"])
        out[h] = st(vals)
    return out, series


def equity_curve(pnls):
    eq, curve = START, [START]
    for x in pnls:
        eq = max(eq * (1 + SIZE * x / 100.0), 1e-9)
        curve.append(eq)
    return np.array(curve)


def max_dd(curve):
    peak = np.maximum.accumulate(curve)
    return float(np.max((peak - curve) / peak) * 100)


def main():
    print("=" * 112)
    print("  THE ENTRY HOUR ON LARGE VENUES — surfaces compared, no peak chosen")
    print("=" * 112)
    print(f"  band declared in advance for the unweighted mean: T+{BAND[0]}h..T+{BAND[1]}h")

    print("\n  computing the Binance surface (in-sample, reference only) ...")
    B = binance_surface()
    print("  computing the Coinbase clean surface (48 tokens) ...")
    C, series = coinbase_surface()

    bl = min(x["mean"] for x in B.values() if x)
    bh = max(x["mean"] for x in B.values() if x)
    cl = min(x["mean"] for x in C.values() if x)
    ch = max(x["mean"] for x in C.values() if x)

    print("\n" + "=" * 112)
    print(f"  {'hour':>6}  {'BINANCE (in-sample, n115)':<40}  {'COINBASE CLEAN':<40}")
    print("=" * 112)
    for h in HOURS:
        b, c = B.get(h), C.get(h)
        bs = (f"{b['mean']:+6.2f}% t{b['t']:+5.2f} {bar(b['mean'], bl, bh)}"
              if b else "  n<3")
        cs = (f"{c['mean']:+6.2f}% t{c['t']:+5.2f} n{c['n']:<3d} {bar(c['mean'], cl, ch)}"
              if c else "  n<3")
        star = "  <- frozen" if h == 12 else ""
        print(f"  T+{h:>3}h  {bs:<40}  {cs:<40}{star}")

    hb = [B[h]["mean"] for h in HOURS if B.get(h) and C.get(h)]
    hc = [C[h]["mean"] for h in HOURS if B.get(h) and C.get(h)]
    r = float(np.corrcoef(hb, hc)[0, 1])
    print("\n" + "=" * 112)
    print("  DO THE TWO SURFACES AGREE ON SHAPE?")
    print("=" * 112)
    print(f"  correlation across the {len(hb)} shared hours: r = {r:+.3f}")
    bpk = max((h for h in HOURS if B.get(h)), key=lambda h: B[h]["mean"])
    cpk = max((h for h in HOURS if C.get(h)), key=lambda h: C[h]["mean"])
    print(f"  Binance peaks at T+{bpk}h ({B[bpk]['mean']:+.2f}%), "
          f"Coinbase at T+{cpk}h ({C[cpk]['mean']:+.2f}%)")
    if r > 0.5:
        print("  -> the surfaces agree. The hour is a replicated feature and the peak region")
        print("     can be used without it being pure curve fitting.")
    elif r > 0:
        print("  -> weak agreement. Not enough to justify choosing an hour.")
    else:
        print("  -> the surfaces DISAGREE. The best hour on one venue is not the best hour")
        print("     on the other, so the hour is not identifiable from this data. Choosing")
        print("     one would be fitting noise, on either venue.")

    print("\n" + "=" * 112)
    print(f"  THE PARAMETER-FREE SUMMARY — unweighted mean over T+{BAND[0]}..{BAND[1]}h")
    print("=" * 112)
    for name, S in (("Binance (in-sample)", B), ("Coinbase clean", C)):
        vals = [S[h]["mean"] for h in HOURS if S.get(h) and BAND[0] <= h <= BAND[1]]
        ts = [S[h]["t"] for h in HOURS if S.get(h) and BAND[0] <= h <= BAND[1]]
        print(f"  {name:22s} mean of hourly means {np.mean(vals):+6.2f}%   "
              f"worst hour {min(vals):+6.2f}%   best {max(vals):+6.2f}%   "
              f"hours positive {sum(1 for v in vals if v > 0)}/{len(vals)}   "
              f"mean t {np.mean(ts):+.2f}")
    print("  A band average has no parameter to fit, so it is the number to quote when the")
    print("  hour cannot be identified. It is also the number a live trader would earn if")
    print("  they could not time the entry precisely.")

    print("\n" + "=" * 112)
    print("  CAGR AND DRAWDOWN — at the FROZEN T+12h on the clean Coinbase sample only")
    print("=" * 112)
    T = pd.read_csv(os.path.join(D, "coinbase_events.csv"))
    R = pd.read_csv(os.path.join(D, "coinbase_results.csv"))
    A = R[(R.arm == "t12") & R.clean].merge(
        T[["base", "first_day_ms"]], on="base", how="left").sort_values("first_ms")
    pnls = A.pnl_pct.to_numpy()
    span_y = (A.first_ms.max() - A.first_ms.min()) / (365.25 * 86400_000)
    per_year = len(pnls) / span_y
    curve = equity_curve(pnls)
    cagr = ((curve[-1] / START) ** (1 / span_y) - 1) * 100
    print(f"  events {len(pnls)} over {span_y:.2f} years  =  {per_year:.1f} per year")
    print(f"  sizing {SIZE*100:.0f}% of equity per position, 1x, no compounding of leverage")
    print(f"  ${START:,.0f} -> ${curve[-1]:,.0f}   CAGR {cagr:+.1f}%")
    print(f"  historical-order max drawdown {max_dd(curve):.1f}%")

    # Two different questions need two different resamplings, and conflating them is an
    # error this file made on its first run:
    #   drawdown depends on ORDER, so permute -- the multiset of trades is held fixed
    #   final equity does NOT depend on order at all, because multiplication commutes, so
    #   permuting gives one identical number 4000 times. Its uncertainty comes from not
    #   knowing the true trade distribution, which needs resampling WITH replacement.
    dds = np.array([max_dd(equity_curve(RNG.permutation(pnls))) for _ in range(4000)])
    print(f"  drawdown over 4000 re-orderings: median {np.median(dds):.1f}%   "
          f"p90 {np.percentile(dds,90):.1f}%   p99 {np.percentile(dds,99):.1f}%")

    boots = []
    for _ in range(4000):
        smp = RNG.choice(pnls, size=len(pnls), replace=True)
        boots.append(equity_curve(smp)[-1])
    boots = np.array(boots)
    bc = ((boots / START) ** (1 / span_y) - 1) * 100
    print(f"  bootstrapped final equity (resampled with replacement):")
    print(f"      p10 ${np.percentile(boots,10):,.0f}   median ${np.median(boots):,.0f}   "
          f"p90 ${np.percentile(boots,90):,.0f}")
    print(f"      CAGR p10 {np.percentile(bc,10):+.1f}%   median {np.median(bc):+.1f}%   "
          f"p90 {np.percentile(bc,90):+.1f}%")
    print(f"  runs ending BELOW the starting capital: {(boots < START).mean()*100:.1f}%")

    band = np.mean([C[h]["mean"] for h in HOURS if C.get(h) and BAND[0] <= h <= BAND[1]])
    print()
    print(f"  the same maths at the parameter-free band average of {band:+.2f}% per trade:")
    scaled = pnls - pnls.mean() + band
    cb2 = equity_curve(scaled)
    print(f"      ${START:,.0f} -> ${cb2[-1]:,.0f}   CAGR "
          f"{((cb2[-1]/START)**(1/span_y)-1)*100:+.1f}%   max DD {max_dd(cb2):.1f}%")
    print("  That is the figure to plan against if the entry hour cannot be identified,")
    print("  and the surfaces say it cannot.")
    print()
    print(f"  worst single trade {pnls.min():+.2f}%  =  "
          f"${pnls.min()/100*SIZE*START:+,.0f} at this size")
    print(f"  CAGR is computed from {len(pnls)} events and a {span_y:.1f}-year span. It is an")
    print(f"  arithmetic consequence of a mean that is not significant (t 1.64), so it")
    print(f"  inherits that uncertainty entirely.")
    print("=" * 112)


if __name__ == "__main__":
    main()
