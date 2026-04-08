import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from openai import OpenAI

import config

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_WEAK_REASONING_TOKENS = (
    "unclear",
    "uncertain",
    "mixed",
    "balanced",
    "neutral",
    "no strong",
    "limited signal",
)
_LAST_SKIP_EVENTS: list[dict] = []

_SYSTEM_PROMPT = """\
You are a short-horizon prediction market trader.
Your goal is to produce evidence-driven probabilities without directional bias.

CORE RULES:
- Treat market price as a prior, but do not simply mirror it.
- Evaluate YES and NO symmetrically before choosing a side.
- Do not assume upside drift, bullish continuation, or mean-reversion bounces unless concrete evidence supports that exact direction.
- Move away from market price only when you can name specific directional evidence.
- If evidence is mixed or weak, stay closer to market price rather than leaning bullish by default.

CONFIDENCE:
- MEDIUM is default.
- HIGH when you can cite at least two coherent signals.
- LOW only when signal quality is genuinely poor.

REASONING STYLE:
- Mention one concrete reason for YES and one concrete reason for NO.
- State which side is stronger and why.
- Keep reasoning short and explicit.

Always respond with valid JSON in exactly this format:
{"probability": <float 0.0-1.0>, "confidence": "<low|medium|high>", "reasoning": "<2-3 sentences max>"}\
"""

_CRYPTO_WINDOW_PROMPT = """\
You trade crypto Up/Down interval markets from the underlying price path.

RULES:
- Decide direction from the underlying coin path first.
- Market implied probability is only a value filter. It must not change direction by itself.
- Focus on the active window from market start until now.
- Pay special attention to the last 60s, 30s, and 15s for reversal vs continuation.
- If the window is choppy or evidence is weak, return NO_TRADE.
- Do not mirror market sentiment.

Return valid JSON exactly in this shape:
{"direction":"UP|DOWN|NO_TRADE","probability_up":0.0,"confidence":"low|medium|high","pattern":"continuation|reversal|chop|breakout","reasoning":"2-3 short sentences"}
"""


def _clamp_probability(probability: float) -> float:
    return max(0.01, min(0.99, float(probability)))


def _record_skip(market: dict, reason: str, stage: str = "analysis") -> None:
    _LAST_SKIP_EVENTS.append({
        "market_id": market.get("id") or market.get("market_id"),
        "question": market.get("question", ""),
        "reason": reason,
        "stage": stage,
    })


def reset_skip_events() -> None:
    _LAST_SKIP_EVENTS.clear()


def get_skip_summary() -> dict[str, int]:
    counts = Counter()
    for event in _LAST_SKIP_EVENTS:
        counts[f"{event.get('stage', 'analysis')}:{event.get('reason', 'unknown')}"] += 1
    return dict(sorted(counts.items()))


def _parse_json_payload(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group() if match else raw)


def _normalize_confidence(confidence: str | None) -> str:
    value = (confidence or "medium").strip().lower()
    if value not in _CONFIDENCE_RANK:
        return "medium"
    return value


def _calibrate_llm_probability(
    market_prob: float,
    raw_probability: float,
    confidence: str,
    reasoning: str,
) -> tuple[float, float, float]:
    raw_probability = _clamp_probability(raw_probability)
    delta_before = raw_probability - float(market_prob)
    clamp_size = float(getattr(config, "DIRECTIONAL_DELTA_CLAMP", 0.08))
    clamped_delta = max(-clamp_size, min(clamp_size, delta_before))

    confidence = _normalize_confidence(confidence)
    shrink = {"high": 1.0, "medium": 0.85, "low": 0.55}.get(confidence, 0.75)
    if abs(clamped_delta) < 0.03:
        shrink *= 0.75

    reasoning_text = (reasoning or "").lower()
    if any(token in reasoning_text for token in _WEAK_REASONING_TOKENS):
        shrink *= 0.75

    delta_after = clamped_delta * shrink
    final_probability = _clamp_probability(float(market_prob) + delta_after)
    delta_after = final_probability - float(market_prob)
    return final_probability, delta_before, delta_after


