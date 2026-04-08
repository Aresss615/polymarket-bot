# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

A **paper trading simulation bot** for Polymarket prediction markets. Each cycle it fetches live binary markets, sends them to an LLM for probability estimation, compares that estimate against the market price to find "edge", and logs simulated trades to `trades.csv`. No real money is ever placed.

## Commands

```bash
# Run the bot (loops every 5 minutes, Ctrl+C to stop)
.venv/bin/python main.py

# Manually resolve a pending trade outcome
.venv/bin/python logger.py resolve <trade_id> WON
.venv/bin/python logger.py resolve <trade_id> LOST

# Install dependencies
.venv/bin/pip install -r requirements.txt
```

## Architecture

The pipeline runs in a single loop: `main.py → fetcher → analyzer → engine → logger → dashboard`

| Module | Role |
|--------|------|
| `config.py` | All tuneable constants (model, thresholds, API URLs, intervals) |
| `fetcher.py` | Fetches active binary markets from Gamma API, enriches with CLOB midpoint prices |
| `analyzer.py` | Sends each market to the LLM (Groq/OpenAI-compatible) for probability estimation; returns `claude_prob`, `edge`, `confidence`, `reasoning` |
| `engine.py` | Filters analyses by `EDGE_THRESHOLD` and `MIN_CONFIDENCE`; computes `projected_pnl` |
| `logger.py` | Appends trades to `trades.csv` as `PENDING`; supports manual WON/LOST resolution |
| `dashboard.py` | Rich terminal UI — markets table, trades table, portfolio summary |

## LLM integration

Uses the **OpenAI-compatible SDK** pointed at Groq (`GROQ_BASE_URL`). The model is `llama-3.3-70b-versatile`. Response format is `{"type": "json_object"}` — the system prompt instructs the model to return `{"probability", "confidence", "reasoning"}`.

To switch providers, update `config.py` (`MODEL_NAME`, `GROQ_BASE_URL`) and the env var read in `main.py`.

## Key config knobs (`config.py`)

- `EDGE_THRESHOLD` — minimum `|claude_prob - market_price|` to trigger a trade (default 10%)
- `MIN_CONFIDENCE` — `"low"`, `"medium"`, or `"high"` (default `"medium"`)
- `MAX_MARKETS_PER_CYCLE` — caps Groq API calls per cycle (default 15)
- `LOOP_INTERVAL_SECONDS` — sleep between cycles (default 300s)

## Environment

Requires a `.env` file (copy from `.env.example`):
```
GROQ_API_KEY=gsk_...
```

## Known limitations

- LLM knowledge cutoff means sports/short-term markets have no informational edge
- `projected_pnl` is simplified (`|edge| × bet_size`), not true implied-odds P&L
- Trade resolution is manual — no auto-resolution when markets close

---

## Planned redesign (approved 2026-04-07, not yet implemented)

**Problem:** Bot was losing on Polymarket's 5-min crypto markets. Root causes:
1. Timing wrong — woke 1 min *after* each boundary, bet 5-10 min before close
2. Strategy wrong — LLM has zero edge on short-term crypto price direction

**Approved fix — Hybrid approach:**
- For crypto interval markets (`*-updown-Xm-*` slugs): skip LLM, use **OKX live price + momentum**
- Wake **90 seconds before** each 5-min boundary (not 1 min after)
- Bet only when: live price is clearly above/below strike (>0.2%) AND last 4 candles confirm direction (3/4 same direction)
- Bet sizing: 5% Kelly of bankroll (scales with wins, no hard $ cap)

**Price feed:** OKX primary (`api.okx.com`), Bybit fallback. **Never Binance** — banned in Philippines.

**Full spec:** `docs/superpowers/specs/2026-04-07-crypto-lastminute-strategy-design.md`

**Files to create/modify:**
| File | Change |
|------|--------|
| `price_feed.py` | NEW — OKX + Bybit spot price and kline momentum |
| `config.py` | Add `CRYPTO_5MIN_*` constants (`SECONDS_BEFORE_CLOSE=90`, etc.) |
| `main.py` | Fix `seconds_until_next_cycle()` to wake 90s before boundary |
| `fetcher.py` | Tag markets as `is_crypto_5min`, switch to seconds-based window |
| `analyzer.py` | Split path: crypto → price_feed, non-crypto → LLM |
| `engine.py` | Add `CRYPTO_KELLY_FRACTION` (5%) override for crypto bets |

---

## Implementation log (2026-04-07)

Implemented and shipped:

- Crypto 5-min analyzer now supports momentum fallback via net move when candle majority is unclear.
- Fetch filtering now applies windows per market type (crypto in seconds, non-crypto in minutes) instead of globally.
- Added EV quality gate in engine:
  - `MIN_EV_ROI` in `config.py`
  - trade must satisfy `projected_pnl / bet_size >= MIN_EV_ROI`
- Expanded `trades.csv` telemetry:
  - `ev_roi`, `is_crypto_5min`, `seconds_to_close`, `signal_source`,
    `momentum_signal`, `net_move_pct`, `live_price`, `strike_price`
- Added CSV header auto-migration in `logger.py` for backward compatibility.
- Added weekly calibration tool `calibrate.py` with recommendations for:
  - `EDGE_THRESHOLD`
  - `MIN_EV_ROI`
  - `MOMENTUM_NET_MOVE_FALLBACK` (when enough fallback samples exist)

Run calibration:

```bash
.venv/bin/python calibrate.py --days 7
```

## Implementation log (2026-04-08)

Implemented the 30-second crypto recovery plan with directional-bias controls:

- Crypto 5-minute trading now runs in two explicit phases per boundary:
  - `t30` at `T-30s`
  - `t15` at `T-15s`
- Removed generic crypto grace retry; fetch filtering is now phase-aware.
- Crypto 5-minute markets no longer fall back to the LLM when momentum is unclear.
- Non-crypto LLM analysis is now side-neutral:
  - prompt explicitly evaluates YES and NO symmetrically
  - LLM delta is symmetrically clamped around market price
  - weak / mixed reasoning is shrunk back toward market
- Engine now applies:
  - crypto-specific tier thresholds and size multipliers
  - recent-side concentration score penalty to reduce `BUY_YES` drift
  - short-horizon direction-bucket kill switch after repeated losses
- Trade telemetry expanded with:
  - `cycle_phase`, `boundary_time`
  - `direction_bucket`
  - `side_concentration_penalty_applied`
  - `reentry_parent_trade_id`
  - `llm_delta_before_clamp`, `llm_delta_after_clamp`
- Added regression tests for:
  - `t30` / `t15` scheduler behavior
  - no crypto LLM fallback
  - symmetric LLM calibration
  - side concentration penalty
  - short-horizon direction-bucket disable
