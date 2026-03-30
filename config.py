# === Claude API ===
MODEL_NAME = "claude-sonnet-4-6"
MAX_TOKENS = 1024

# === Trading Strategy ===
EDGE_THRESHOLD = 0.10       # Minimum |edge| to trigger a trade (10%)
BET_SIZE = 100.00           # Simulated dollars per trade
MIN_CONFIDENCE = "medium"   # Minimum confidence level: "low", "medium", "high"

# === Loop Settings ===
LOOP_INTERVAL_SECONDS = 300  # 5 minutes between cycles
MAX_MARKETS_PER_CYCLE = 15   # Cap on markets analyzed per cycle

# === Polymarket API ===
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"
MIN_LIQUIDITY = 5000        # Minimum liquidity filter (USD)
REQUEST_TIMEOUT = 15        # Seconds per HTTP request

# === Output ===
TRADES_CSV_PATH = "trades.csv"
