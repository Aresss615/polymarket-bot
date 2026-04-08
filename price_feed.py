import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import requests

import config

# OKX symbol format: BTC-USDT | Bybit: BTCUSDT

_RTDS_SYMBOL_FILTERS = {
    "BTC": "btcusdt",
    "ETH": "ethusdt",
    "SOL": "solusdt",
    "XRP": "xrpusdt",
}
_RTDS_FILTER_TO_SYMBOL = {v: k for k, v in _RTDS_SYMBOL_FILTERS.items()}
_STREAM_POINTS: dict[str, deque[tuple[int, float]]] = defaultdict(deque)
_STREAM_LOCK = threading.Lock()
_STREAM_STOP = threading.Event()
_STREAM_THREAD: threading.Thread | None = None
_REQUESTED_STREAM_SYMBOLS: set[str] = set()
_STREAM_IMPORT_ERROR: str | None = None


def _buffer_max_seconds() -> int:
    return int(getattr(config, "CRYPTO_WINDOW_BUFFER_MINUTES", 10) * 60)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_millis(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def clear_price_buffers() -> None:
    with _STREAM_LOCK:
        _STREAM_POINTS.clear()


def record_price_sample(symbol: str, price: float, timestamp_ms: int | None = None) -> None:
    symbol = (symbol or "").upper()
    if not symbol:
        return
    ts_ms = int(timestamp_ms or (_utc_now().timestamp() * 1000))
    with _STREAM_LOCK:
        points = _STREAM_POINTS[symbol]
        points.append((ts_ms, float(price)))
        cutoff = ts_ms - (_buffer_max_seconds() * 1000)
        while points and points[0][0] < cutoff:
            points.popleft()


def register_symbols(symbols: list[str] | set[str] | tuple[str, ...]) -> None:
    for symbol in symbols:
        if symbol:
            _REQUESTED_STREAM_SYMBOLS.add(str(symbol).upper())


def _stream_filters() -> str:
    filters = []
    for symbol in sorted(_REQUESTED_STREAM_SYMBOLS):
        value = _RTDS_SYMBOL_FILTERS.get(symbol)
        if value:
            filters.append(value)
    return ",".join(filters)


def start_price_stream(symbols: list[str] | None = None) -> bool:
    global _STREAM_THREAD, _STREAM_IMPORT_ERROR

    if not getattr(config, "CRYPTO_UNDERLYING_STREAM_ENABLED", True):
        return False

    if symbols:
        register_symbols(symbols)
    else:
        register_symbols(_RTDS_SYMBOL_FILTERS.keys())

    if not _stream_filters():
        return False

    try:
        import websocket  # type: ignore
    except Exception as exc:
        _STREAM_IMPORT_ERROR = str(exc)
        return False

    if _STREAM_THREAD and _STREAM_THREAD.is_alive():
        return True

    _STREAM_STOP.clear()
    _STREAM_THREAD = threading.Thread(target=_stream_loop, name="polymarket-rtds", daemon=True)
    _STREAM_THREAD.start()
    return True


def stop_price_stream() -> None:
    _STREAM_STOP.set()


def get_stream_status() -> str:
    if _STREAM_IMPORT_ERROR:
        return f"fallback_only ({_STREAM_IMPORT_ERROR})"
    if _STREAM_THREAD and _STREAM_THREAD.is_alive():
        return f"rtds:{','.join(sorted(_REQUESTED_STREAM_SYMBOLS)) or 'idle'}"
    return "fallback_only"


def _stream_loop() -> None:
    while not _STREAM_STOP.is_set():
        filters = _stream_filters()
        if not filters:
            time.sleep(1.0)
            continue

        try:
            import websocket  # type: ignore
        except Exception as exc:
            global _STREAM_IMPORT_ERROR
            _STREAM_IMPORT_ERROR = str(exc)
            return

        def _on_open(ws):
            ws.send(json.dumps({
                "action": "subscribe",
                "subscriptions": [
                    {
                        "topic": "crypto_prices",
                        "type": "update",
                        "filters": filters,
                    }
                ],
            }))

        def _on_message(_ws, message: str) -> None:
            try:
                payload = json.loads(message)
            except Exception:
                return
            if payload.get("topic") != "crypto_prices" or payload.get("type") != "update":
                return
            data = payload.get("payload") or {}
            rtds_symbol = str(data.get("symbol") or "").lower()
            symbol = _RTDS_FILTER_TO_SYMBOL.get(rtds_symbol)
            if not symbol:
                return
            value = data.get("value")
            timestamp_ms = data.get("timestamp") or payload.get("timestamp")
            try:
                record_price_sample(symbol, float(value), int(timestamp_ms) if timestamp_ms is not None else None)
            except Exception:
                return

        ws = websocket.WebSocketApp(
            config.POLYMARKET_RTDS_URL,
            on_open=_on_open,
            on_message=_on_message,
        )
        try:
            ws.run_forever(ping_interval=5, ping_timeout=2)
        except Exception:
            pass
        if not _STREAM_STOP.is_set():
            time.sleep(2.0)


def _get_recent_candle_bars(symbol: str, lookback: int) -> list[dict] | None:
    bars = None

    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": f"{symbol}-USDT", "bar": "1m", "limit": str(lookback + 2)},
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        bars = [
            {
                "ts": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
            }
            for c in reversed(data)
        ]
    except Exception:
        pass

    if not bars:
        try:
            r = requests.get(
                "https://api.bybit.com/v5/market/kline",
                params={
                    "category": "spot",
                    "symbol": f"{symbol}USDT",
                    "interval": "1",
                    "limit": str(lookback + 2),
                },
                timeout=config.REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()["result"]["list"]
            bars = [
                {
                    "ts": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                }
                for c in reversed(data)
            ]
        except Exception:
            return None

    return bars


def _get_recent_candles(symbol: str, lookback: int) -> list[tuple[float, float]] | None:
    bars = _get_recent_candle_bars(symbol, lookback)
    if not bars:
        return None
    return [(bar["open"], bar["close"]) for bar in bars]


def get_spot_price(symbol: str) -> float | None:
    """
    Fetch current price for symbol (e.g. BTC, ETH, SOL).
    Tries RTDS buffer first, then OKX, then Bybit.
    """
    symbol = (symbol or "").upper()
    with _STREAM_LOCK:
        points = _STREAM_POINTS.get(symbol)
        if points:
            return float(points[-1][1])

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
    if lookback is None:
        lookback = config.MOMENTUM_CANDLES

    candles = _get_recent_candles(symbol, lookback)
    if not candles or len(candles) < lookback:
        return "UNCLEAR"

    recent = candles[-lookback:]
    green = sum(1 for o, c in recent if c > o)
    red = sum(1 for o, c in recent if c < o)

    threshold = config.MOMENTUM_THRESHOLD
    if green >= threshold:
        return "UP"
    if red >= threshold:
        return "DOWN"
    return "UNCLEAR"


def get_net_move_pct(symbol: str, lookback: int = None) -> float | None:
    if lookback is None:
        lookback = config.MOMENTUM_CANDLES

    candles = _get_recent_candles(symbol, lookback)
    if not candles or len(candles) < lookback:
        return None

    recent = candles[-lookback:]
    first_open = recent[0][0]
    last_close = recent[-1][1]
    if first_open <= 0:
        return None
    return (last_close - first_open) / first_open


def get_last_candle_move_pct(symbol: str) -> float | None:
    candles = _get_recent_candles(symbol, 1)
    if not candles:
        return None

    open_price, close_price = candles[-1]
    if open_price <= 0:
        return None
    return (close_price - open_price) / open_price


def get_window_move_pct(symbol: str, minutes: int = 5) -> float | None:
    bars = _get_recent_candle_bars(symbol, minutes)
    if not bars or len(bars) < minutes:
        return None

    recent = bars[-minutes:]
    first_open = recent[0]["open"]
    last_close = recent[-1]["close"]
    if first_open <= 0:
        return None
    return (last_close - first_open) / first_open


def _nearest_price(points: list[tuple[int, float]], target_ms: int) -> float | None:
    if not points:
        return None

    before = [price for ts, price in points if ts <= target_ms]
    if before:
        return float(before[-1])

    first_ts, first_price = points[0]
    if abs(first_ts - target_ms) <= 15000:
        return float(first_price)
    return None


def _pct_move(start_price: float | None, end_price: float | None) -> float | None:
    if start_price in (None, 0) or end_price is None:
        return None
    return (float(end_price) - float(start_price)) / float(start_price)


def _classify_window_pattern(summary: dict) -> str:
    window_move = float(summary.get("window_move_pct") or 0.0)
    last30 = summary.get("last30_move_pct")
    last15 = summary.get("last15_move_pct")
    dist_high = summary.get("distance_from_high_pct")
    dist_low = summary.get("distance_from_low_pct")
    min_move = float(getattr(config, "WINDOW_MOVE_MIN", 0.0001))

    if abs(window_move) < min_move and abs(float(last30 or 0.0)) < min_move:
        return "chop"

    if last15 is not None and window_move * float(last15) < 0 and abs(float(last15)) >= (min_move / 2):
        return "reversal"
    if last30 is not None and window_move * float(last30) < 0 and abs(float(last30)) >= (min_move / 2):
        return "reversal"

    if dist_high is not None and dist_low is not None:
        if window_move > 0 and abs(float(dist_high)) <= min_move:
            return "breakout"
        if window_move < 0 and abs(float(dist_low)) <= min_move:
            return "breakout"

    return "continuation"


def _finalize_summary(summary: dict) -> dict | None:
    start_price = summary.get("window_start_price")
    current_price = summary.get("window_current_price")
    if start_price in (None, 0) or current_price is None:
        return None

    summary["window_move_pct"] = _pct_move(start_price, current_price)
    window_high = summary.get("window_high")
    window_low = summary.get("window_low")
    summary["distance_from_high_pct"] = _pct_move(window_high, current_price) if window_high else None
    summary["distance_from_low_pct"] = _pct_move(window_low, current_price) if window_low else None
    summary["pattern"] = _classify_window_pattern(summary)
    return summary


def _summarize_points(
    points: list[tuple[int, float]],
    window_start: datetime,
    current_time: datetime,
    data_source: str,
    completeness: str,
) -> dict | None:
    if not points:
        return None

    start_ms = _to_millis(window_start)
    now_ms = _to_millis(current_time)
    relevant = [(ts, price) for ts, price in points if start_ms - 15000 <= ts <= now_ms + 1000]
    if not relevant:
        return None

    start_price = _nearest_price(relevant, start_ms)
    current_price = _nearest_price(relevant, now_ms)
    if current_price is None:
        current_price = float(relevant[-1][1])

    in_window_prices = [price for ts, price in relevant if ts >= start_ms]
    if not in_window_prices:
        in_window_prices = [price for _ts, price in relevant]

    summary = {
        "window_start_price": start_price,
        "window_current_price": current_price,
        "window_high": max(in_window_prices) if in_window_prices else None,
        "window_low": min(in_window_prices) if in_window_prices else None,
        "last60_move_pct": _pct_move(_nearest_price(relevant, now_ms - 60000), current_price),
        "last30_move_pct": _pct_move(_nearest_price(relevant, now_ms - 30000), current_price),
        "last15_move_pct": _pct_move(_nearest_price(relevant, now_ms - 15000), current_price),
        "data_source": data_source,
        "completeness": completeness,
        "sample_count": len(relevant),
        "window_elapsed_seconds": max(0, int((current_time - window_start).total_seconds())),
    }
    return _finalize_summary(summary)


def _summarize_fallback(symbol: str, window_start: datetime, current_time: datetime) -> dict | None:
    lookback = max(int(getattr(config, "CRYPTO_WINDOW_BUFFER_MINUTES", 10)), 6)
    bars = _get_recent_candle_bars(symbol, lookback)
    if not bars:
        return None

    start_ms = _to_millis(window_start)
    recent = [bar for bar in bars if bar["ts"] >= start_ms - 60000]
    if not recent:
        recent = bars[-max(1, lookback // 2):]
    if not recent:
        return None

    current_price = get_spot_price(symbol) or recent[-1]["close"]
    latest_open = recent[-1]["open"] if recent else None
    summary = {
        "window_start_price": recent[0]["open"],
        "window_current_price": current_price,
        "window_high": max([bar["high"] for bar in recent] + [current_price]),
        "window_low": min([bar["low"] for bar in recent] + [current_price]),
        "last60_move_pct": _pct_move(latest_open, current_price) if latest_open else None,
        "last30_move_pct": None,
        "last15_move_pct": None,
        "data_source": "exchange_fallback",
        "completeness": "fallback",
        "sample_count": len(recent),
        "window_elapsed_seconds": max(0, int((current_time - window_start).total_seconds())),
    }
    return _finalize_summary(summary)


def get_window_summary(symbol: str, window_start: datetime, current_time: datetime | None = None) -> dict | None:
    symbol = (symbol or "").upper()
    current_time = current_time or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)

    with _STREAM_LOCK:
        points = list(_STREAM_POINTS.get(symbol, ()))

    stream_summary = None
    if points:
        stream_summary = _summarize_points(points, window_start, current_time, data_source="rtds", completeness="full")
        if stream_summary:
            first_ts = points[0][0]
            latest_ts = points[-1][0]
            if first_ts > (_to_millis(window_start) + 15000) or latest_ts < (_to_millis(current_time) - 5000):
                stream_summary["completeness"] = "partial"
                stream_summary["data_source"] = "partial"
                stream_summary["pattern"] = _classify_window_pattern(stream_summary)

    fallback_summary = _summarize_fallback(symbol, window_start, current_time)

    if stream_summary and stream_summary.get("completeness") == "full":
        return stream_summary
    if stream_summary and fallback_summary:
        merged = dict(fallback_summary)
        for key in (
            "window_current_price",
            "last60_move_pct",
            "last30_move_pct",
            "last15_move_pct",
            "sample_count",
        ):
            if stream_summary.get(key) is not None:
                merged[key] = stream_summary[key]
        if stream_summary.get("window_start_price") is not None:
            merged["window_start_price"] = stream_summary["window_start_price"]
        highs = [value for value in (stream_summary.get("window_high"), fallback_summary.get("window_high")) if value is not None]
        lows = [value for value in (stream_summary.get("window_low"), fallback_summary.get("window_low")) if value is not None]
        merged["window_high"] = max(highs) if highs else None
        merged["window_low"] = min(lows) if lows else None
        merged["data_source"] = "partial"
        merged["completeness"] = "partial"
        return _finalize_summary(merged)
    return fallback_summary or stream_summary
