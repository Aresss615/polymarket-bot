"""
Trade logger — writes trades to CSV and supports manual resolution.

CLI usage:
    python logger.py resolve <trade_id> WON
    python logger.py resolve <trade_id> LOST
"""

import csv
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bankroll as _bankroll
import config

_FIELDNAMES = [
    "id",
    "timestamp",
    "cycle",
    "market_id",
    "question",
    "direction",
    "display_direction",
    "market_prob",
    "claude_prob",
    "market_implied_up_prob",
    "probability_up",
    "edge",
    "confidence",
    "bet_size",
    "projected_pnl",
    "ev_roi",
    "status",
    "actual_pnl",
    "bankroll_before",
    "bankroll_after",
    "is_crypto_5min",
    "seconds_to_close",
    "interval_minutes",
    "signal_source",
    "cycle_phase",
    "boundary_time",
    "quality_tier",
    "trade_score",
    "tier_size_multiplier",
    "drawdown_size_multiplier",
    "strategy_bucket",
    "direction_bucket",
    "side_concentration_penalty_applied",
    "reentry_parent_trade_id",
    "momentum_signal",
    "net_move_pct",
    "window_move_pct",
    "window_start_price",
    "window_current_price",
    "window_high",
    "window_low",
    "last60_move_pct",
    "last30_move_pct",
    "last15_move_pct",
    "pattern",
    "data_source",
    "market_spread",
    "best_bid",
    "best_ask",
    "last_trade_price",
    "live_price",
    "strike_price",
    "llm_delta_before_clamp",
    "llm_delta_after_clamp",
    "reasoning",
]


def _csv_path() -> Path:
    return Path(config.TRADES_CSV_PATH)


def _ensure_headers() -> None:
    p = _csv_path()
    if not p.exists() or p.stat().st_size == 0:
        with p.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
            writer.writeheader()
        return

    # Migrate existing CSV to latest schema if headers differ.
    with p.open(newline="") as f:
        reader = csv.DictReader(f)
        existing = reader.fieldnames or []
        rows = list(reader)

    if existing == _FIELDNAMES:
        return

    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            normalized = {k: row.get(k, "") for k in _FIELDNAMES}
            writer.writerow(normalized)


def log_trades(trades: list[dict], cycle: int, bankroll_balance: float) -> None:
    """Append trade decisions to trades.csv as PENDING rows."""
    if not trades:
        return
    try:
        _ensure_headers()
        with _csv_path().open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
            for t in trades:
                before = _bankroll.get_balance()
                after = _bankroll.deduct_bet(t["bet_size"])
                writer.writerow({
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "cycle": cycle,
                    "market_id": t["market_id"],
                    "question": t["question"],
                    "direction": t["direction"],
                    "display_direction": t.get("display_direction", ""),
                    "market_prob": t["market_prob"],
                    "claude_prob": t["claude_prob"],
                    "market_implied_up_prob": t.get("market_implied_up_prob", ""),
                    "probability_up": t.get("probability_up", ""),
                    "edge": t["edge"],
                    "confidence": t["confidence"],
                    "bet_size": t["bet_size"],
                    "projected_pnl": t["projected_pnl"],
                    "ev_roi": t.get("ev_roi", ""),
                    "status": "PENDING",
                    "actual_pnl": "",
                    "bankroll_before": before,
                    "bankroll_after": after,
                    "is_crypto_5min": t.get("is_crypto_5min", ""),
                    "seconds_to_close": t.get("seconds_to_close", ""),
                    "interval_minutes": t.get("interval_minutes", ""),
                    "signal_source": t.get("signal_source", ""),
                    "cycle_phase": t.get("cycle_phase", ""),
                    "boundary_time": t.get("boundary_time", ""),
                    "quality_tier": t.get("quality_tier", ""),
                    "trade_score": t.get("trade_score", ""),
                    "tier_size_multiplier": t.get("tier_size_multiplier", ""),
                    "drawdown_size_multiplier": t.get("drawdown_size_multiplier", ""),
                    "strategy_bucket": t.get("strategy_bucket", ""),
                    "direction_bucket": t.get("direction_bucket", ""),
                    "side_concentration_penalty_applied": t.get("side_concentration_penalty_applied", ""),
                    "reentry_parent_trade_id": t.get("reentry_parent_trade_id", ""),
                    "momentum_signal": t.get("momentum_signal", ""),
                    "net_move_pct": t.get("net_move_pct", ""),
                    "window_move_pct": t.get("window_move_pct", ""),
                    "window_start_price": t.get("window_start_price", ""),
                    "window_current_price": t.get("window_current_price", ""),
                    "window_high": t.get("window_high", ""),
                    "window_low": t.get("window_low", ""),
                    "last60_move_pct": t.get("last60_move_pct", ""),
                    "last30_move_pct": t.get("last30_move_pct", ""),
                    "last15_move_pct": t.get("last15_move_pct", ""),
                    "pattern": t.get("pattern", ""),
                    "data_source": t.get("data_source", ""),
                    "market_spread": t.get("market_spread", ""),
                    "best_bid": t.get("best_bid", ""),
                    "best_ask": t.get("best_ask", ""),
                    "last_trade_price": t.get("last_trade_price", ""),
                    "live_price": t.get("live_price", ""),
                    "strike_price": t.get("strike_price", ""),
                    "llm_delta_before_clamp": t.get("llm_delta_before_clamp", ""),
                    "llm_delta_after_clamp": t.get("llm_delta_after_clamp", ""),
                    "reasoning": t["reasoning"],
                })
    except IOError as e:
        print(f"[logger] Failed to write trades: {e}")


