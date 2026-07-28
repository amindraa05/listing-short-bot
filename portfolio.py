"""A real portfolio simulator: concurrency caps, per-token cooldown, three venues.

Everything reported before this used sequential compounding — one trade finishes, the next
begins. That is not how the strategy would run. Listings arrive when they arrive, the hold is
up to 72 hours, and positions overlap: up to 5 at once on Coinbase plus Upbit alone. Sequential
compounding therefore understates the return AND hides the exposure.

This walks the calendar instead. A signal arrives, and it is taken only if a slot is free and
the token is not already on cooldown; otherwise it is recorded as skipped. Size is a percentage
of equity AT THE MOMENT OF ENTRY, so concurrent positions genuinely share one account.

Binance is included as an option and always labelled, because the rule was built on that data.
Any figure including it is in-sample and is not evidence.

Run:  python portfolio.py
"""
import json
import math
import os

import numpy as np
import pandas as pd

D = r"C:\CLAUDECODE\listings\data"
START = 1000.0
RNG = np.random.default_rng(20260728)
COOLDOWN_D = 7            # do not re-short the same token within a week
BAND_MEAN = 1.18          # the parameter-free per-trade mean, hour not identifiable


def load(include_binance=False):
    """One row per signal: venue, token, entry ms, exit ms, net pct."""
    rows = []

    C = pd.read_csv(os.path.join(D, "coinbase_results.csv"))
    c = C[(C.arm == "t12") & C.clean]
    for _, r in c.iterrows():
        rows.append({"venue": "coinbase", "base": r.base, "entry": int(r.first_ms),
                     "hours": int(r.bars), "pnl": float(r.pnl_pct),
                     "in_sample": False})

    K = pd.read_csv(os.path.join(D, "korea_results.csv"))
    k = K[(K.arm == "t12") & K.clean]
    for _, r in k.iterrows():
        rows.append({"venue": "upbit", "base": r.base, "entry": int(r.anchor_ms),
                     "hours": int(r.bars), "pnl": float(r.pnl_pct),
                     "in_sample": False})

    if include_binance:
        B = json.load(open(os.path.join(D, "dashboard_data.json")))["trades"]
        for t in B:
            rows.append({"venue": "binance", "base": t["base"],
                         "entry": int(pd.Timestamp(t["date"], tz="UTC").timestamp() * 1000),
                         "hours": int(t["hours"]), "pnl": float(t["pnl"]),
                         "in_sample": True})

    T = pd.DataFrame(rows).sort_values("entry").reset_index(drop=True)
    T["exit"] = T.entry + T.hours * 3600_000
    return T


def simulate(T, cap, size, cooldown_d=COOLDOWN_D, rescale_to=None):
    """Walk the calendar. Returns the equity path, the trades taken, and what was skipped."""
    pnls = T.pnl.to_numpy(dtype=float)
    if rescale_to is not None:
        pnls = pnls - pnls.mean() + rescale_to

    eq = START
    open_pos = []                    # (exit_ms, notional, pnl_pct)
    last_seen = {}
    curve = [(int(T.entry.iloc[0]), eq)]
    taken, skip_cap, skip_cool = [], [], []

    for i in range(len(T)):
        r = T.iloc[i]
        now = int(r.entry)
        # settle anything that closed before this signal
        for p in [p for p in open_pos if p[0] <= now]:
            eq += p[1] * p[2] / 100.0
            open_pos.remove(p)
            curve.append((p[0], eq))
        if last_seen.get(r.base, -1e18) > now - cooldown_d * 86400_000:
            skip_cool.append(i)
            continue
        if len(open_pos) >= cap:
            skip_cap.append(i)
            continue
        notional = eq * size
        open_pos.append((int(r.exit), notional, float(pnls[i])))
        last_seen[r.base] = now
        taken.append(i)

    for p in sorted(open_pos, key=lambda x: x[0]):
        eq += p[1] * p[2] / 100.0
        curve.append((p[0], eq))

    c = np.array([x[1] for x in curve])
    return {"curve": c, "final": eq, "taken": taken,
            "skip_cap": skip_cap, "skip_cool": skip_cool}


def max_dd(c):
    peak = np.maximum.accumulate(c)
    return float(np.max((peak - c) / peak) * 100)


def peak_exposure(T, cap, size, taken):
    """Largest simultaneous notional as a share of equity, from the taken trades only."""
    S = T.iloc[taken]
    st, en = S.entry.to_numpy(), S.exit.to_numpy()
    return int(max(((st <= s) & (en > s)).sum() for s in st)) * size * 100


def summarise(label, T, cap, size, rescale=None, quiet=False):
    r = simulate(T, cap, size, rescale_to=rescale)
    span_y = (T.exit.max() - T.entry.min()) / (365.25 * 86400_000)
    cagr = ((r["final"] / START) ** (1 / span_y) - 1) * 100
    n = len(r["taken"])
    pe = peak_exposure(T, cap, size, r["taken"])
    if not quiet:
        print(f"  {label:38s} took {n:>3d}/{len(T):<3d}  "
              f"skipped {len(r['skip_cap']):>3d} cap /{len(r['skip_cool']):>2d} cooldown  "
              f"${r['final']:>7,.0f}  CAGR {cagr:>+7.1f}%  "
              f"DD {max_dd(r['curve']):>5.1f}%  peak exp {pe:>4.0f}%")
    return {"label": label, "cap": cap, "size": size, "n": n, "final": r["final"],
            "cagr": cagr, "dd": max_dd(r["curve"]), "peak_exposure": pe,
            "skipped_cap": len(r["skip_cap"]), "skipped_cool": len(r["skip_cool"]),
            "span_years": span_y}


