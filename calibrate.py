"""
Weekly calibration helper.

Usage:
    .venv/bin/python calibrate.py
    .venv/bin/python calibrate.py --days 7
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config


@dataclass
class TradeRow:
    timestamp: datetime
    status: str
    actual_pnl: float
    edge: float
    ev_roi: float
    is_crypto_5min: bool
    signal_source: str
    net_move_pct: float | None


def _to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _to_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def load_resolved_trades(days: int) -> list[TradeRow]:
    path = Path(config.TRADES_CSV_PATH)
    if not path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[TradeRow] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = (row.get("status") or "").upper()
            if status not in {"WON", "LOST"}:
                continue

            ts = _parse_ts(row.get("timestamp"))
            if ts is None or ts < cutoff:
                continue

            net_move_raw = row.get("net_move_pct")
            net_move = None if net_move_raw in (None, "") else _to_float(net_move_raw, 0.0)
            rows.append(
                TradeRow(
                    timestamp=ts,
                    status=status,
                    actual_pnl=_to_float(row.get("actual_pnl"), 0.0),
                    edge=abs(_to_float(row.get("edge"), 0.0)),
                    ev_roi=_to_float(row.get("ev_roi"), 0.0),
                    is_crypto_5min=_to_bool(row.get("is_crypto_5min")),
                    signal_source=(row.get("signal_source") or "").strip(),
                    net_move_pct=net_move,
                )
            )
    return rows


def _evaluate_threshold(rows: list[TradeRow], getter, candidates: list[float]) -> tuple[float, int, float]:
    best = (candidates[0], 0, float("-inf"))
    for c in candidates:
        subset = [r for r in rows if getter(r) >= c]
        pnl = round(sum(r.actual_pnl for r in subset), 4)
        count = len(subset)
        score = pnl if count > 0 else float("-inf")
        if score > best[2]:
            best = (c, count, pnl)
    return best


def recommend(rows: list[TradeRow]) -> None:
    total = len(rows)
    won = sum(1 for r in rows if r.status == "WON")
    pnl = round(sum(r.actual_pnl for r in rows), 4)
    win_rate = (won / total) if total else 0.0

    print(f"Resolved trades in window: {total}")
    print(f"Win rate: {win_rate:.1%}")
    print(f"Total P&L: ${pnl:+.2f}")

    if total < 10:
        print("Not enough resolved trades for robust calibration (need at least 10).")
        return

    edge_candidates = [0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12]
    roi_candidates = [0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]

    edge_rec, edge_n, edge_pnl = _evaluate_threshold(rows, lambda r: r.edge, edge_candidates)
    roi_rec, roi_n, roi_pnl = _evaluate_threshold(rows, lambda r: r.ev_roi, roi_candidates)

    print("\nRecommended updates")
    print(f"- EDGE_THRESHOLD = {edge_rec:.3f}  (keeps {edge_n} trades, P&L ${edge_pnl:+.2f})")
    print(f"- MIN_EV_ROI    = {roi_rec:.3f}  (keeps {roi_n} trades, P&L ${roi_pnl:+.2f})")

    fallback_rows = [
        r for r in rows
        if r.is_crypto_5min
        and "fallback" in r.signal_source
        and r.net_move_pct is not None
    ]
    if len(fallback_rows) >= 5:
        nm_candidates = [0.0005, 0.0007, 0.0010, 0.0015, 0.0020, 0.0030]
        nm_rec, nm_n, nm_pnl = _evaluate_threshold(
            fallback_rows, lambda r: abs(r.net_move_pct or 0.0), nm_candidates
        )
        print(
            f"- MOMENTUM_NET_MOVE_FALLBACK = {nm_rec:.4f}  "
            f"(keeps {nm_n} fallback trades, P&L ${nm_pnl:+.2f})"
        )
    else:
        print("- MOMENTUM_NET_MOVE_FALLBACK: not enough fallback trades yet (need at least 5).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly calibration suggestions from resolved trades.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    args = parser.parse_args()

    rows = load_resolved_trades(days=args.days)
    recommend(rows)


if __name__ == "__main__":
    main()
