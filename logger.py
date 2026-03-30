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

import config

_FIELDNAMES = [
    "id",
    "timestamp",
    "cycle",
    "market_id",
    "question",
    "direction",
    "market_prob",
    "claude_prob",
    "edge",
    "confidence",
    "bet_size",
    "projected_pnl",
    "status",
    "actual_pnl",
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


def log_trades(trades: list[dict], cycle: int) -> None:
    """Append trade decisions to trades.csv as PENDING rows."""
    if not trades:
        return
    try:
        _ensure_headers()
        with _csv_path().open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
            for t in trades:
                writer.writerow({
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "cycle": cycle,
                    "market_id": t["market_id"],
                    "question": t["question"],
                    "direction": t["direction"],
                    "market_prob": t["market_prob"],
                    "claude_prob": t["claude_prob"],
                    "edge": t["edge"],
                    "confidence": t["confidence"],
                    "bet_size": t["bet_size"],
                    "projected_pnl": t["projected_pnl"],
                    "status": "PENDING",
                    "actual_pnl": "",
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
            prob = float(t["market_prob"])
            if outcome == "WON":
                # payout = bet / market_prob (implied odds), minus the bet itself
                payout = round(bet / prob - bet, 2) if prob > 0 else 0.0
                t["actual_pnl"] = payout
            else:
                t["actual_pnl"] = -bet
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
