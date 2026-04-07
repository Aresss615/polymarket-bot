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
