# === LLM ===
MODEL_NAME = "llama3.1:8b"
MAX_TOKENS = 1024
API_BASE_URL = "http://localhost:11434/v1"

# === Trading Strategy ===
EDGE_THRESHOLD = 0.02           # Minimum |edge| to trigger a trade (2%)
CRYPTO_EDGE_THRESHOLD = 0.015   # Lower general edge floor for crypto interval markets
CRYPTO_TAIL_EDGE_THRESHOLD = 0.005  # Lower edge threshold for extreme crypto tail markets
CRYPTO_TAIL_MARKET_PROB_CUTOFF = 0.05  # Treat <=5% or >=95% YES as tail markets
CRYPTO_TAIL_TIER_B_THRESHOLD = 0.18  # Allow small but actionable extreme-tail signals through scoring
CRYPTO_TAIL_MIN_EV_ROI = 0.001       # Lower EV floor for extreme late crypto tail setups
MAX_KELLY_FRACTION = 0.40       # Cap Kelly bet at 40% of bankroll
MIN_CONFIDENCE = "medium"       # Minimum confidence level: "low", "medium", "high"
MIN_EV_ROI = 0.005              # Minimum EV/bet ratio (0.5%) required to place a trade
LLM_TRADING_ENABLED = True      # Enabled: allow non-crypto paper trades again
RELAXED_PASS_ENABLED = False    # Disabled alongside LLM trading
RELAXED_EDGE_MULTIPLIER = 0.5   # Relaxed edge threshold = EDGE_THRESHOLD * multiplier
RELAXED_EV_ROI_MULTIPLIER = 0.5 # Relaxed EV ROI floor = MIN_EV_ROI * multiplier
RELAXED_MAX_TRADES = 1          # Max trades placed by relaxed pass
RELAXED_ALLOW_LOW_CONF_CRYPTO = False # Do not allow low-confidence crypto trades
TOP_TRADES_PER_CYCLE = 3        # Rank candidates by quality score, then take top N
SCORE_WEIGHTS = {               # Weights must sum near 1.0
    "edge": 0.30,
    "ev_roi": 0.25,
    "time": 0.20,
    "liquidity": 0.10,
    "signal": 0.15,
}
QUALITY_TIER_THRESHOLDS = {     # Score cutoffs
    "A": 0.70,                  # Full sizing
    "B": 0.40,                  # Reduced sizing
}
TIER_SIZE_MULTIPLIERS = {
    "A": 1.0,
    "B": 0.5,
    "C": 0.0,
}
CRYPTO_TIER_THRESHOLDS = {
    "A": 0.60,
    "B": 0.50,
}
CRYPTO_TIER_SIZE_MULTIPLIERS = {
    "A": 1.2,
    "B": 0.55,
    "C": 0.0,
}
DRAWDOWN_SIZE_RULES = [         # (drawdown_threshold, size_multiplier)
    (-0.20, 0.65),              # Drawdown <= -20%
    (-0.10, 0.85),              # Drawdown <= -10%
    (0.00, 1.00),               # Otherwise
]
SIDE_CONCENTRATION_LOOKBACK = 10
SIDE_CONCENTRATION_THRESHOLD = 0.70
SIDE_CONCENTRATION_SCORE_PENALTY = 0.08
DIRECTIONAL_DELTA_CLAMP = 0.08

# === Bankroll & Goal ===
STARTING_BANKROLL = 10.00       # Starting capital in USD
GOAL_AMOUNT = 1_000_000.00      # Target bankroll ($1M)

# === Loop Settings ===
LOOP_INTERVAL_SECONDS = 30      # 30 seconds between cycles (last-minute targeting)
MAX_MARKETS_PER_CYCLE = 16      # Wider crypto funnel so more tradable names survive fetch

# === Market Selection ===
MIN_DAYS_TO_RESOLVE = 0         # Allow intraday markets (hourly crypto, etc.)
MAX_DAYS_TO_RESOLVE = 7         # Skip markets resolving in >7 days (short-term only)
MIN_MINUTES_TO_RESOLVE = 3      # Ignore markets closing in less than 3 minutes (too late to bet)
MAX_MINUTES_TO_RESOLVE = 10     # Only target markets closing within next 10 minutes
MIN_LIQUIDITY = 2500            # Lower floor so more altcoin 5m markets are eligible

