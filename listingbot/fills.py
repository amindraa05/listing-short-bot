"""Honest fills: walk the real order book instead of assuming a price.

This is the whole reason the forward test is worth running. The backtest assumed a flat
0.3% spread because historical new-listing spreads are published nowhere, and that
assumption was named as its most fragile input — at 1% the edge lost its bar. A testnet
would not fix it, because testnet books are synthetic and thin.

What this module does instead: at the moment of a decision it fetches the live L2 book
and consumes it level by level until the intended notional is filled, then reports the
volume-weighted price actually achieved. Slippage stops being a parameter and becomes a
measurement.

A short sells into the BIDS to open and buys from the ASKS to close.
"""
from . import config as C
from . import venues


def walk(levels, notional_usdt):
    """Consume price levels until `notional_usdt` is filled.

    levels: [(price, size_in_contracts)] best-first.
    Returns dict with the achieved VWAP, or None if the book cannot fill the size.
    Size on Gate USDT perps is in contracts; notional per contract is
    price * quanto_multiplier, applied by the caller via `contract_value`.
    """
    filled_value = 0.0
    weighted = 0.0
    consumed = 0
    for px, size in levels:
        if px <= 0 or size <= 0:
            continue
        avail = px * size
        take = min(avail, notional_usdt - filled_value)
        if take <= 0:
            break
        weighted += px * take
        filled_value += take
        consumed += 1
        if filled_value >= notional_usdt - 1e-9:
            break
    if filled_value <= 0:
        return None
    return {"vwap": weighted / filled_value,
            "filled_usdt": filled_value,
            "levels_consumed": consumed,
            "complete": filled_value >= notional_usdt - 1e-6}


def book_depth_usdt(levels):
    return sum(px * sz for px, sz in levels if px > 0 and sz > 0)


def quote(contract, side, notional_usdt):
    """Price a paper fill against the live book.

    side 'sell' opens the short (consumes bids); 'buy' closes it (consumes asks).
    Returns a dict recording everything needed to audit the fill later, or None with a
    reason if the book is too thin to be believable.
    """
    ob = venues.gate_order_book(contract, limit=50)
    if not ob:
        return None, "no order book"
    bids, asks = ob["bids"], ob["asks"]
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 1e4 if mid > 0 else None

    levels = bids if side == "sell" else asks
    depth = book_depth_usdt(levels)
    if depth < max(C.MIN_BOOK_NOTIONAL_USDT, notional_usdt):
        return None, (f"book too thin: {depth:.0f} USDT on the {side} side, "
                      f"need {notional_usdt:.0f}")

    w = walk(levels, notional_usdt)
    if not w or not w["complete"]:
        return None, "book could not fill the size"

    # signed so that positive slippage always means "worse than mid"
    slip_bps = ((mid - w["vwap"]) / mid * 1e4 if side == "sell"
                else (w["vwap"] - mid) / mid * 1e4)
    fee_usdt = w["filled_usdt"] * C.GATE_TAKER_FEE
    return {
        "side": side,
        "vwap": w["vwap"],
        "mid": mid,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": spread_bps,
        "slippage_bps": slip_bps,
        "levels_consumed": w["levels_consumed"],
        "notional_usdt": w["filled_usdt"],
        "fee_usdt": fee_usdt,
        "book_depth_usdt": depth,
    }, None


def funding_accrued(contract, entry_ms, exit_ms):
    """Funding a SHORT collects or pays between two timestamps.

    Sign convention: a positive Gate funding rate means longs pay shorts, so a short
    RECEIVES it. Returned as a fraction of notional, positive = credit to the short.
    """
    hist = venues.gate_funding_history(contract, limit=200)
    if not hist:
        return 0.0, 0
    total, n = 0.0, 0
    for ts, rate in hist:
        ms = ts * 1000
        if entry_ms < ms <= exit_ms:
            total += rate
            n += 1
    return total, n
