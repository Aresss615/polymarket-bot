"""
Bankroll state — persists to bankroll.json.
Tracks current balance, peak, and goal progress.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import config


def _path() -> Path:
    return Path(config.BANKROLL_PATH)


def load() -> dict:
    """Load bankroll state. Returns defaults if file doesn't exist."""
    p = _path()
    if not p.exists():
        return {
            "balance": config.STARTING_BANKROLL,
            "peak": config.STARTING_BANKROLL,
            "start_balance": config.STARTING_BANKROLL,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "trades_resolved": 0,
        }
    with p.open() as f:
        return json.load(f)


def save(state: dict) -> None:
    with _path().open("w") as f:
        json.dump(state, f, indent=2)


def get_balance() -> float:
    return load()["balance"]


def deduct_bet(amount: float) -> float:
    """Deduct a bet stake from bankroll at placement time. Returns new balance."""
    state = load()
    state["balance"] = round(max(0.0, state["balance"] - amount), 6)
    save(state)
    return state["balance"]


def update_after_trade(payout: float) -> float:
    """Add resolved trade payout to bankroll (0 if lost, full return if won). Returns new balance."""
    state = load()
    state["balance"] = round(state["balance"] + payout, 6)
    state["peak"] = round(max(state["peak"], state["balance"]), 6)
    state["trades_resolved"] = state.get("trades_resolved", 0) + 1
    save(state)
    return state["balance"]


def get_progress() -> dict:
    """Return goal-tracking metrics for the dashboard."""
    state = load()
    balance = state["balance"]
    peak = state["peak"]
    start = state["start_balance"]
    start_time = datetime.fromisoformat(state["start_time"])
    now = datetime.now(timezone.utc)

    elapsed_days = max((now - start_time).total_seconds() / 86400, 0.001)
    total_return = (balance / start - 1) if start > 0 else 0
    drawdown = (balance / peak - 1) if peak > 0 else 0

    # Project days to goal using current CAGR
    if balance > start and elapsed_days > 0:
        daily_growth = (balance / start) ** (1 / elapsed_days)
        if daily_growth > 1:
            days_to_goal = math.log(config.GOAL_AMOUNT / balance) / math.log(daily_growth)
        else:
            days_to_goal = None
    else:
        days_to_goal = None

    return {
        "balance": balance,
        "peak": peak,
        "start_balance": start,
        "total_return": total_return,
        "drawdown": drawdown,
        "elapsed_days": elapsed_days,
        "days_to_goal": days_to_goal,
        "trades_resolved": state.get("trades_resolved", 0),
        "goal": config.GOAL_AMOUNT,
    }
