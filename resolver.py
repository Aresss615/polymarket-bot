"""
Auto-resolver — polls Gamma API each cycle and resolves PENDING trades
when their market has closed and a resolution price is available.
"""

import requests
import config
import bankroll
import logger


def _fetch_market(market_id: str) -> dict | None:
    """Fetch a single market from Gamma API by ID."""
    try:
        resp = requests.get(
            f"{config.GAMMA_API_URL}/markets/{market_id}",
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _determine_outcome(trade: dict, market: dict) -> str | None:
    """
    Returns 'WON', 'LOST', or None if outcome can't be determined yet.
    Tries resolutionPrice first, then outcomePrices[0] (first outcome = YES/Up).
    """
    if not market.get("closed"):
        return None

    # Try resolutionPrice (some markets use this)
    resolution_price = market.get("resolutionPrice")
    if resolution_price is not None:
        try:
            res = float(resolution_price)
            yes_won = res >= 0.5
        except (ValueError, TypeError):
            yes_won = None
    else:
        yes_won = None

    # Fall back to outcomePrices (5-min crypto Up/Down markets use this)
    if yes_won is None:
        import json as _json
        outcome_prices = market.get("outcomePrices")
        if not outcome_prices:
            return None
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = _json.loads(outcome_prices)
            except Exception:
                return None
        try:
            yes_won = float(outcome_prices[0]) >= 0.5
        except (ValueError, TypeError, IndexError):
            return None

    direction = trade.get("direction", "BUY_YES")
    if direction == "BUY_YES":
        return "WON" if yes_won else "LOST"
    else:
        return "WON" if not yes_won else "LOST"


def auto_resolve() -> int:
    """
    Check all PENDING trades. Resolve any whose market has closed.
    Returns the number of trades resolved this call.
    """
    trades = logger.load_trades()
    pending = [t for t in trades if t.get("status") == "PENDING"]
    if not pending:
        return 0

    resolved_count = 0

    for trade in pending:
        market = _fetch_market(trade["market_id"])
        if not market:
            continue

        outcome = _determine_outcome(trade, market)
        if not outcome:
            continue

        # Compute actual P&L and payout
        bet = float(trade["bet_size"])
        market_prob = float(trade["market_prob"])
        if outcome == "WON":
            if trade["direction"] == "BUY_YES":
                payout = round(bet / market_prob, 4) if market_prob > 0 else 0.0
            else:  # BUY_NO
                no_price = round(1.0 - market_prob, 4)
                payout = round(bet / no_price, 4) if no_price > 0 else 0.0
            actual_pnl = round(payout - bet, 4)
        else:
            payout = 0.0
            actual_pnl = -bet

        # Update trade in CSV
        trade["status"] = outcome
        trade["actual_pnl"] = actual_pnl

        # Return payout to bankroll (stake was already deducted at placement)
        bankroll.update_after_trade(payout)
        resolved_count += 1

        print(f"[resolver] Auto-resolved {trade['market_id'][:12]}… as {outcome} | P&L: ${actual_pnl:+.2f}")

    if resolved_count > 0:
        # Rewrite CSV with updated statuses
        import csv
        from pathlib import Path
        p = Path(config.TRADES_CSV_PATH)
        updated = {t["id"]: t for t in trades}
        all_trades = logger.load_trades()
        for t in all_trades:
            if t["id"] in updated:
                t.update(updated[t["id"]])
        with p.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=logger._FIELDNAMES)
            writer.writeheader()
            writer.writerows(all_trades)

    return resolved_count
