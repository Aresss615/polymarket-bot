import config

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_MIN_RANK = _CONFIDENCE_RANK[config.MIN_CONFIDENCE]


def evaluate_trades(analyses: list[dict], existing_pending: set[str] | None = None) -> list[dict]:
    """
    Filter analyses that meet the edge threshold and minimum confidence.
    Skips markets that already have a PENDING trade.

    Returns a list of trade decision dicts.
    """
    pending_ids = existing_pending or set()
    trades = []

    for a in analyses:
        market_id = a["market_id"]
        if market_id in pending_ids:
            continue

        confidence_rank = _CONFIDENCE_RANK.get(a["confidence"], 0)
        if confidence_rank < _MIN_RANK:
            continue

        edge = a["edge"]
        if abs(edge) < config.EDGE_THRESHOLD:
            continue

        direction = "BUY_YES" if edge > 0 else "BUY_NO"
        trade = calculate_sim_pnl({**a, "direction": direction})
        trades.append(trade)

    return trades


def calculate_sim_pnl(trade: dict) -> dict:
    """
    Add bet_size and projected_pnl to a trade dict.
    projected_pnl = |edge| * bet_size
    """
    trade = dict(trade)
    trade["bet_size"] = config.BET_SIZE
    trade["projected_pnl"] = round(abs(trade["edge"]) * config.BET_SIZE, 2)
    return trade
