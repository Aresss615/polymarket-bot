import config
import bankroll
from collections import Counter

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_MIN_RANK = _CONFIDENCE_RANK[config.MIN_CONFIDENCE]
_LAST_REJECTIONS: list[dict] = []


def _record_rejection(analysis: dict, reason: str) -> None:
    _LAST_REJECTIONS.append({
        "market_id": analysis.get("market_id"),
        "question": analysis.get("question", ""),
        "reason": reason,
        "stage": "engine",
    })


def reset_rejections() -> None:
    _LAST_REJECTIONS.clear()


def get_rejection_summary() -> dict[str, int]:
    counts = Counter()
    for event in _LAST_REJECTIONS:
        counts[f"{event.get('stage', 'engine')}:{event.get('reason', 'unknown')}"] += 1
    return dict(sorted(counts.items()))


def _kelly_bet(edge: float, market_prob: float, direction: str, balance: float, kelly_cap: float | None = None) -> float:
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
    cap = kelly_cap if kelly_cap is not None else config.MAX_KELLY_FRACTION
    kelly = min(kelly, cap)

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


def _drawdown_multiplier() -> float:
    drawdown = bankroll.get_progress().get("drawdown", 0.0)
    rules = sorted(getattr(config, "DRAWDOWN_SIZE_RULES", []), key=lambda x: x[0])
    for threshold, mult in rules:
        if drawdown <= threshold:
            return float(mult)
    return 1.0


def _signal_strength_score(a: dict) -> float:
    confidence = (a.get("confidence") or "").lower()
    base = {"high": 1.0, "medium": 0.7, "low": 0.4}.get(confidence, 0.5)
    src = (a.get("signal_source") or "").lower()
    if "price+momentum" in src:
        base += 0.10
    elif "fallback" in src:
        base -= 0.02
    return max(0.0, min(1.0, base))


def _time_proximity_score(a: dict) -> float:
    seconds_to_close = a.get("seconds_to_close")
    if seconds_to_close is None:
        return 0.5
    try:
        seconds_to_close = max(0.0, float(seconds_to_close))
    except (TypeError, ValueError):
        return 0.5

    interval = a.get("interval_minutes")
    if a.get("is_crypto_5min") and isinstance(interval, int):
        max_window = getattr(config, "CRYPTO_INTERVAL_ENTRY_SECONDS", {}).get(interval)
        if max_window is None:
            max_window = config.MAX_SECONDS_TO_CLOSE
        # Include grace window in scoring for crypto interval markets so
        # valid grace-window entries are not penalized as low-quality.
        if a.get("is_crypto_5min"):
            max_window += int(getattr(config, "CRYPTO_ENTRY_GRACE_SECONDS", 0) or 0)
    else:
        # Non-crypto markets are filtered in minutes, so score against that window.
        max_minutes = int(getattr(config, "MAX_MINUTES_TO_RESOLVE", 10) or 10)
        min_minutes = int(getattr(config, "MIN_MINUTES_TO_RESOLVE", 0) or 0)
        max_window = max(60, max_minutes * 60 - min_minutes * 60)

    max_window = max(1.0, float(max_window))
    score = 1.0 - min(seconds_to_close / max_window, 1.0)
    return max(0.0, min(1.0, score))


def _score_candidate(a: dict, ev_roi: float) -> float:
    weights = getattr(config, "SCORE_WEIGHTS", {})
    edge_score = min(abs(float(a["edge"])) / 0.10, 1.0)
    ev_score = min(max(0.0, ev_roi) / 0.20, 1.0)
    time_score = _time_proximity_score(a)
    liq = float(a.get("liquidity") or 0.0)
    liquidity_score = min(liq / 20000.0, 1.0)
    signal_score = _signal_strength_score(a)
    score = (
        weights.get("edge", 0.30) * edge_score
        + weights.get("ev_roi", 0.25) * ev_score
        + weights.get("time", 0.20) * time_score
        + weights.get("liquidity", 0.10) * liquidity_score
        + weights.get("signal", 0.15) * signal_score
    )
    return round(max(0.0, min(1.0, score)), 6)


def _effective_edge_threshold(a: dict) -> float:
    threshold = float(getattr(config, "EDGE_THRESHOLD", 0.02))
    if not a.get("is_crypto_5min"):
        return threshold
    threshold = float(getattr(config, "CRYPTO_EDGE_THRESHOLD", threshold))
    market_prob = float(a.get("market_prob") or 0.5)
    cutoff = float(getattr(config, "CRYPTO_TAIL_MARKET_PROB_CUTOFF", 0.05))
    if market_prob <= cutoff or market_prob >= (1.0 - cutoff):
        return float(getattr(config, "CRYPTO_TAIL_EDGE_THRESHOLD", threshold))
    return threshold


