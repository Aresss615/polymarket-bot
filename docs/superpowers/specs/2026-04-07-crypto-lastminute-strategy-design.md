# Design: Last-Minute Crypto 5-Min Strategy

**Date:** 2026-04-07
**Status:** Approved for implementation
**Branch:** implement on top of `fix/market-filters-and-bankroll-accounting`

---

## Context / Problem

The bot was consistently losing on Polymarket's 5-minute crypto markets because:

1. **Wrong timing**: `main.py` woke up 1 minute *after* each 5-min boundary (`:01`, `:06`, `:11`) then targeted markets 3-10 minutes out. By the time bets were placed (~`:02-:03`), the market still had 4-9 minutes left — way too early, and subject to full reversal.
2. **Wrong strategy**: The LLM has zero informational edge on short-term BTC/ETH price direction. It's essentially a coin flip on 5-minute candles.
3. **User goal**: Bet close to resolution (roughly the last 1-2 minutes). Use real live price data + momentum, not LLM guessing.

---

## Approved Approach: Hybrid

- Detect 5-min (and other interval) crypto markets by slug pattern: `btc-updown-5m-*`, `eth-updown-5m-*`, etc.
- Route them through a new `price_feed.py` module (OKX + Bybit fallback) instead of LLM
- Fix cycle timing: **wake 90 seconds before** each 5-min boundary
- Long-horizon non-crypto markets continue through the existing LLM path unchanged

### Key decisions made during design
| Decision | Choice | Reason |
|---|---|---|
| Price feed | OKX primary, Bybit fallback | Binance banned in Philippines; both OKX/Bybit accessible and have free kline API |
| Wake timing | 90s before boundary | At ~20s many markets are already priced 0/100; 90s keeps uncertainty while still being close to resolution |
| Bet trigger | Price vs strike AND momentum (both must agree) | Double confirmation → higher win rate |
| Bet sizing | Kelly at 5% of bankroll, no hard $ cap | Scales with bankroll as wins accumulate |
| Max bets/cycle | 3 | Prevents over-concentration in one cycle |
| Price buffer | 0.2% gap vs strike | Avoids noise trades when price is right on the strike |

---

## Data Flow

```
BEFORE (broken):
  wake at :01 → fetch (3-10 min window) → LLM for ALL → engine → log

AFTER (fixed):
  wake at :03:30 → fetch (5-120s window) → split by market type:
    ├── slug matches *-updown-Xm-* → price_feed.py → _analyze_crypto_5min() → engine
    └── non-crypto / long-horizon  → analyzer.py (LLM) → engine
  → merge results → log
```

---

## New File: `price_feed.py`

Two public functions used by `analyzer.py`:

```python
def get_spot_price(symbol: str) -> float | None:
    """
    Fetch current price. Tries OKX first, falls back to Bybit.
    symbol: "BTC", "ETH", "SOL", etc. (asset name without USDT)

    OKX:   GET https://www.okx.com/api/v5/market/ticker?instId={symbol}-USDT
           → response["data"][0]["last"]
    Bybit: GET https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}USDT
           → response["result"]["list"][0]["lastPrice"]

    Returns float or None on total failure.
    ~100-200ms latency. No API key required.
    """

def get_momentum(symbol: str, lookback: int = 4) -> str:
    """
    Fetch last (lookback+1) 1-minute candles and count directional candles.
    Tries OKX first, falls back to Bybit.

    OKX:   GET https://www.okx.com/api/v5/market/candles?instId={symbol}-USDT&bar=1m&limit=5
           → array of [ts, open, high, low, close, vol, ...]
    Bybit: GET https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}USDT&interval=1&limit=5

    Count green candles (close > open) among last `lookback` candles.
    Returns:
      "UP"      if >= MOMENTUM_THRESHOLD green  (default: 3/4)
      "DOWN"    if >= MOMENTUM_THRESHOLD red
      "UNCLEAR" otherwise → caller should skip
    """
```

---

## Modified: `config.py`

Add these constants (all existing constants remain unchanged):