# Keywords to INCLUDE — markets where LLM has genuine reasoning edge
MARKET_FOCUS_KEYWORDS = [
    # Crypto
    "bitcoin", "btc", "ethereum", "eth", "crypto", "altcoin", "defi", "nft",
    "solana", "sol", "xrp", "ripple", "dogecoin", "doge", "bnb", "binance",
    "litecoin", "ltc", "polkadot", "dot", "tron", "trx", "toncoin", "ton",
    "shiba", "shib", "pepe", "sui", "aptos", "apt", "sei",
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
POLYMARKET_RTDS_URL = "wss://ws-live-data.polymarket.com"

# === Output ===
TRADES_CSV_PATH = "trades.csv"
BANKROLL_PATH = "bankroll.json"

# === Crypto 5-Min Last-Minute Strategy ===
CRYPTO_5MIN_ENABLED = True
SECONDS_BEFORE_CLOSE = 45       # First crypto phase at T-45s (analysis)
SECOND_CHANCE_SECONDS = 30      # Second crypto phase at T-30s (execution)
MIN_SECONDS_TO_CLOSE = 5        # Skip markets closing in <5s
MAX_SECONDS_TO_CLOSE = 120      # Only target markets closing within 120s
MOMENTUM_CANDLES = 4            # Candles to evaluate (last 4 × 1-min)
MOMENTUM_THRESHOLD = 2          # Min candles same direction to confirm
MOMENTUM_NET_MOVE_FALLBACK = 0.00015  # If momentum unclear, require >=0.015% net move over lookback
T15_WEAK_SIGNAL_ENABLED = True       # Allow a small late-entry fallback in final T-15s
T15_WEAK_NET_MOVE_MIN = 0.00005      # Require at least 0.005% net move for weak T15 fallback
T15_LAST_CANDLE_MOVE_MIN = 0.00003   # Require at least 0.003% move in the latest 1m candle
WINDOW_MOVE_MIN = 0.0001            # Require at least 0.01% 5-minute window move for direct up/down signal
T15_TAIL_CONTINUATION_ENABLED = False # Disabled: 21% win rate, consistent P&L drain
T15_TAIL_PROB_STEP = 0.01            # Move claude_prob by 1 percentage point on tail continuation
CRYPTO_PRICE_BUFFER = 0.001     # 0.1% min price-vs-strike gap (noise filter)
CRYPTO_KELLY_FRACTION = 0.12    # 12% of bankroll per crypto bet (scales with balance)
CRYPTO_MAX_BETS_PER_CYCLE = 3   # Max crypto bets per cycle
CRYPTO_MAX_SAME_SIDE_BETS_PER_CYCLE = 1  # Still avoid stacking correlated crypto bets on one direction
CRYPTO_NEAR_CERTAIN_LOWER = 0.001  # Skip momentum-only markets at <=0.1% YES
CRYPTO_NEAR_CERTAIN_UPPER = 0.999  # Skip momentum-only markets at >=99.9% YES
CRYPTO_FALLBACK_TO_LLM = False     # Crypto 5m uses price/momentum only
CRYPTO_INTERVAL_ENTRY_SECONDS = {   # Trade windows by interval duration
    5: 45,   # final ~45 seconds for 5m markets (T45 analysis, T30 execution)
    15: 45,  # final ~45 seconds for 15m markets
}
CRYPTO_ENTRY_GRACE_SECONDS = 0      # Phase-based polling replaces generic grace retries
ENABLE_LATE_REENTRY = True          # Optional second entry near expiry if signal improves
LATE_REENTRY_SECONDS = 30           # Re-entry allowed only in final T-30s phase
MIN_SIGNAL_IMPROVEMENT = 0.03       # Required increase in |edge| for re-entry
LATE_REENTRY_MAX_ADDITIONAL = 1     # At most one additional pending entry per market
CRYPTO_LLM_FALLBACK_MIN_EDGE = 0.02 # Require minimum fallback edge to avoid weak fallback noise
CRYPTO_LLM_FALLBACK_MIN_CONF = "medium"  # Min confidence for crypto LLM fallback
CRYPTO_UNDERLYING_STREAM_ENABLED = True
CRYPTO_WINDOW_BUFFER_MINUTES = 10
CRYPTO_5M_EXECUTE_ONLY_ON_T30 = True
CRYPTO_MAX_MARKET_SPREAD = 0.15
MIN_SAMPLE_FOR_GATING = 20          # Minimum resolved samples per strategy bucket
AUTO_DISABLE_NEGATIVE_BUCKETS = True  # Disable buckets with negative P&L after min sample
SHORT_BUCKET_DISABLE_CONSEC_LOSSES = 3
SHORT_BUCKET_DISABLE_LAST_N = 5
SHORT_BUCKET_DISABLE_MIN_LOSSES = 4
SHORT_BUCKET_DISABLE_CYCLES = 12