def _is_crypto_tail_market(a: dict) -> bool:
    if not a.get("is_crypto_5min"):
        return False
    market_prob = float(a.get("market_prob") or 0.5)
    cutoff = float(getattr(config, "CRYPTO_TAIL_MARKET_PROB_CUTOFF", 0.05))
    return market_prob <= cutoff or market_prob >= (1.0 - cutoff)


def _effective_min_ev_roi(a: dict) -> float:
    threshold = float(getattr(config, "MIN_EV_ROI", 0.005))
    if _is_crypto_tail_market(a):
        return float(getattr(config, "CRYPTO_TAIL_MIN_EV_ROI", threshold))
    return threshold


def _quality_tier(score: float, a: dict) -> str:
    if _is_crypto_tail_market(a):
        if score >= float(getattr(config, "CRYPTO_TAIL_TIER_B_THRESHOLD", 0.30)):
            return "B"
        return "C"
    thresholds = (
        getattr(config, "CRYPTO_TIER_THRESHOLDS", {})
        if a.get("is_crypto_5min")
        else getattr(config, "QUALITY_TIER_THRESHOLDS", {})
    )
    if score >= float(thresholds.get("A", 0.70)):
        return "A"
    if score >= float(thresholds.get("B", 0.45)):
        return "B"
    return "C"


def _tier_multiplier(tier: str, a: dict) -> float:
    multipliers = (
        getattr(config, "CRYPTO_TIER_SIZE_MULTIPLIERS", {})
        if a.get("is_crypto_5min")
        else getattr(config, "TIER_SIZE_MULTIPLIERS", {})
    )
    return float(multipliers.get(tier, 0.0))


def _strategy_bucket(signal_source: str, interval_minutes, tier: str) -> str:
    interval = interval_minutes if interval_minutes is not None else "na"
    return f"{signal_source or 'unknown'}|{interval}|{tier}"


def _normalized_direction(payload: dict, fallback: str | None = None) -> str:
    value = payload.get("display_direction") or payload.get("direction") or fallback or "unknown"
    return str(value)


def _direction_bucket(signal_source: str, interval_minutes, direction: str, tier: str) -> str:
    interval = interval_minutes if interval_minutes is not None else "na"
    return f"{signal_source or 'unknown'}|{interval}|{direction}|{tier}"


def _trade_direction_bucket(trade: dict) -> str:
    existing = trade.get("direction_bucket")
    if existing:
        return existing
    return _direction_bucket(
        trade.get("signal_source"),
        trade.get("interval_minutes"),
        _normalized_direction(trade),
        trade.get("quality_tier") or "NA",
    )


def _trade_cycle(trade: dict) -> int:
    try:
        return int(trade.get("cycle") or 0)
    except (TypeError, ValueError):
        return 0


def _side_concentration_penalty(direction: str, all_trades: list[dict]) -> float:
    lookback = int(getattr(config, "SIDE_CONCENTRATION_LOOKBACK", 10) or 0)
    if lookback <= 0:
        return 0.0

    recent = [
        t for t in all_trades
        if _normalized_direction(t) in {"BUY_YES", "BUY_NO", "BUY_UP", "BUY_DOWN"}
    ]
    if len(recent) < lookback:
        return 0.0

    sample = recent[-lookback:]
    same_side = sum(1 for t in sample if _normalized_direction(t) == direction)
    share = same_side / max(1, len(sample))
    if share > float(getattr(config, "SIDE_CONCENTRATION_THRESHOLD", 0.70)):
        return float(getattr(config, "SIDE_CONCENTRATION_SCORE_PENALTY", 0.08))
    return 0.0


def _short_bucket_disable_reason(
    direction_bucket: str,
    all_trades: list[dict],
    current_cycle: int | None,
) -> str | None:
    if current_cycle is None:
        return None

    resolved = [
        t for t in all_trades
        if (t.get("status") or "").upper() in {"WON", "LOST"}
        and _trade_direction_bucket(t) == direction_bucket
    ]
    if not resolved:
        return None

    resolved.sort(key=_trade_cycle)
    trigger_cycle = None
    trigger_reason = None

    consec_needed = int(getattr(config, "SHORT_BUCKET_DISABLE_CONSEC_LOSSES", 3))
    if len(resolved) >= consec_needed:
        tail = resolved[-consec_needed:]
        if all((t.get("status") or "").upper() == "LOST" for t in tail):
            trigger_cycle = _trade_cycle(tail[-1])
            trigger_reason = f"{consec_needed} consecutive losses"

    window = int(getattr(config, "SHORT_BUCKET_DISABLE_LAST_N", 5))
    min_losses = int(getattr(config, "SHORT_BUCKET_DISABLE_MIN_LOSSES", 4))
    if len(resolved) >= window:
        recent_window = resolved[-window:]
        losses = sum(1 for t in recent_window if (t.get("status") or "").upper() == "LOST")
        if losses >= min_losses:
            window_cycle = _trade_cycle(recent_window[-1])
            if trigger_cycle is None or window_cycle >= trigger_cycle:
                trigger_cycle = window_cycle
                trigger_reason = f"{losses} losses in last {window}"

    if trigger_cycle is None:
        return None

    disable_cycles = int(getattr(config, "SHORT_BUCKET_DISABLE_CYCLES", 12))
    if current_cycle <= trigger_cycle + disable_cycles:
        return trigger_reason
    return None


