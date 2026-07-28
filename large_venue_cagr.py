"""CAGR, drawdown and concurrency on the pooled large-venue sample.

This is the deployable version of the question: an account that trades BOTH Coinbase and Upbit
listings, chronologically, at the frozen T+12h. Pooling matters for more than sample size —
the two venues list independently, so positions overlap, and overlapping positions at a fixed
percentage each mean the account can be far more exposed than the sizing number suggests.
Concurrency is therefore measured rather than assumed away.

Reported at both sizing conventions in use: 30% (what the research dashboard shows) and 20%
(what the live paper bot actually runs), plus the parameter-free band-average variant, because
the entry-hour surfaces disagree across venues and the hour is not identifiable.

Run:  python large_venue_cagr.py
"""
import json
import math
import os

import numpy as np
import pandas as pd

D = r"C:\CLAUDECODE\listings\data"
START = 1000.0
HOLD_H = 72
RNG = np.random.default_rng(20260728)
BAND_MEAN = 1.18          # parameter-free band average measured on clean Coinbase


def load():
    C = pd.read_csv(os.path.join(D, "coinbase_results.csv"))
    K = pd.read_csv(os.path.join(D, "korea_results.csv"))
    c = C[(C.arm == "t12") & C.clean].copy()
    c["venue"] = "coinbase"
    c["ts"] = c.first_ms
    k = K[(K.arm == "t12") & K.clean].copy()
    k["venue"] = "upbit"
    k["ts"] = k.anchor_ms
    cols = ["venue", "base", "ts", "pnl_pct", "reason", "mae_pct"]
    return pd.concat([c[cols], k[cols]]).sort_values("ts").reset_index(drop=True)


def curve(pnls, size):
    eq, out = START, [START]
    for x in pnls:
        eq = max(eq * (1 + size * x / 100.0), 1e-9)
        out.append(eq)
    return np.array(out)


def max_dd(c):
    peak = np.maximum.accumulate(c)
    return float(np.max((peak - c) / peak) * 100)


def report(label, pnls, span_y, size):
    c = curve(pnls, size)
    cagr = ((c[-1] / START) ** (1 / span_y) - 1) * 100
    dds = np.array([max_dd(curve(RNG.permutation(pnls), size)) for _ in range(3000)])
    boots = np.array([curve(RNG.choice(pnls, len(pnls), replace=True), size)[-1]
                      for _ in range(3000)])
    bc = ((boots / START) ** (1 / span_y) - 1) * 100
    print(f"  {label}")
    print(f"      ${START:,.0f} -> ${c[-1]:,.0f}   CAGR {cagr:+.1f}%   "
          f"max DD (historical order) {max_dd(c):.1f}%")
    print(f"      DD over 3000 re-orderings: median {np.median(dds):.1f}%  "
          f"p90 {np.percentile(dds,90):.1f}%  p99 {np.percentile(dds,99):.1f}%")
    print(f"      bootstrapped CAGR: p10 {np.percentile(bc,10):+.1f}%  "
          f"median {np.median(bc):+.1f}%  p90 {np.percentile(bc,90):+.1f}%")
    print(f"      resamples ending below the starting capital: "
          f"{(boots < START).mean()*100:.1f}%")
    return {"final": float(c[-1]), "cagr": cagr, "dd_hist": max_dd(c),
            "dd_p90": float(np.percentile(dds, 90)),
            "cagr_p10": float(np.percentile(bc, 10)),
            "cagr_p90": float(np.percentile(bc, 90)),
            "below_start_pct": float((boots < START).mean() * 100)}