def _parse_end_datetime(end_date: str | None) -> datetime | None:
    if not end_date:
        return None
    try:
        if end_date.endswith("Z"):
            end_date = end_date[:-1] + "+00:00"
        dt = datetime.fromisoformat(end_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def analyze_market(client: OpenAI, market: dict) -> dict:
    user_prompt = (
        f"Market Question: {market['question']}\n"
        f"Market Slug: {market.get('slug', '')}\n"
        f"Outcomes: {market['outcomes']}\n"
        f"Current Market Price (YES): {market['yes_price']:.2%}\n"
        f"Seconds To Close: {market.get('seconds_to_close')}\n"
        f"Market Liquidity: ${market['liquidity']:,.0f}\n"
        f"Trading Volume: ${market['volume']:,.0f}\n\n"
        f"Estimate the true probability that the YES outcome occurs.\n"
        f"Consider both sides fairly: give one brief YES case, one brief NO case, "
        f"then state which side is stronger. Avoid default bullish assumptions."
    )

    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        max_tokens=config.MAX_TOKENS,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    data = _parse_json_payload(response.choices[0].message.content)
    raw_prob = _clamp_probability(float(data["probability"]))
    claude_prob, delta_before, delta_after = _calibrate_llm_probability(
        market_prob=market["yes_price"],
        raw_probability=raw_prob,
        confidence=data["confidence"],
        reasoning=data["reasoning"],
    )
    edge = round(claude_prob - market["yes_price"], 4)

    return {
        "market_id": market["id"],
        "question": market["question"],
        "market_prob": market["yes_price"],
        "claude_prob": round(claude_prob, 4),
        "edge": edge,
        "confidence": data["confidence"],
        "reasoning": data["reasoning"],
        "is_crypto_5min": bool(market.get("is_crypto_5min")),
        "seconds_to_close": market.get("seconds_to_close"),
        "interval_minutes": market.get("interval_minutes"),
        "signal_source": "llm",
        "momentum_signal": None,
        "net_move_pct": None,
        "window_move_pct": None,
        "live_price": None,
        "strike_price": None,
        "cycle_phase": market.get("cycle_phase"),
        "boundary_time": market.get("boundary_time"),
        "llm_delta_before_clamp": round(delta_before, 4),
        "llm_delta_after_clamp": round(delta_after, 4),
        "market_implied_up_prob": market.get("market_implied_up_prob", market["yes_price"]),
        "probability_up": None,
        "predicted_direction": None,
        "display_direction": None,
        "pattern": None,
        "data_source": None,
        "window_start_price": None,
        "window_current_price": None,
        "window_high": None,
        "window_low": None,
        "last60_move_pct": None,
        "last30_move_pct": None,
        "last15_move_pct": None,
        "market_spread": market.get("market_spread"),
        "best_bid": market.get("best_bid"),
        "best_ask": market.get("best_ask"),
        "last_trade_price": market.get("last_trade_price"),
        "liquidity": market.get("liquidity"),
        "volume": market.get("volume"),
    }


def _parse_strike_price(question: str) -> float | None:
    matches = re.findall(r'\$([0-9,]+(?:\.[0-9]+)?)', question)
    if not matches:
        return None
    try:
        return float(matches[0].replace(",", ""))
    except ValueError:
        return None


def _prob_from_signal(direction: str, strength: str, strike_based: bool) -> float:
    if strike_based:
        levels = {"strong": 0.82, "medium": 0.72, "weak": 0.62}
    else:
        levels = {"strong": 0.74, "medium": 0.66, "weak": 0.58}
    up_prob = levels[strength]
    return up_prob if direction == "UP" else 1.0 - up_prob


def _build_crypto_result(
    market: dict,
    probability_up: float,
    confidence: str,
    reasoning: str,
    signal_source: str,
    predicted_direction: str,
    summary: dict | None,
    llm_meta: dict | None = None,
    momentum_signal: str | None = None,
) -> dict:
    up_index = market.get("up_outcome_index")
    if up_index not in {0, 1}:
        up_index = 0

    market_prob = float(market["yes_price"])
    market_implied_up_prob = float(market.get("market_implied_up_prob", market_prob if up_index == 0 else (1.0 - market_prob)))
    probability_up = _clamp_probability(probability_up)
    claude_prob = probability_up if up_index == 0 else (1.0 - probability_up)
    edge = round(claude_prob - market_prob, 4)

    result = {
        "market_id": market["id"],
        "question": market["question"],
        "market_prob": market_prob,
        "claude_prob": round(claude_prob, 4),
        "edge": edge,
        "confidence": confidence,
        "reasoning": reasoning,
        "end_date": market.get("end_date"),
        "is_crypto_5min": bool(market.get("is_crypto_5min")),
        "seconds_to_close": market.get("seconds_to_close"),
        "interval_minutes": market.get("interval_minutes"),
        "signal_source": signal_source,
        "momentum_signal": momentum_signal or predicted_direction,
        "net_move_pct": summary.get("window_move_pct") if summary else None,
        "window_move_pct": summary.get("window_move_pct") if summary else None,
        "live_price": summary.get("window_current_price") if summary else None,
        "strike_price": None,
        "cycle_phase": market.get("cycle_phase"),
        "boundary_time": market.get("boundary_time"),
        "llm_delta_before_clamp": llm_meta.get("delta_before") if llm_meta else None,
        "llm_delta_after_clamp": llm_meta.get("delta_after") if llm_meta else None,
        "market_implied_up_prob": round(market_implied_up_prob, 4),
        "probability_up": round(probability_up, 4),
        "predicted_direction": predicted_direction,
        "display_direction": f"BUY_{predicted_direction}",
        "pattern": (summary or {}).get("pattern"),
        "data_source": (summary or {}).get("data_source"),
        "window_start_price": (summary or {}).get("window_start_price"),
        "window_current_price": (summary or {}).get("window_current_price"),
        "window_high": (summary or {}).get("window_high"),
        "window_low": (summary or {}).get("window_low"),
        "last60_move_pct": (summary or {}).get("last60_move_pct"),
        "last30_move_pct": (summary or {}).get("last30_move_pct"),
        "last15_move_pct": (summary or {}).get("last15_move_pct"),
        "market_spread": market.get("market_spread"),
        "best_bid": market.get("best_bid"),
        "best_ask": market.get("best_ask"),
        "last_trade_price": market.get("last_trade_price"),
        "liquidity": market.get("liquidity"),
        "volume": market.get("volume"),
    }
    return result


def _heuristic_crypto_window_decision(summary: dict) -> dict:
    min_move = float(getattr(config, "WINDOW_MOVE_MIN", 0.0001))
    window_move = float(summary.get("window_move_pct") or 0.0)
    last30 = float(summary.get("last30_move_pct") or 0.0)
    last15 = float(summary.get("last15_move_pct") or 0.0)
    pattern = summary.get("pattern") or "chop"

    if pattern == "chop" and abs(window_move) < (min_move * 1.5):
        return {
            "direction": "NO_TRADE",
            "probability_up": 0.5,
            "confidence": "low",
            "pattern": "chop",
            "reasoning": "The active window is choppy and the late path is not directional enough.",
        }

    if pattern == "reversal":
        direction = "UP" if last15 > 0 or last30 > 0 else "DOWN"
        probability_up = 0.42 if direction == "DOWN" else 0.58
        return {
            "direction": direction,
            "probability_up": probability_up,
            "confidence": "medium",
            "pattern": "reversal",
            "reasoning": "Late-window move is reversing the earlier path into the close.",
        }

    direction = "UP" if window_move >= 0 else "DOWN"
    confidence = "high" if abs(window_move) >= (min_move * 4) and summary.get("completeness") == "full" else "medium"
    base_prob = 0.70 if confidence == "high" else 0.62
    if direction == "DOWN":
        probability_up = 1.0 - base_prob
    else:
        probability_up = base_prob
    return {
        "direction": direction,
        "probability_up": probability_up,
        "confidence": confidence,
        "pattern": pattern if pattern in {"continuation", "breakout"} else "continuation",
        "reasoning": "Underlying price path is directionally aligned into the close.",
    }


def _build_crypto_window_prompt(market: dict, symbol: str, summary: dict) -> str:
    return (
        f"Symbol: {symbol}\n"
        f"Question: {market['question']}\n"
        f"Window start price: {summary.get('window_start_price')}\n"
        f"Current price: {summary.get('window_current_price')}\n"
        f"Window high: {summary.get('window_high')}\n"
        f"Window low: {summary.get('window_low')}\n"
        f"Full-window move: {summary.get('window_move_pct')}\n"
        f"Last 60s move: {summary.get('last60_move_pct')}\n"
        f"Last 30s move: {summary.get('last30_move_pct')}\n"
        f"Last 15s move: {summary.get('last15_move_pct')}\n"
        f"Distance from high: {summary.get('distance_from_high_pct')}\n"
        f"Distance from low: {summary.get('distance_from_low_pct')}\n"
        f"Heuristic pattern: {summary.get('pattern')}\n"
        f"Data source: {summary.get('data_source')}\n"
        f"Data completeness: {summary.get('completeness')}\n"
        f"Current implied UP probability: {market.get('market_implied_up_prob', market['yes_price'])}\n"
        f"Current market spread: {market.get('market_spread')}\n"
        f"Current market last trade price: {market.get('last_trade_price')}\n"
        f"Seconds to close: {market.get('seconds_to_close')}\n\n"
        "Decide whether the coin is finishing this active window UP or DOWN from the underlying path. "
        "Only use market implied probability to judge whether the market is underpricing or overpricing that direction. "
        "If the path is noisy, choose NO_TRADE."
    )


def _analyze_crypto_window_with_reason(client: OpenAI | None, market: dict) -> tuple[dict | None, str | None]:
    import price_feed

    if (
        int(market.get("interval_minutes") or 5) == 5
        and getattr(config, "CRYPTO_5M_EXECUTE_ONLY_ON_T30", True)
        and market.get("cycle_phase") != "t30"
    ):
        return None, "observe_only_phase"

    symbol = market["slug"].split("-")[0].upper()
    end_dt = _parse_end_datetime(market.get("end_date"))
    if end_dt is None:
        return None, "no_end_date"

    now = datetime.now(timezone.utc)
    window_start = end_dt - timedelta(minutes=int(market.get("interval_minutes") or 5))
    summary = price_feed.get_window_summary(symbol, window_start=window_start, current_time=now)
    if not summary:
        return None, "insufficient_window_data"

    spread = market.get("market_spread")
    if spread is not None and float(spread) > float(getattr(config, "CRYPTO_MAX_MARKET_SPREAD", 0.15)):
        return None, "spread_too_wide"

    heuristic = _heuristic_crypto_window_decision(summary)
    decision = heuristic
    llm_meta = None
    signal_source = "underlying_window_heuristic"

    if client is not None:
        try:
            response = client.chat.completions.create(
                model=config.MODEL_NAME,
                max_tokens=config.MAX_TOKENS,
                messages=[
                    {"role": "system", "content": _CRYPTO_WINDOW_PROMPT},
                    {"role": "user", "content": _build_crypto_window_prompt(market, symbol, summary)},
                ],
            )
            data = _parse_json_payload(response.choices[0].message.content)
            decision = {
                "direction": str(data.get("direction") or "NO_TRADE").upper(),
                "probability_up": float(data.get("probability_up", heuristic["probability_up"])),
                "confidence": _normalize_confidence(data.get("confidence")),
                "pattern": str(data.get("pattern") or summary.get("pattern") or heuristic["pattern"]).lower(),
                "reasoning": str(data.get("reasoning") or heuristic["reasoning"]),
            }
            signal_source = "underlying_window_llm"
            llm_meta = {"delta_before": None, "delta_after": None}
        except Exception:
            decision = heuristic
            signal_source = "underlying_window_heuristic"

    direction = decision.get("direction", "NO_TRADE")
    if direction not in {"UP", "DOWN"}:
        return None, "no_trade_model"

    confidence = _normalize_confidence(decision.get("confidence"))
    if summary.get("completeness") != "full" and confidence == "high":
        confidence = "medium"

    probability_up = _clamp_probability(float(decision.get("probability_up", heuristic["probability_up"])))
    if direction == "UP" and probability_up < 0.5:
        probability_up = 0.55
    if direction == "DOWN" and probability_up > 0.5:
        probability_up = 0.45

    summary = dict(summary)
    summary["pattern"] = decision.get("pattern") or summary.get("pattern")
    result = _build_crypto_result(
        market=market,
        probability_up=probability_up,
        confidence=confidence,
        reasoning=str(decision.get("reasoning") or heuristic["reasoning"]),
        signal_source=signal_source,
        predicted_direction=direction,
        summary=summary,
        llm_meta=llm_meta,
    )
    return result, None


def _analyze_crypto_interval_legacy_with_reason(market: dict) -> tuple[dict | None, str | None]:
    import price_feed

    symbol = market["slug"].split("-")[0].upper()
    strike = _parse_strike_price(market["question"])
    market_prob = float(market["yes_price"])
    interval_minutes = int(market.get("interval_minutes") or 5)

    def _fallback_direction_if_unclear() -> tuple[str | None, float | None, str]:
        net_move = price_feed.get_net_move_pct(symbol)
        if net_move is None:
            last_candle_move = price_feed.get_last_candle_move_pct(symbol)
            if last_candle_move is None:
                return None, None, "no_net_move"
            if last_candle_move > 0:
                direction = "UP"
            elif last_candle_move < 0:
                direction = "DOWN"
            else:
                return None, last_candle_move, "flat_last_candle"
            if abs(last_candle_move) >= float(getattr(config, "T15_LAST_CANDLE_MOVE_MIN", 0.00003)):
                return direction, last_candle_move, "last_candle_micro"
            return direction, last_candle_move, "last_candle_too_small"
        if net_move > 0:
            direction = "UP"
        elif net_move < 0:
            direction = "DOWN"
        else:
            return None, net_move, "flat_net_move"
        if abs(net_move) >= config.MOMENTUM_NET_MOVE_FALLBACK:
            return direction, net_move, "net_move_strong"
        return direction, net_move, "net_move_weak"

    def _allow_t30_weak_signal(net_move: float | None) -> bool:
        try:
            seconds_to_close = int(market.get("seconds_to_close") or 9999)
        except (TypeError, ValueError):
            return False
        if seconds_to_close > int(getattr(config, "SECOND_CHANCE_SECONDS", 15)):
            return False
        if net_move is None:
            return False
        return abs(net_move) >= float(getattr(config, "T15_WEAK_NET_MOVE_MIN", 0.00005))

    def _allow_t30_tail_continuation() -> bool:
        if not getattr(config, "T15_TAIL_CONTINUATION_ENABLED", True):
            return False
        try:
            seconds_to_close = int(market.get("seconds_to_close") or 9999)
        except (TypeError, ValueError):
            return False
        if seconds_to_close > int(getattr(config, "SECOND_CHANCE_SECONDS", 15)):
            return False
        cutoff = float(getattr(config, "CRYPTO_TAIL_MARKET_PROB_CUTOFF", 0.05))
        return market_prob <= cutoff or market_prob >= (1.0 - cutoff)

    if strike is not None:
        live_price = price_feed.get_spot_price(symbol)
        if live_price is None:
            return None, "spot_price_unavailable"
        direction = "UP" if live_price > strike else "DOWN"
        probability_up = 0.66 if direction == "UP" else 0.34
        summary = {
            "window_move_pct": (live_price - strike) / strike,
            "window_current_price": live_price,
            "window_start_price": strike,
            "window_high": max(live_price, strike),
            "window_low": min(live_price, strike),
            "last60_move_pct": None,
            "last30_move_pct": None,
            "last15_move_pct": None,
            "pattern": "continuation",
            "data_source": "exchange_fallback",
        }
        return _build_crypto_result(
            market,
            probability_up=probability_up,
            confidence="medium",
            reasoning=f"Legacy strike comparison: live {symbol}={live_price:.2f} vs strike {strike:.2f}.",
            signal_source="legacy_price_signal",
            predicted_direction=direction,
            summary=summary,
        ), None

    is_near_certain = market_prob >= config.CRYPTO_NEAR_CERTAIN_UPPER or market_prob <= config.CRYPTO_NEAR_CERTAIN_LOWER
    if is_near_certain and not _allow_t30_tail_continuation():
        return None, "market_near_certain"

    window_move = price_feed.get_window_move_pct(symbol, minutes=interval_minutes)
    if window_move is not None and abs(window_move) >= float(getattr(config, "WINDOW_MOVE_MIN", 0.0001)):
        direction = "UP" if window_move > 0 else "DOWN"
        probability_up = 0.66 if direction == "UP" else 0.34
        summary = {
            "window_move_pct": window_move,
            "window_current_price": price_feed.get_spot_price(symbol),
            "window_start_price": None,
            "window_high": None,
            "window_low": None,
            "last60_move_pct": None,
            "last30_move_pct": None,
            "last15_move_pct": None,
            "pattern": "continuation",
            "data_source": "exchange_fallback",
        }
        return _build_crypto_result(
            market,
            probability_up=probability_up,
            confidence="medium",
            reasoning=f"Legacy window-move fallback: {symbol} moved {window_move:+.2%} over the recent window.",
            signal_source="legacy_window_move",
            predicted_direction=direction,
            summary=summary,
        ), None

    direction, net_move, fallback_strength = _fallback_direction_if_unclear()
    if direction is None and _allow_t30_tail_continuation():
        tail_step = float(getattr(config, "T15_TAIL_PROB_STEP", 0.01))
        if market.get("market_implied_up_prob", market_prob) <= float(getattr(config, "CRYPTO_TAIL_MARKET_PROB_CUTOFF", 0.05)):
            probability_up = max(0.001, float(market.get("market_implied_up_prob", market_prob)) - tail_step)
            direction = "DOWN"
        else:
            probability_up = min(0.999, float(market.get("market_implied_up_prob", market_prob)) + tail_step)
            direction = "UP"
        summary = {
            "window_move_pct": net_move,
            "window_current_price": price_feed.get_spot_price(symbol),
            "window_start_price": None,
            "window_high": None,
            "window_low": None,
            "last60_move_pct": None,
            "last30_move_pct": None,
            "last15_move_pct": None,
            "pattern": "continuation",
            "data_source": "exchange_fallback",
        }
        return _build_crypto_result(
            market,
            probability_up=probability_up,
            confidence="medium",
            reasoning=f"Legacy tail continuation fallback: {symbol} market already sits at an extreme into close.",
            signal_source="market_tail_continuation",
            predicted_direction=direction,
            summary=summary,
        ), None

    if direction is None:
        return None, "momentum_unclear"

    if fallback_strength == "net_move_strong":
        probability_up = 0.58 if direction == "UP" else 0.42
        signal_source = "momentum+net_move_fallback"
    elif _allow_t30_weak_signal(net_move):
        probability_up = 0.55 if direction == "UP" else 0.45
        signal_source = "momentum+t30_weak_fallback"
    else:
        return None, "momentum_unclear"

    summary = {
        "window_move_pct": net_move,
        "window_current_price": price_feed.get_spot_price(symbol),
        "window_start_price": None,
        "window_high": None,
        "window_low": None,
        "last60_move_pct": None,
        "last30_move_pct": None,
        "last15_move_pct": None,
        "pattern": "continuation",
        "data_source": "exchange_fallback",
    }
    return _build_crypto_result(
        market,
        probability_up=probability_up,
        confidence="medium",
        reasoning=f"Legacy momentum fallback: {symbol} direction={direction} via {fallback_strength}.",
        signal_source=signal_source,
        predicted_direction=direction,
        summary=summary,
    ), None


def _analyze_crypto_5min_with_reason(market: dict, client: OpenAI | None = None) -> tuple[dict | None, str | None]:
    interval_minutes = int(market.get("interval_minutes") or 5)
    if interval_minutes == 5 and _parse_strike_price(market.get("question", "")) is None:
        result, reason = _analyze_crypto_window_with_reason(client, market)
        if result or reason not in {"insufficient_window_data", "crypto_llm_error"}:
            return result, reason
    return _analyze_crypto_interval_legacy_with_reason(market)


def _analyze_crypto_5min(market: dict, client: OpenAI | None = None) -> dict | None:
    result, _ = _analyze_crypto_5min_with_reason(market, client=client)
    return result


def analyze_markets(client: OpenAI, markets: list[dict]) -> list[dict]:
    results = []
    reset_skip_events()

    crypto_markets = [m for m in markets if m.get("is_crypto_5min")]
    llm_markets = [m for m in markets if not m.get("is_crypto_5min")]

    for m in crypto_markets:
        result, skip_reason = _analyze_crypto_5min_with_reason(m, client=client)
        if result:
            results.append(result)
        else:
            _record_skip(m, skip_reason or "unknown", stage="analysis")
            print(
                "[analyzer] Skipped crypto market "
                f"{m.get('id', '?')} ({m.get('question', '')[:60]}) "
                f"reason={skip_reason} yes_price={m.get('yes_price')} "
                f"seconds_to_close={m.get('seconds_to_close')}"
            )

    if llm_markets:
        with ThreadPoolExecutor(max_workers=len(llm_markets)) as pool:
            futures = {pool.submit(analyze_market, client, m): m for m in llm_markets}
            for future in as_completed(futures):
                m = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    _record_skip(m, "llm_error", stage="analysis")
                    print(f"[analyzer] Skipping market {m.get('id', '?')} ({m.get('question', '')[:50]}): {exc}")

    return results