def bootstrap_cagr(T, cap, size, iters=800):
    """Resample the P&L column with replacement, keep the calendar fixed."""
    span_y = (T.exit.max() - T.entry.min()) / (365.25 * 86400_000)
    base = T.pnl.to_numpy(dtype=float)
    out = []
    for _ in range(iters):
        S = T.copy()
        S["pnl"] = RNG.choice(base, len(base), replace=True)
        r = simulate(S, cap, size)
        out.append(((r["final"] / START) ** (1 / span_y) - 1) * 100)
    return np.array(out)


def main():
    L = load(include_binance=False)
    print("=" * 118)
    print("  PART 1 — LARGE-VENUE PORTFOLIO (Coinbase + Upbit), calendar-accurate")
    print("=" * 118)
    print(f"  {len(L)} signals over "
          f"{(L.exit.max()-L.entry.min())/(365.25*86400_000):.2f} years")
    dupes = L.base.duplicated().sum()
    print(f"  the same token signalled by both venues: {dupes} times  "
          f"(cooldown {COOLDOWN_D}d applies)")
    print(f"  sequential compounding, for comparison, gave CAGR +76.2% at 30%\n")

    print(f"  {'configuration':38s} {'trades taken':>14}  {'skipped':>22}  "
          f"{'final':>8} {'CAGR':>13} {'DD':>7} {'peak exp':>9}")
    res = []
    for cap in (1, 2, 3, 5, 99):
        for size in (0.20, 0.30):
            tag = f"cap {cap if cap < 99 else 'none'} @ {size*100:.0f}%"
            res.append(summarise(tag, L, cap, size))
        print()

    print("=" * 118)
    print("  THE ANSWER TO 'CAP AT 2'")
    print("=" * 118)
    for size in (0.20, 0.30, 0.40, 0.50):
        r = summarise(f"cap 2 @ {size*100:.0f}%", L, 2, size)
    bc = bootstrap_cagr(L, 2, 0.30)
    print(f"\n  cap 2 at 30%, bootstrapped CAGR: p10 {np.percentile(bc,10):+.1f}%  "
          f"median {np.median(bc):+.1f}%  p90 {np.percentile(bc,90):+.1f}%")
    print(f"  resamples losing money: {(bc < 0).mean()*100:.1f}%")
    b2 = summarise("cap 2 @ 30% band avg", L, 2, 0.30, rescale=BAND_MEAN, quiet=True)
    print(f"  at the parameter-free {BAND_MEAN:+.2f}% per trade instead: "
          f"CAGR {b2['cagr']:+.1f}%, DD {b2['dd']:.1f}%")

    # ---------------------------------------------------------------- part 2
    A = load(include_binance=True)
    print("\n" + "=" * 118)
    print("  PART 2 — ALL THREE VENUES. Binance is IN-SAMPLE, so this is not evidence")
    print("=" * 118)
    print(f"  {len(A)} signals: "
          + ", ".join(f"{v} {int((A.venue==v).sum())}" for v in A.venue.unique()))
    print(f"  span {(A.exit.max()-A.entry.min())/(365.25*86400_000):.2f} years  =  "
          f"{len(A)/((A.exit.max()-A.entry.min())/(365.25*86400_000)):.0f} signals/year")
    dup = A[A.base.duplicated(keep=False)].sort_values(["base", "entry"])
    same = dup.groupby("base").entry.apply(lambda x: (x.diff().dropna() / 86400_000).min())
    print(f"  tokens signalled by more than one venue: {A.base.duplicated().sum()}")
    if len(same):
        print(f"  gap between duplicate signals: median {same.median():.0f}d  "
              f"min {same.min():.0f}d  under {COOLDOWN_D}d: {int((same<COOLDOWN_D).sum())}")
    print()
    print(f"  {'configuration':38s} {'trades taken':>14}  {'skipped':>22}  "
          f"{'final':>8} {'CAGR':>13} {'DD':>7} {'peak exp':>9}")
    for cap in (1, 2, 3, 5):
        for size in (0.20, 0.30):
            summarise(f"3 venues, cap {cap} @ {size*100:.0f}%", A, cap, size)
        print()

    print("=" * 118)
    print("  WHAT THE CAP COSTS, AND WHAT IT BUYS")
    print("=" * 118)
    print(f"  {'cap':>5}{'trades':>8}{'skipped':>9}{'CAGR@30%':>11}{'DD':>7}"
          f"{'peak exp':>10}{'CAGR per unit of DD':>22}")
    for cap in (1, 2, 3, 5, 99):
        r = summarise("", L, cap, 0.30, quiet=True)
        ratio = r["cagr"] / r["dd"] if r["dd"] > 0 else float("nan")
        print(f"  {cap if cap<99 else 'none':>5}{r['n']:>8}{r['skipped_cap']:>9}"
              f"{r['cagr']:>+10.1f}%{r['dd']:>6.1f}%{r['peak_exposure']:>9.0f}%"
              f"{ratio:>22.2f}")

    with open(os.path.join(D, "portfolio.json"), "w") as f:
        json.dump({"large_venue": res, "cooldown_days": COOLDOWN_D,
                   "band_mean": BAND_MEAN}, f, indent=1)
    print("=" * 118)


if __name__ == "__main__":
    main()
