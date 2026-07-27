"""Venue clients. Standard library only — no pip, no dependency risk on a host that
also runs the operator's live trading.

Every function is read-only. This module cannot place an order; there is no signing
code and no API key anywhere in the project. The forward test is paper, and the code
is written so that it could not become live by accident.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config as C


def _get(url, timeout=None, retries=None):
    timeout = timeout or C.HTTP_TIMEOUT
    retries = retries or C.HTTP_RETRIES
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 4xx other than rate limiting means the resource genuinely is not there
            if e.code in (400, 404, 422):
                return None
            last = f"HTTP {e.code}"
            time.sleep(1.0 * (attempt + 1))
        except Exception as e:                                  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url} ({last})")


# --------------------------------------------------------------- Binance spot
def binance_usdt_symbols():
    """{symbol: baseAsset} for every USDT pair currently trading."""
    d = _get(f"{C.BINANCE_SPOT}/exchangeInfo")
    if not d:
        return {}
    return {s["symbol"]: s["baseAsset"] for s in d.get("symbols", [])
            if s.get("quoteAsset") == C.QUOTE_ASSET and s.get("status") == "TRADING"}


def binance_first_hour_ms(symbol):
    """Open time of the first 1h candle — the real first traded hour.

    Using the first DAILY candle instead gives midnight of the listing day, which was
    wrong by more than six hours for 112 of 116 events in the backtest and randomised
    the entry anchor. That bug is the reason this function exists.
    """
    k = _get(f"{C.BINANCE_SPOT}/klines?symbol={symbol}&interval=1h&startTime=0&limit=1")
    return int(k[0][0]) if k else None


# ---------------------------------------------------------------------- Gate
def gate_contracts():
    """[{name, create_time_ms, quanto_multiplier, ...}] for USDT perps."""
    d = _get(f"{C.GATE_FUTURES}/contracts")
    if not d:
        return []
    out = []
    for c in d:
        ct = c.get("create_time")
        out.append({
            "venue": "gate",
            "symbol": c.get("name"),
            "base": (c.get("name") or "").split("_")[0].upper(),
            "launch_ms": int(float(ct) * 1000) if ct else None,
            "quanto_multiplier": float(c.get("quanto_multiplier") or 1),
            "order_size_min": float(c.get("order_size_min") or 1),
            "mark_price": float(c.get("mark_price") or 0) or None,
            "funding_rate": (float(c["funding_rate"])
                             if c.get("funding_rate") not in (None, "") else None),
            "funding_interval": int(c.get("funding_interval") or 28800),
        })
    return out


def gate_order_book(contract, limit=50):
    """L2 book. Returns {'bids': [(px, size)], 'asks': [(px, size)]} best-first."""
    d = _get(f"{C.GATE_FUTURES}/order_book?contract={contract}&limit={limit}")
    if not d:
        return None

    def side(rows):
        out = []
        for r in rows or []:
            try:
                out.append((float(r["p"]), float(r["s"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    bids, asks = side(d.get("bids")), side(d.get("asks"))
    if not bids or not asks:
        return None
    return {"bids": bids, "asks": asks}


def gate_funding_history(contract, limit=200):
    """[(timestamp_s, rate)] most recent first, as Gate returns it."""
    d = _get(f"{C.GATE_FUTURES}/funding_rate?contract={contract}&limit={limit}")
    if not d:
        return []
    out = []
    for r in d:
        try:
            out.append((int(r["t"]), float(r["r"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def gate_ticker(contract):
    d = _get(f"{C.GATE_FUTURES}/tickers?contract={contract}")
    if not d:
        return None
    t = d[0] if isinstance(d, list) and d else None
    if not t:
        return None
    return {"last": float(t.get("last") or 0) or None,
            "mark": float(t.get("mark_price") or 0) or None,
            "funding_rate": (float(t["funding_rate"])
                             if t.get("funding_rate") not in (None, "") else None)}


# ----------------------------------------------------------------- OKX, KuCoin
def okx_swaps():
    d = _get(f"{C.OKX_PUBLIC}/instruments?instType=SWAP")
    if not d or not d.get("data"):
        return []
    out = []
    for c in d["data"]:
        if c.get("settleCcy") != C.QUOTE_ASSET:
            continue
        base = (c.get("ctValCcy") or c.get("baseCcy") or "").upper()
        lt = c.get("listTime")
        out.append({"venue": "okx", "symbol": c.get("instId"), "base": base,
                    "launch_ms": int(lt) if lt else None})
    return out


def kucoin_contracts():
    d = _get(f"{C.KUCOIN_FUTURES}/contracts/active")
    if not d or not d.get("data"):
        return []
    out = []
    for c in d["data"]:
        if c.get("quoteCurrency") != C.QUOTE_ASSET:
            continue
        out.append({"venue": "kucoin", "symbol": c.get("symbol"),
                    "base": (c.get("baseCurrency") or "").upper(),
                    "launch_ms": c.get("firstOpenDate")})
    return out


def perp_index():
    """base -> earliest known perp across reachable venues.

    Binance-futures, Bybit, MEXC and Bitget were unreachable from the research network.
    If they are reachable from this host they should be added, because MEXC in
    particular lists new perps fast and their absence UNDERCOUNTS shortability.
    """
    best = {}
    for fn in (gate_contracts, okx_swaps, kucoin_contracts):
        try:
            rows = fn()
        except Exception:                                       # noqa: BLE001
            continue
        for r in rows:
            b, ms = r.get("base"), r.get("launch_ms")
            if not b or not ms:
                continue
            if b not in best or ms < best[b]["launch_ms"]:
                best[b] = r
    return best