def load_trades() -> list[dict]:
    """Read all trades from CSV. Returns empty list if file doesn't exist."""
    p = _csv_path()
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def get_pending_market_ids() -> set[str]:
    """Return set of market_ids that have a PENDING trade."""
    return {t["market_id"] for t in load_trades() if t.get("status") == "PENDING"}


def get_pending_trades() -> list[dict]:
    """Return all PENDING trades."""
    return [t for t in load_trades() if t.get("status") == "PENDING"]


def get_strategy_bucket_stats() -> dict[str, dict]:
    """
    Aggregate resolved performance by strategy bucket.
    Bucket key: signal_source|interval_minutes|quality_tier
    """
    stats: dict[str, dict] = {}
    for t in load_trades():
        status = (t.get("status") or "").upper()
        if status not in {"WON", "LOST"}:
            continue
        signal_source = t.get("signal_source") or "unknown"
        interval = t.get("interval_minutes") or "na"
        quality_tier = t.get("quality_tier") or "NA"
        key = f"{signal_source}|{interval}|{quality_tier}"
        row = stats.setdefault(key, {"count": 0, "pnl": 0.0})
        row["count"] += 1
        row["pnl"] += float(t.get("actual_pnl") or 0.0)
    for row in stats.values():
        row["pnl"] = round(row["pnl"], 6)
    return stats


def get_direction_bucket_stats() -> dict[str, dict]:
    """
    Aggregate resolved performance by direction bucket.
    Bucket key: signal_source|interval_minutes|direction|quality_tier
    """
    stats: dict[str, dict] = {}
    for t in load_trades():
        status = (t.get("status") or "").upper()
        if status not in {"WON", "LOST"}:
            continue
        key = t.get("direction_bucket")
        if not key:
            signal_source = t.get("signal_source") or "unknown"
            interval = t.get("interval_minutes") or "na"
            direction = t.get("display_direction") or t.get("direction") or "unknown"
            quality_tier = t.get("quality_tier") or "NA"
            key = f"{signal_source}|{interval}|{direction}|{quality_tier}"
        row = stats.setdefault(key, {"count": 0, "pnl": 0.0})
        row["count"] += 1
        row["pnl"] += float(t.get("actual_pnl") or 0.0)
    for row in stats.values():
        row["pnl"] = round(row["pnl"], 6)
    return stats


def get_portfolio_summary() -> dict:
    """Aggregate stats across all trades."""
    trades = load_trades()
    total = len(trades)
    pending = sum(1 for t in trades if t["status"] == "PENDING")
    won = sum(1 for t in trades if t["status"] == "WON")
    lost = sum(1 for t in trades if t["status"] == "LOST")

    actual_pnl_vals = [float(t["actual_pnl"]) for t in trades if t.get("actual_pnl")]
    total_pnl = round(sum(actual_pnl_vals), 2)

    return {
        "total": total,
        "pending": pending,
        "won": won,
        "lost": lost,
        "total_pnl": total_pnl,
        "win_rate": round(won / (won + lost), 3) if (won + lost) > 0 else None,
    }


def resolve_trade(trade_id: str, outcome: str) -> None:
    """
    Update a PENDING trade to WON or LOST and compute actual_pnl.
    Rewrites the entire CSV in-place.
    """
    import bankroll as _bankroll

    outcome = outcome.upper()
    if outcome not in ("WON", "LOST"):
        raise ValueError(f"Outcome must be WON or LOST, got: {outcome!r}")

    trades = load_trades()
    found = False
    for t in trades:
        if t["id"] == trade_id:
            if t["status"] != "PENDING":
                print(f"Trade {trade_id} is already {t['status']}.")
                return
            t["status"] = outcome
            bet = float(t["bet_size"])
            market_prob = float(t["market_prob"])
            direction = t.get("direction", "BUY_YES")

            if outcome == "WON":
                if direction == "BUY_YES":
                    payout = round(bet / market_prob, 4) if market_prob > 0 else 0.0
                else:
                    no_price = round(1.0 - market_prob, 4)
                    payout = round(bet / no_price, 4) if no_price > 0 else 0.0
                actual_pnl = round(payout - bet, 4)
            else:
                payout = 0.0
                actual_pnl = -bet

            t["actual_pnl"] = actual_pnl
            new_balance = _bankroll.update_after_trade(payout)
            t["bankroll_after"] = new_balance
            found = True
            break

    if not found:
        print(f"Trade ID {trade_id!r} not found.")
        return

    p = _csv_path()
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        writer.writerows(trades)

    print(f"Resolved trade {trade_id} as {outcome}.")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "resolve":
        _, _, trade_id, outcome = sys.argv
        resolve_trade(trade_id, outcome)
    else:
        print("Usage: python logger.py resolve <trade_id> WON|LOST")
        sys.exit(1)
