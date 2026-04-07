import config
import bankroll

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_MIN_RANK = _CONFIDENCE_RANK[config.MIN_CONFIDENCE]


def _kelly_bet(edge: float, market_prob: float, direction: str, balance: float) -> float:
    """
    Full Kelly fraction, capped at MAX_KELLY_FRACTION of bankroll.
    For BUY_YES: b = (1/yes_price) - 1, p = claude_prob
    For BUY_NO:  b = (1/no_price)  - 1, p = 1 - claude_prob
    Kelly fraction = (b*p - (1-p)) / b
    """
    if direction == "BUY_YES":
        price = market_prob
        p = market_prob + edge  # claude_prob
    else:
        price = round(1.0 - market_prob, 4)
        p = 1.0 - (market_prob + edge)  # prob NO wins

    if price <= 0 or price >= 1:
        return 0.0

    b = (1.0 / price) - 1.0  # net odds
    if b <= 0:
        return 0.0

    kelly = (b * p - (1.0 - p)) / b
    kelly = max(0.0, kelly)
    kelly = min(kelly, config.MAX_KELLY_FRACTION)

    return round(kelly * balance, 4)


def _expected_value(edge: float, market_prob: float, direction: str, bet: float) -> float:
    """True expected value of the bet in dollars."""
    if direction == "BUY_YES":
        price = market_prob
        p = market_prob + edge
    else:
        price = round(1.0 - market_prob, 4)
        p = 1.0 - (market_prob + edge)

    if price <= 0:
        return 0.0

    payout_if_win = bet / price - bet
    ev = p * payout_if_win - (1.0 - p) * bet
    return round(ev, 4)


def evaluate_trades(analyses: list[dict], existing_pending: set[str] | None = None) -> list[dict]:
    """
    Filter analyses that meet edge/confidence/date/focus criteria.
    Uses Kelly criterion for bet sizing and true EV for projected P&L.
    """
    pending_ids = existing_pending or set()
    remaining = bankroll.get_balance()
    trades = []

    for a in analyses:
        if remaining < 0.01:
            break

        market_id = a["market_id"]
        if market_id in pending_ids:
            continue

        # Confidence filter
        if _CONFIDENCE_RANK.get(a["confidence"], 0) < _MIN_RANK:
            continue

        # Edge filter
        edge = a["edge"]
        if abs(edge) < config.EDGE_THRESHOLD:
            continue

        direction = "BUY_YES" if edge > 0 else "BUY_NO"
        bet_size = _kelly_bet(edge, a["market_prob"], direction, remaining)

        if bet_size < 0.01:
            continue

        ev = _expected_value(edge, a["market_prob"], direction, bet_size)
        if ev <= 0:
            continue

        trades.append({
            **a,
            "direction": direction,
            "bet_size": bet_size,
            "projected_pnl": ev,
        })
        remaining = round(remaining - bet_size, 6)

    return trades
