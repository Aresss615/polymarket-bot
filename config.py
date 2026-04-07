# === Groq API (OpenAI-compatible) ===
MODEL_NAME = "llama-3.1-8b-instant"
MAX_TOKENS = 1024
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# === Trading Strategy ===
EDGE_THRESHOLD = 0.06           # Minimum |edge| to trigger a trade (6%)
MAX_KELLY_FRACTION = 0.40       # Cap Kelly bet at 40% of bankroll
MIN_CONFIDENCE = "medium"       # Minimum confidence level: "low", "medium", "high"

# === Bankroll & Goal ===
STARTING_BANKROLL = 10.00       # Starting capital in USD
GOAL_AMOUNT = 1_000_000.00      # Target bankroll ($1M)

# === Loop Settings ===
LOOP_INTERVAL_SECONDS = 300     # 5 minutes between cycles
MAX_MARKETS_PER_CYCLE = 8       # Cap on markets analyzed per cycle

# === Market Selection ===
MIN_DAYS_TO_RESOLVE = 0         # Allow intraday markets (hourly crypto, etc.)
MAX_DAYS_TO_RESOLVE = 7         # Skip markets resolving in >7 days (short-term only)
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
