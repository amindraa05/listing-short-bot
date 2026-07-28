"""Venue clients. Standard library only — no pip, no dependency risk on a host that
also runs the operator's live trading.

Every function is read-only. This module cannot place an order; there is no signing
code and no API key anywhere in the project. The forward test is paper, and the code
is written so that it could not become live by accident.
"""
import json
import time
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
# How far back a just-detected listing's first hour is searched for. The bot polls every
# five minutes, so a genuine new listing is always well inside this; the window exists to
# bound the request, not to find old listings.
LISTING_LOOKBACK_H = 72


# --------------------------------------------------------------------------- Coinbase
def coinbase_usd_products():
    """Online USD/USDC products, one entry per base currency, USD preferred."""
    d = _get(f"{C.COINBASE_EXCHANGE}/products")
    out = {}
    for x in (d or []):
        if (x.get("status") != "online" or x.get("trading_disabled")
                or x.get("quote_currency") not in ("USD", "USDC")):
            continue
        b = (x.get("base_currency") or "").upper()
        if not b:
            continue
        if b not in out or x["quote_currency"] == "USD":
            out[b] = x["id"]
    return out


def coinbase_first_hour_ms(product, lookback_h=LISTING_LOOKBACK_H):
    """First traded HOUR of a product the scan has just detected as NEW.

    Coinbase lists in the afternoon — measured median first hour 17:00 UTC — so a midnight
    anchor is wrong by most of a day, and on the historical run that mistake cost the
    T+12h arm 91 of 102 events.

    PRECONDITION: the caller has already established that this product is new, by diffing
    the product list. Given that, the earliest hourly candle inside a recent window IS the
    first traded hour. Without that precondition the answer would be meaningless, because
    Coinbase's candle endpoint returns the most RECENT window when no range is given — the
    first version of this function did exactly that and reported "300 days ago" as the
    listing hour for two unrelated products.

    Returns None rather than a guess when the earliest candle sits at the edge of the
    window, since then the true first hour may be older and cannot be distinguished.
    """
    now = int(time.time())
    start = now - lookback_h * 3600
    h = _get(f"{C.COINBASE_EXCHANGE}/products/{product}/candles?granularity=3600"
             f"&start={_iso(start)}&end={_iso(now)}")
    if not isinstance(h, list) or not h:
        return None
    first = min(int(x[0]) for x in h)
    if first <= start + 3600:          # touching the edge: cannot tell it is the first
        return None
    return first * 1000


# --------------------------------------------------------------------------- Upbit
def upbit_markets():
    """KRW and USDT markets, one per token, KRW preferred as the retail signal."""
    d = _get(f"{C.UPBIT}/market/all?isDetails=true")
    out = {}
    for x in (d or []):
        m = x.get("market", "")
        if not (m.startswith("KRW-") or m.startswith("USDT-")):
            continue
        b = m.split("-", 1)[1].upper()
        if b not in out or m.startswith("KRW-"):
            out[b] = m
    return out


def upbit_first_hour_ms(market, lookback_h=LISTING_LOOKBACK_H):
    """First traded HOUR on Upbit, for a market the scan has just detected as NEW.

    Upbit lists in the Korean afternoon, a measured median 7 hours past midnight UTC.
    Anchoring on midnight there manufactured a +5.91% result at t 5.76 in the historical
    run, which had to be withdrawn — the third midnight-anchor bug in this project.

    Same precondition and same refusal as the Coinbase version: Upbit's candle endpoints
    also return the most recent N candles when no range is given, so the earliest one is
    only the listing hour if the market really is new.
    """
    n = min(200, max(4, lookback_h))
    d = _get(f"{C.UPBIT}/candles/minutes/60?market={market}&count={n}")
    if not d:
        return None
    hrs = sorted(t for t in (_upbit_ts(x) for x in d) if t)
    if not hrs:
        return None
    edge = (time.time() - n * 3600) * 1000
    if hrs[0] <= edge + 3600_000:      # touching the edge: may not be the first hour
        return None
    return hrs[0]


def _upbit_ts(x):
    try:
        return int(time.mktime(time.strptime(
            x["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S"))) * 1000
    except (KeyError, TypeError, ValueError):
        return None


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))


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


def gate_hourly_volume(contract, hours=1):
    """Quote-denominated volume traded on the perp over the last `hours` full hours.

    The 'sum' field is quote volume; 'v' is contracts and would need the multiplier.
    Returns None rather than 0 when unavailable, so a caller can tell "no data" from
    "no trading" — the two justify opposite decisions.
    """
    d = _get(f"{C.GATE_FUTURES}/candlesticks?contract={contract}&interval=1h"
             f"&limit={hours + 1}")
    if not d:
        return None
    tot = 0.0
    got = 0
    for c in d[-(hours + 1):-1] or d[-1:]:
        try:
            tot += float(c.get("sum") or 0)
            got += 1
        except (TypeError, ValueError):
            continue
    return tot if got else None


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
