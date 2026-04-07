import requests
import config

# OKX symbol format: "BTC-USDT" | Bybit: "BTCUSDT"


def get_spot_price(symbol: str) -> float | None:
    """
    Fetch current price for symbol (e.g. "BTC", "ETH", "SOL").
    Tries OKX first, falls back to Bybit.
    Returns float or None on total failure.
    """
    # OKX
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": f"{symbol}-USDT"},
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return float(r.json()["data"][0]["last"])
    except Exception:
        pass

    # Bybit fallback
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot", "symbol": f"{symbol}USDT"},
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return float(r.json()["result"]["list"][0]["lastPrice"])
    except Exception:
        return None


def get_momentum(symbol: str, lookback: int = None) -> str:
    """
    Fetch 1-min candles and count directional candles.
    Returns "UP", "DOWN", or "UNCLEAR".
    Uses config.MOMENTUM_CANDLES and config.MOMENTUM_THRESHOLD.
    """
    if lookback is None:
        lookback = config.MOMENTUM_CANDLES

    candles = None

    # OKX — returns [ts, open, high, low, close, vol, ...], newest first
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": f"{symbol}-USDT", "bar": "1m", "limit": str(lookback + 1)},
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        # OKX returns newest first; reverse to get oldest→newest
        candles = [(float(c[1]), float(c[4])) for c in reversed(data)]  # (open, close)
    except Exception:
        pass

    # Bybit fallback — returns [startTime, open, high, low, close, volume, turnover], newest first
    if not candles:
        try:
            r = requests.get(
                "https://api.bybit.com/v5/market/kline",
                params={
                    "category": "spot",
                    "symbol": f"{symbol}USDT",
                    "interval": "1",
                    "limit": str(lookback + 1),
                },
                timeout=config.REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()["result"]["list"]
            candles = [(float(c[1]), float(c[4])) for c in reversed(data)]
        except Exception:
            return "UNCLEAR"

    if len(candles) < lookback:
        return "UNCLEAR"

    # Use last `lookback` candles
    recent = candles[-lookback:]
    green = sum(1 for o, c in recent if c > o)
    red = lookback - green

    threshold = config.MOMENTUM_THRESHOLD
    if green >= threshold:
        return "UP"
    if red >= threshold:
        return "DOWN"
    return "UNCLEAR"