```python
# === Crypto 5-Min Last-Minute Strategy ===
CRYPTO_5MIN_ENABLED = True          # Enable price-feed strategy for 5-min crypto markets
SECONDS_BEFORE_CLOSE = 90           # Wake up N seconds before each 5-min boundary
MIN_SECONDS_TO_CLOSE = 5            # Reject if <5s left (too late)
MAX_SECONDS_TO_CLOSE = 120          # Only target markets closing within 120s
MOMENTUM_CANDLES = 4                # Candles to evaluate for momentum (last 4 × 1-min)
MOMENTUM_THRESHOLD = 3              # Min candles in same direction to trigger bet
CRYPTO_PRICE_BUFFER = 0.002         # 0.2% minimum price-vs-strike gap (filters noise)
CRYPTO_KELLY_FRACTION = 0.05        # 5% of bankroll per crypto bet (scales with balance)
CRYPTO_MAX_BETS_PER_CYCLE = 3       # Max crypto bets per cycle
```

---

## Modified: `main.py`

### Replace `seconds_until_next_cycle()`

```python
def seconds_until_next_cycle() -> float:
    """Wake up SECONDS_BEFORE_CLOSE seconds before the next 5-min boundary."""
    now = datetime.datetime.now()
    remainder = now.minute % 5
    minutes_to_boundary = 5 - remainder if remainder != 0 else 5
    boundary = now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=minutes_to_boundary)
    wake_time = boundary - datetime.timedelta(seconds=config.SECONDS_BEFORE_CLOSE)
    delta = (wake_time - datetime.datetime.now()).total_seconds()
    while delta < 10:  # need at least 10s to complete a cycle
        boundary += datetime.timedelta(minutes=5)
        wake_time = boundary - datetime.timedelta(seconds=config.SECONDS_BEFORE_CLOSE)
        delta = (wake_time - datetime.datetime.now()).total_seconds()
    return delta
```

**Before:** `wake_time = boundary + timedelta(minutes=1)` → bets 5-10 min early
**After:**  `wake_time = boundary - timedelta(seconds=90)` → bets ~90s before close

---

## Modified: `fetcher.py`

### Three changes:

**1. Slug detection** — add near top of file:
```python
import re
_CRYPTO_INTERVAL_SLUG = re.compile(
    r'^(btc|eth|sol|bnb|xrp|doge|avax|link|matic|ada|op|arb)-updown-\d+m-\d+$'
)

def _is_crypto_5min(slug: str) -> bool:
    return bool(_CRYPTO_INTERVAL_SLUG.match(slug.lower()))
```

**2. Fetch window** — in `fetch_active_markets()`, when `CRYPTO_5MIN_ENABLED`:
```python
if config.CRYPTO_5MIN_ENABLED:
    floor  = now + timedelta(seconds=config.MIN_SECONDS_TO_CLOSE)
    cutoff = now + timedelta(seconds=config.MAX_SECONDS_TO_CLOSE)
else:
    # existing logic using MIN/MAX_MINUTES_TO_RESOLVE
    ...
```

**3. New fields** — in `_enrich_one()` return dict:
```python
seconds_to_close = max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
return {
    # ...all existing fields...
    "seconds_to_close": seconds_to_close,
    "is_crypto_5min": _is_crypto_5min(m.get("slug", "")),
}, None
```

Also update `_enrich_one()` to use seconds-based `too_soon` / `too_far` check when `CRYPTO_5MIN_ENABLED`.

---

## Modified: `analyzer.py`

Add a fast path that splits markets by type before hitting the LLM:

