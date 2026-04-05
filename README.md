# Polymarket Compound Simulation Bot

![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat&logo=python&logoColor=white)
![Groq](https://img.shields.io/badge/LLM-Groq%20%2F%20Llama--3.3--70b-orange?style=flat)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)
![Mode](https://img.shields.io/badge/Mode-Paper%20Trading%20Only-yellow?style=flat)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat)

An AI-powered paper trading simulation bot for [Polymarket](https://polymarket.com) prediction markets. Every cycle it fetches live binary markets, sends them to an LLM for probability estimation, compares against the market price to find edge opportunities, and logs simulated trades to CSV — **no real money is ever placed**.

---

## Description

The bot simulates a systematic prediction market trading strategy using LLM-based probability estimation as its edge signal. It fetches active markets from Polymarket's Gamma API, asks Groq's `llama-3.3-70b-versatile` to estimate the true probability of each outcome, compares that estimate to the current market price, and logs a simulated trade whenever the difference (edge) exceeds a configurable threshold.

All trades are tracked in `trades.csv` with win/loss resolution support. A rich terminal dashboard shows live cycle results, portfolio performance, and bankroll progress.

---

## Features

- **LLM edge detection** — uses `llama-3.3-70b-versatile` via Groq to estimate market probabilities
- **Real-time market data** — fetches live binary markets from Polymarket's Gamma API + CLOB midpoint prices
- **Configurable thresholds** — tune edge %, confidence level, and max markets per cycle
- **Paper trading only** — all trades are simulated; zero financial risk
- **CSV trade log** — every trade written to `trades.csv` with status `PENDING` → `WON`/`LOST`
- **Manual resolution** — resolve trade outcomes via CLI command
- **Rich terminal dashboard** — live tables for markets, analyses, trades, and portfolio summary
- **Auto-retry on API errors** — graceful handling of Polymarket downtime
- **Bankroll simulation** — compound growth tracking with configurable starting balance
- **Continuous loop** — runs every 5 minutes until `Ctrl+C`

---

## Tech Stack

| Technology | Version | Role |
|---|---|---|
| Python | 3.14 | Runtime |
| [openai](https://pypi.org/project/openai/) | >=1.30.0 | OpenAI-compatible SDK (pointed at Groq) |
| [Groq API](https://console.groq.com) | — | LLM inference (`llama-3.3-70b-versatile`) |
| [requests](https://pypi.org/project/requests/) | >=2.31.0 | Polymarket API calls |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | >=1.0.0 | Environment variable loading |
| [rich](https://pypi.org/project/rich/) | >=13.0.0 | Terminal dashboard UI |

---

## Architecture

The pipeline runs as a single continuous loop:

```
main.py → fetcher → analyzer → engine → logger → resolver → bankroll → dashboard
```

| Module | Role |
|---|---|
| `config.py` | All tuneable constants (model, thresholds, API URLs, intervals) |
| `fetcher.py` | Fetches active binary markets from Gamma API, enriches with CLOB midpoint prices |
| `analyzer.py` | Sends each market to the LLM; returns `claude_prob`, `edge`, `confidence`, `reasoning` |
| `engine.py` | Filters by `EDGE_THRESHOLD` and `MIN_CONFIDENCE`; computes `projected_pnl` |
| `logger.py` | Appends trades to `trades.csv` as `PENDING`; supports WON/LOST resolution |
| `resolver.py` | Auto-resolves pending trades when markets close |
| `bankroll.py` | Tracks simulated compound balance and growth progress |
| `dashboard.py` | Rich terminal UI — markets table, trades table, portfolio summary |

---

## Installation

### Prerequisites

- Python 3.10+
- A [Groq API key](https://console.groq.com) (free tier available)
- Git

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/johnchrisley/polymarket-bot.git
cd polymarket-bot

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

---

## Configuration

Edit `.env`:

```env
GROQ_API_KEY=gsk_your_key_here
```

Edit `config.py` to tune behavior:

| Key | Default | Description |
|---|---|---|
| `EDGE_THRESHOLD` | `0.10` | Minimum `\|llm_prob - market_price\|` to trigger a trade (10%) |
| `MIN_CONFIDENCE` | `"medium"` | Minimum LLM confidence: `"low"`, `"medium"`, or `"high"` |
| `MAX_MARKETS_PER_CYCLE` | `15` | Max markets analyzed per cycle (caps Groq API usage) |
| `LOOP_INTERVAL_SECONDS` | `300` | Seconds between cycles (default: 5 minutes) |
| `MODEL_NAME` | `"llama-3.3-70b-versatile"` | Groq model to use |

---

## Usage

### Run the bot

```bash
.venv/bin/python main.py
```

The bot will:
1. Fetch live markets from Polymarket
2. Analyze each with the LLM
3. Log simulated trades with edge > threshold
4. Display a rich dashboard summary
5. Sleep 5 minutes and repeat

Stop with `Ctrl+C`.

### Resolve a trade manually

```bash
.venv/bin/python logger.py resolve <trade_id> WON
.venv/bin/python logger.py resolve <trade_id> LOST
```

---

## Screenshots

### Terminal Dashboard — Cycle Summary
![Dashboard Cycle](./screenshots/dashboard-cycle.png)

### Markets Table
![Markets Table](./screenshots/markets-table.png)

### Trades Log
![Trades Log](./screenshots/trades-log.png)

### Portfolio Summary
![Portfolio Summary](./screenshots/portfolio-summary.png)

> **Note:** Create a `screenshots/` folder and add images to populate the above.

---

## Folder Structure

```
polymarket-bot/
├── main.py             # Entry point — main loop and cycle orchestration
├── config.py           # All tunable constants (thresholds, model, intervals)
├── fetcher.py          # Polymarket Gamma API + CLOB price fetcher
├── analyzer.py         # LLM probability estimation via Groq
├── engine.py           # Edge filtering and trade evaluation
├── logger.py           # CSV trade logging and manual resolution CLI
├── resolver.py         # Auto-resolution of closed markets
├── bankroll.py         # Simulated compound bankroll tracking
├── dashboard.py        # Rich terminal UI
├── trades.csv          # Trade log (auto-generated)
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── .env                # Your local config (gitignored)
```

---

## Deployment

### Run on a VPS (24/7 operation)

```bash
# SSH into your server
ssh user@your-server.com

# Clone and set up
git clone https://github.com/johnchrisley/polymarket-bot.git
cd polymarket-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # Add your GROQ_API_KEY

# Run in a persistent session with tmux
tmux new -s polymarket
.venv/bin/python main.py
# Detach: Ctrl+B then D
# Reattach: tmux attach -t polymarket
```

### Run as a systemd service

```ini
# /etc/systemd/system/polymarket-bot.service
[Unit]
Description=Polymarket Simulation Bot
After=network.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/polymarket-bot
ExecStart=/home/youruser/polymarket-bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable polymarket-bot
sudo systemctl start polymarket-bot
sudo journalctl -u polymarket-bot -f
```

---

## Known Limitations

- LLM knowledge cutoff means sports and short-term markets have limited informational edge
- `projected_pnl` is simplified (`|edge| × bet_size`), not true implied-odds P&L
- Trade resolution requires manual CLI input unless a market has a detectable close date

---

## Future Improvements

- [ ] Automated trade resolution via Polymarket settlement data
- [ ] Backtesting mode against historical market data
- [ ] Web dashboard (Flask/FastAPI) instead of terminal-only UI
- [ ] Multi-model ensemble for higher-confidence probability estimates
- [ ] Discord/Telegram alerts for high-edge trade signals
- [ ] Portfolio analytics (Sharpe ratio, win rate, ROI charts)
- [ ] Support for multi-outcome (non-binary) markets
- [ ] Real trading mode with Polymarket API integration (opt-in)

---

## Disclaimer

> **This bot is for educational and simulation purposes only.** It does not place real trades or interact with any real-money systems. Prediction markets involve financial risk. Past simulated performance does not guarantee future results. Use any real trading tools at your own risk.

---

## Author

**John Chrisley**
- GitHub: [@johnchrisley](https://github.com/johnchrisley)

---

## License

MIT License — see [LICENSE](./LICENSE) for details.
