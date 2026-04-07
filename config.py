# === LLM (OpenRouter) ===
MODEL_NAME = "llama-3.3-70b-versatile"
MAX_TOKENS = 1024
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# === Trading Strategy ===
EDGE_THRESHOLD = 0.05           # Minimum |edge| to trigger a trade (5%)
MAX_KELLY_FRACTION = 0.40       # Cap Kelly bet at 40% of bankroll
MIN_CONFIDENCE = "medium"       # Minimum confidence level: "low", "medium", "high"

# === Bankroll & Goal ===
STARTING_BANKROLL = 10.00       # Starting capital in USD
GOAL_AMOUNT = 1_000_000.00      # Target bankroll ($1M)

# === Loop Settings ===
LOOP_INTERVAL_SECONDS = 30      # 30 seconds between cycles (last-minute targeting)
MAX_MARKETS_PER_CYCLE = 8       # Safe under Groq 12k TPM with parallel analysis

# === Market Selection ===
MIN_DAYS_TO_RESOLVE = 0         # Allow intraday markets (hourly crypto, etc.)
MAX_DAYS_TO_RESOLVE = 7         # Skip markets resolving in >7 days (short-term only)
MIN_MINUTES_TO_RESOLVE = 3      # Ignore markets closing in less than 3 minutes (too late to bet)
MAX_MINUTES_TO_RESOLVE = 10     # Only target markets closing within next 10 minutes
MIN_LIQUIDITY = 5000            # Minimum liquidity filter (USD)

# Keywords to INCLUDE — markets where LLM has genuine reasoning edge
MARKET_FOCUS_KEYWORDS = [
    # Crypto
    "bitcoin", "btc", "ethereum", "eth", "crypto", "altcoin", "defi", "nft",
    "solana", "sol", "xrp", "ripple", "dogecoin", "doge", "bnb", "binance",
    "coinbase", "blackrock", "etf", "spot etf", "halving", "blockchain",
    "stablecoin", "usdc", "tether", "on-chain", "layer 2", "l2",
    # Macro / finance
    "fed", "federal reserve", "rate", "interest rate", "rate cut", "rate hike",
    "inflation", "cpi", "pce", "gdp", "recession", "yield", "treasury",
    "dollar", "usd", "eur", "forex", "oil", "gold", "silver", "commodities",
    # Equities
    "stock", "s&p", "nasdaq", "dow", "ipo", "earnings", "market cap",
    "apple", "tesla", "nvidia", "microsoft", "amazon", "google", "meta",
    "sec", "regulatory", "approval", "listing",
]

# Keywords to EXCLUDE — real-time sports/games where LLM has no edge
MARKET_EXCLUDE_KEYWORDS = [
    " vs. ", " vs ", "o/u ", "moneyline", "1h ", "2h ",
    "score", "win on 20", "win on 19", "win on 18",
    "nfl", "nba", "mlb", "nhl", "fifa", "premier league", "match",
    "tournament", "championship", "playoff",
]

# === Polymarket API ===
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"
REQUEST_TIMEOUT = 15            # Seconds per HTTP request

# === Output ===
TRADES_CSV_PATH = "trades.csv"
BANKROLL_PATH = "bankroll.json"

# === Crypto 5-Min Last-Minute Strategy ===
CRYPTO_5MIN_ENABLED = True
SECONDS_BEFORE_CLOSE = 20       # Wake N seconds before each 5-min boundary
MIN_SECONDS_TO_CLOSE = 5        # Skip markets closing in <5s
MAX_SECONDS_TO_CLOSE = 60       # Only target markets closing within 60s
MOMENTUM_CANDLES = 4            # Candles to evaluate (last 4 × 1-min)
MOMENTUM_THRESHOLD = 3          # Min candles same direction to confirm
CRYPTO_PRICE_BUFFER = 0.002     # 0.2% min price-vs-strike gap (noise filter)
CRYPTO_KELLY_FRACTION = 0.05    # 5% of bankroll per crypto bet (scales with balance)
CRYPTO_MAX_BETS_PER_CYCLE = 3   # Max crypto bets per cycle