def _reentry_parent_trade_id(a: dict, pending_same_market: list[dict]) -> str | None:
    if not getattr(config, "ENABLE_LATE_REENTRY", False):
        return None
    if not a.get("is_crypto_5min"):
        return None

    secs = a.get("seconds_to_close")
    try:
        secs = int(secs)
    except (TypeError, ValueError):
        return None
    if secs > int(getattr(config, "LATE_REENTRY_SECONDS", 30)):
        return None

    max_additional = int(getattr(config, "LATE_REENTRY_MAX_ADDITIONAL", 1))
    if len(pending_same_market) >= (1 + max_additional):
        return None

    current_abs_edge = abs(float(a.get("edge") or 0.0))
    best_prev = 0.0
    parent_id = None
    for t in pending_same_market:
        try:
            trade_edge = abs(float(t.get("edge") or 0.0))
        except (TypeError, ValueError):
            continue
        if trade_edge >= best_prev:
            best_prev = trade_edge
            parent_id = t.get("id")
    improvement = current_abs_edge - best_prev
    if improvement >= float(getattr(config, "MIN_SIGNAL_IMPROVEMENT", 0.02)):
        return parent_id
    return None


def evaluate_trades(
    analyses: list[dict],
    existing_pending_trades: list[dict] | None = None,
    bucket_stats: dict[str, dict] | None = None,
    direction_bucket_stats: dict[str, dict] | None = None,
    all_trades: list[dict] | None = None,
    current_cycle: int | None = None,
) -> list[dict]:
    """
    Rank analyses with quality scoring, then place top-N trades using tiered
    sizing and drawdown-aware multipliers.
    """
    pending_trades = existing_pending_trades or []
    reset_rejections()
    pending_by_market: dict[str, list[dict]] = {}
    for t in pending_trades:
        pending_by_market.setdefault(t.get("market_id", ""), []).append(t)

    strategy_stats = bucket_stats or {}
    directional_stats = direction_bucket_stats or {}
    trade_history = all_trades or []
    drawdown_mult = _drawdown_multiplier()
    candidate_rows = []

    for a in analyses:
        market_id = a["market_id"]
        pending_same = pending_by_market.get(market_id, [])
        reentry_parent_trade_id = None
        if pending_same:
            reentry_parent_trade_id = _reentry_parent_trade_id(a, pending_same)
            if not reentry_parent_trade_id:
                _record_rejection(a, "pending_or_reentry_not_improved")
                continue

        if _CONFIDENCE_RANK.get(a["confidence"], 0) < _MIN_RANK:
            _record_rejection(a, "confidence_below_min")
            continue

        if a.get("cycle_phase") == "t45" and int(a.get("interval_minutes") or 0) == 5:
            _record_rejection(a, "observe_only_phase")
            continue

        if not a.get("is_crypto_5min") and not getattr(config, "LLM_TRADING_ENABLED", True):
            _record_rejection(a, "llm_trading_disabled")
            continue

        if (
            a.get("is_crypto_5min")
            and int(a.get("interval_minutes") or 0) == 5
            and getattr(config, "CRYPTO_5M_EXECUTE_ONLY_ON_T30", True)
            and a.get("cycle_phase") != "t30"
        ):
            _record_rejection(a, "observe_only_phase")
            continue

        edge = float(a["edge"])
        if abs(edge) < _effective_edge_threshold(a):
            _record_rejection(a, "edge_below_threshold")
            continue

        direction = "BUY_YES" if edge > 0 else "BUY_NO"
        normalized_direction = _normalized_direction(a, direction)
        ev_per_dollar = _expected_value(edge, a["market_prob"], direction, 1.0)
        if ev_per_dollar <= 0:
            _record_rejection(a, "ev_non_positive")
            continue
        ev_roi = ev_per_dollar
        if ev_roi < _effective_min_ev_roi(a):
            _record_rejection(a, "ev_below_min_roi")
            continue

        base_score = _score_candidate(a, ev_roi)
        side_penalty = _side_concentration_penalty(normalized_direction, trade_history)
        score = round(max(0.0, base_score - side_penalty), 6)
        tier = _quality_tier(score, a)
        tier_mult = _tier_multiplier(tier, a)
        if tier_mult <= 0:
            _record_rejection(a, "tier_blocked")
            continue

        bucket = _strategy_bucket(a.get("signal_source"), a.get("interval_minutes"), tier)
        direction_bucket = _direction_bucket(a.get("signal_source"), a.get("interval_minutes"), normalized_direction, tier)
        row = strategy_stats.get(bucket)
        direction_row = directional_stats.get(direction_bucket)
        if (
            getattr(config, "AUTO_DISABLE_NEGATIVE_BUCKETS", False)
            and (
                (
                    direction_row
                    and int(direction_row.get("count", 0)) >= int(getattr(config, "MIN_SAMPLE_FOR_GATING", 20))
                    and float(direction_row.get("pnl", 0.0)) < 0
                )
                or (
                    row
                    and int(row.get("count", 0)) >= int(getattr(config, "MIN_SAMPLE_FOR_GATING", 20))
                    and float(row.get("pnl", 0.0)) < 0
                )
            )
        ):
            _record_rejection(a, "negative_bucket_disabled")
            continue
        if _short_bucket_disable_reason(direction_bucket, trade_history, current_cycle):
            _record_rejection(a, "short_bucket_disabled")
            continue

        candidate_rows.append({
            "analysis": a,
            "direction": direction,
            "score": score,
            "tier": tier,
            "tier_mult": tier_mult,
            "ev_roi": ev_roi,
            "bucket": bucket,
            "direction_bucket": direction_bucket,
            "display_direction": normalized_direction,
            "reentry_parent_trade_id": reentry_parent_trade_id,
            "side_concentration_penalty_applied": side_penalty > 0,
        })

    candidate_rows.sort(key=lambda r: (r["score"], abs(float(r["analysis"]["edge"]))), reverse=True)
    top_n = int(getattr(config, "TOP_TRADES_PER_CYCLE", 2))
    selected = candidate_rows[:max(0, top_n)]

    remaining = bankroll.get_balance()
    trades: list[dict] = []
    crypto_count = 0
    crypto_direction_counts: dict[str, int] = {}
    for row in selected:
        if remaining < 0.01:
            break

        a = row["analysis"]
        if a.get("is_crypto_5min") and crypto_count >= config.CRYPTO_MAX_BETS_PER_CYCLE:
            _record_rejection(a, "crypto_max_bets_reached")
            continue
        if a.get("is_crypto_5min"):
            direction_count = crypto_direction_counts.get(row["display_direction"], 0)
            max_same_side = int(getattr(config, "CRYPTO_MAX_SAME_SIDE_BETS_PER_CYCLE", 1))
            if direction_count >= max_same_side:
                _record_rejection(a, "same_side_crypto_limit")
                continue

        if a.get("is_crypto_5min"):
            base_bet = round(remaining * config.CRYPTO_KELLY_FRACTION, 4)
        else:
            base_bet = _kelly_bet(float(a["edge"]), a["market_prob"], row["direction"], remaining, kelly_cap=config.MAX_KELLY_FRACTION)
        if base_bet < 0.01:
            _record_rejection(a, "bet_below_minimum")
            continue

        bet_size = round(base_bet * row["tier_mult"] * drawdown_mult, 4)
        if bet_size < 0.01:
            _record_rejection(a, "bet_below_minimum")
            continue

        ev = _expected_value(float(a["edge"]), a["market_prob"], row["direction"], bet_size)
        if ev <= 0:
            _record_rejection(a, "ev_non_positive_after_size")
            continue
        ev_roi = ev / bet_size if bet_size > 0 else 0.0

        trades.append({
            **a,
            "direction": row["direction"],
            "display_direction": row["display_direction"],
            "bet_size": bet_size,
            "projected_pnl": ev,
            "ev_roi": round(ev_roi, 4),
            "trade_score": row["score"],
            "quality_tier": row["tier"],
            "tier_size_multiplier": row["tier_mult"],
            "drawdown_size_multiplier": round(drawdown_mult, 4),
            "strategy_bucket": row["bucket"],
            "direction_bucket": row["direction_bucket"],
            "side_concentration_penalty_applied": row["side_concentration_penalty_applied"],
            "reentry_parent_trade_id": row["reentry_parent_trade_id"],
        })
        remaining = round(remaining - bet_size, 6)
        if a.get("is_crypto_5min"):
            crypto_count += 1
            crypto_direction_counts[row["display_direction"]] = crypto_direction_counts.get(row["display_direction"], 0) + 1

    return trades