def main():
    T = load()
    span_y = (T.ts.max() - T.ts.min()) / (365.25 * 86400_000)
    per_year = len(T) / span_y
    p = T.pnl_pct.to_numpy()

    print("=" * 112)
    print("  POOLED LARGE-VENUE ACCOUNT — Coinbase + Upbit listings, frozen T+12h")
    print("=" * 112)
    print(f"  events {len(T)}  ({int((T.venue=='coinbase').sum())} Coinbase, "
          f"{int((T.venue=='upbit').sum())} Upbit)")
    print(f"  span {span_y:.2f} years  =  {per_year:.1f} events per year")
    print(f"  mean {p.mean():+.2f}%  median {np.median(p):+.2f}%  "
          f"win {(p>0).mean()*100:.1f}%  "
          f"t {p.mean()/(p.std(ddof=1)/math.sqrt(len(p))):+.2f}")

    print("\n" + "-" * 112)
    print("  CONCURRENCY — the two venues list independently, so positions overlap")
    print("-" * 112)
    starts = T.ts.to_numpy()
    ends = starts + HOLD_H * 3600_000
    conc = [int(((starts <= s) & (ends > s)).sum()) for s in starts]
    conc = np.array(conc)
    print(f"  positions open at once: median {int(np.median(conc))}  "
          f"p90 {int(np.percentile(conc,90))}  max {conc.max()}")
    for size in (0.20, 0.30):
        print(f"  at {size*100:.0f}% per position, peak gross exposure would reach "
              f"{conc.max()*size*100:.0f}% of the account")
    print("  This is the figure a fixed-percentage sizing rule hides. An account running")
    print("  both venues needs either a cap on concurrent positions or a smaller per-trade")
    print("  size; the CAGR figures below assume sequential compounding and therefore")
    print("  UNDERSTATE both the return and the risk of the overlapping reality.")

    print("\n" + "-" * 112)
    print("  AT THE FROZEN T+12h")
    print("-" * 112)
    out = {}
    out["30"] = report("30% per position (the research dashboard's convention)",
                       p, span_y, 0.30)
    print()
    out["20"] = report("20% per position (what the live paper bot runs)", p, span_y, 0.20)

    print("\n" + "-" * 112)
    print(f"  AT THE PARAMETER-FREE BAND AVERAGE ({BAND_MEAN:+.2f}% per trade)")
    print("-" * 112)
    print("  The entry-hour surfaces on the two large venues anti-correlate at r = -0.685, so")
    print("  the hour is not identifiable. This rescales the same trades to the unweighted")
    print("  mean across T+6h..T+30h, which has no parameter fitted to it.")
    scaled = p - p.mean() + BAND_MEAN
    out["band30"] = report("30% per position, band average", scaled, span_y, 0.30)
    print()
    out["band20"] = report("20% per position, band average", scaled, span_y, 0.20)

    print("\n" + "-" * 112)
    print("  PER VENUE, for reference")
    print("-" * 112)
    for v in ("coinbase", "upbit"):
        s = T[T.venue == v]
        sy = (s.ts.max() - s.ts.min()) / (365.25 * 86400_000)
        c = curve(s.pnl_pct.to_numpy(), 0.30)
        print(f"  {v:9s} n {len(s):>3d}  {sy:.2f}y  {len(s)/sy:>4.1f} events/yr  "
              f"${c[-1]:>7,.0f}  CAGR {((c[-1]/START)**(1/sy)-1)*100:+6.1f}%  "
              f"max DD {max_dd(c):>4.1f}%")

    print("\n" + "=" * 112)
    print("  WHAT THE HEADLINE NUMBER IS")
    print("=" * 112)
    print(f"  At 30% sizing and the frozen hour: CAGR {out['30']['cagr']:+.1f}%, "
          f"p90 drawdown {out['30']['dd_p90']:.1f}%.")
    print(f"  Bootstrapped, that CAGR runs {out['30']['cagr_p10']:+.1f}% to "
          f"{out['30']['cagr_p90']:+.1f}%, with {out['30']['below_start_pct']:.1f}% of")
    print("  resamples losing money outright.")
    print(f"  If the entry hour is arbitrary -- and the surfaces say it is -- the same")
    print(f"  trades give CAGR {out['band30']['cagr']:+.1f}% instead.")
    print("  Every figure here is historical. None of it is the forward test.")

    with open(os.path.join(D, "large_venue_cagr.json"), "w") as f:
        json.dump({"n": len(T), "span_years": span_y, "per_year": per_year,
                   "mean": float(p.mean()), "median": float(np.median(p)),
                   "win": float((p > 0).mean() * 100),
                   "t": float(p.mean() / (p.std(ddof=1) / math.sqrt(len(p)))),
                   "concurrency_max": int(conc.max()),
                   "concurrency_p90": int(np.percentile(conc, 90)),
                   "band_mean": BAND_MEAN, **out}, f, indent=1)
    print("=" * 112)


if __name__ == "__main__":
    main()