```python
def analyze_markets(client, markets: list[dict]) -> list[dict]:
    results = []

    crypto_markets = [m for m in markets if m.get("is_crypto_5min")]
    llm_markets    = [m for m in markets if not m.get("is_crypto_5min")]

    # Fast path: price-feed + momentum for 5-min crypto (no LLM)
    for m in crypto_markets:
        result = _analyze_crypto_5min(m)
        if result:
            results.append(result)

    # Existing path: LLM for non-crypto / long-horizon
    if llm_markets:
        llm_results = _analyze_with_llm(client, llm_markets)
        results.extend(llm_results)

    return results


def _analyze_crypto_5min(market: dict) -> dict | None:
    """
    Use OKX/Bybit live price + momentum instead of LLM.
    Returns analysis dict (same shape as LLM output) or None if no clear signal.
    """
    import price_feed

    symbol = market["slug"].split("-")[0].upper()   # "btc-updown-5m-..." → "BTC"

    strike = _parse_strike_price(market["question"])
    if strike is None:
        return None

    live_price = price_feed.get_spot_price(symbol)
    if live_price is None:
        return None

    momentum = price_feed.get_momentum(symbol)
    if momentum == "UNCLEAR":
        return None

    price_diff_pct = (live_price - strike) / strike
    if abs(price_diff_pct) < config.CRYPTO_PRICE_BUFFER:
        return None  # too close to strike — noise risk

    price_signal = "UP" if live_price > strike else "DOWN"
    if price_signal != momentum:
        return None  # price and momentum disagree — skip

    # Both agree → high confidence bet
    market_prob = market["yes_price"]
    claude_prob = 0.85 if price_signal == "UP" else 0.15

    return {
        "market_id":   market["id"],
        "question":    market["question"],
        "market_prob": market_prob,
        "claude_prob": claude_prob,
        "edge":        claude_prob - market_prob,
        "confidence":  "high",
        "reasoning":   (
            f"Live {symbol}=${live_price:.2f} vs strike=${strike:.2f} "
            f"({price_diff_pct:+.2%}), momentum={momentum}, "
            f"seconds_to_close={market.get('seconds_to_close')}"
        ),
        "end_date":       market.get("end_date"),
        "is_crypto_5min": True,
    }


def _parse_strike_price(question: str) -> float | None:
    """
    Extract dollar strike price from market question.
    Handles: "Will BTC be above $95,432.56 at 12:05?"
             "Will BTC be higher than $95000 at 3:00 PM UTC?"
    """
    matches = re.findall(r'\$([0-9,]+(?:\.[0-9]+)?)', question)
    if not matches:
        return None
    try:
        return float(matches[0].replace(",", ""))
    except ValueError:
        return None
```

Also refactor existing LLM code into `_analyze_with_llm(client, markets)` — extract from current `analyze_markets()`.

---

## Modified: `engine.py`

**No changes needed.** The `_analyze_crypto_5min()` output uses the same dict shape as LLM analysis (`market_prob`, `claude_prob`, `edge`, `confidence`). The existing Kelly and EV filters apply.

One addition: override `MAX_KELLY_FRACTION` for crypto 5-min markets using `CRYPTO_KELLY_FRACTION`:

```python
# In evaluate_trades(), before calling _kelly_bet():
if a.get("is_crypto_5min"):
    kelly_cap = config.CRYPTO_KELLY_FRACTION   # 5%
else:
    kelly_cap = config.MAX_KELLY_FRACTION      # 40% (existing)
```

---

## Timing Example (After Fix)

```
12:03:30  Bot wakes (90s before :05:00 boundary)
12:03:30  Fetch: markets closing in 5-120s → BTC-updown-5m-X (closes :05:00, 90s away)
12:03:31  OKX:   BTC live = $95,650 | strike = $95,100 | diff = +0.58%
12:03:31  OKX:   klines → 3/4 green candles → momentum = UP
12:03:31  Signal: price=UP, momentum=UP → BET YES, kelly=5% of bankroll
12:03:31  trades.csv: PENDING logged
12:05:00  Polymarket resolves → resolver.py → WON or LOST
```

Total cycle time: ~1-2 seconds (no LLM).

---

## Verification Checklist

1. **Timing**: does the bot now wake at `:03:30`, `:08:30`, `:13:30`?
2. **Fetch window**: do fetched markets have `seconds_to_close` in 5-120 range?
3. **Market tagging**: do crypto interval markets show `is_crypto_5min=True`?
4. **Price feed**: does `reasoning` field show live price vs strike from OKX?
5. **Fallback**: disconnect OKX — does it fall back to Bybit correctly?
6. **Win rate**: after 1 hour (12 cycles × up to 3 bets = ~36 bets), what is win rate?

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `price_feed.py` | **NEW** — OKX + Bybit spot price and kline momentum |
| `config.py` | **MODIFY** — add `CRYPTO_5MIN_*` constants |
| `main.py` | **MODIFY** — fix `seconds_until_next_cycle()` |
| `fetcher.py` | **MODIFY** — slug tag, seconds window, new fields |
| `analyzer.py` | **MODIFY** — split path, add `_analyze_crypto_5min()` |
| `engine.py` | **MODIFY** — add `CRYPTO_KELLY_FRACTION` override |
| `resolver.py` | **NO CHANGE** |
| `logger.py` | **NO CHANGE** |
| `dashboard.py` | **NO CHANGE** |
