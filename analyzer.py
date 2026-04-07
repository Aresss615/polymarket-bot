import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
import config

_SYSTEM_PROMPT = """\
You are a quantitative prediction market trader. Your job is to refine market prices using your knowledge of crypto behaviour, not to replace them.

FRAMEWORK: Treat the market price as a Bayesian prior. Update it with evidence. Your final probability = 70% market anchor + 30% your adjustment.

WHEN TO FIND EDGE:
- Markets priced 35–65%: genuine uncertainty zone. Apply mean-reversion, volume signals, and crypto volatility patterns. These are your best opportunities.
- Markets priced 15–35% or 65–85%: market has a lean but may be over- or under-pricing. Adjust cautiously up to 12%.
- Markets priced below 15% or above 85%: strong market consensus. Only deviate up to 8% with a concrete reason.

CONFIDENCE:
- MEDIUM is your default. Use it whenever you have any reasonable basis to form a view.
- HIGH only when you have two or more corroborating signals.
- LOW only if you are truly unable to form any view (extremely rare).

Always respond with valid JSON in exactly this format:
{"probability": <float 0.0-1.0>, "confidence": "<low|medium|high>", "reasoning": "<2-3 sentences max>"}\
"""

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "probability": {
            "type": "number",
            "description": "Your estimated true probability that YES occurs (0.0 to 1.0)",
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "How confident you are in this estimate",
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of your reasoning (2-4 sentences)",
        },
    },
    "required": ["probability", "confidence", "reasoning"],
}


def analyze_market(client: OpenAI, market: dict) -> dict:
    """
    Send a single market to Gemini for probability estimation.
    Returns an analysis dict merged with market metadata.
    """
    user_prompt = (
        f"Market Question: {market['question']}\n"
        f"Outcomes: {market['outcomes']}\n"
        f"Current Market Price (YES): {market['yes_price']:.2%}\n"
        f"Market Liquidity: ${market['liquidity']:,.0f}\n"
        f"Trading Volume: ${market['volume']:,.0f}\n\n"
        f"Estimate the true probability that the YES outcome occurs."
    )

    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        max_tokens=config.MAX_TOKENS,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content
    # Strip markdown code fences if present
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(match.group() if match else raw)

    claude_prob = max(0.01, min(0.99, float(data["probability"])))
    edge = round(claude_prob - market["yes_price"], 4)

    return {
        "market_id": market["id"],
        "question": market["question"],
        "market_prob": market["yes_price"],
        "claude_prob": round(claude_prob, 4),
        "edge": edge,
        "confidence": data["confidence"],
        "reasoning": data["reasoning"],
    }


def _analyze_crypto_5min(market: dict) -> dict | None:
    """
    Use OKX/Bybit live price + momentum instead of LLM for 5-min crypto interval markets.
    Returns analysis dict (same shape as LLM output) or None if no clear signal.
    """
    import price_feed

    symbol = market["slug"].split("-")[0].upper()  # "btc-updown-5m-..." → "BTC"

    strike = _parse_strike_price(market["question"])
    if strike is None:
        return None

    live_price = price_feed.get_spot_price(symbol)
    if live_price is None:
        return None

    momentum = price_feed.get_momentum(symbol)
    if momentum == "UNCLEAR":
        return None

    price_diff_pct = (live_price - strike) / strike
    if abs(price_diff_pct) < config.CRYPTO_PRICE_BUFFER:
        return None  # too close to strike — noise risk

    price_signal = "UP" if live_price > strike else "DOWN"
    if price_signal != momentum:
        return None  # price and momentum disagree — skip

    # Both agree → high confidence bet
    market_prob = market["yes_price"]
    claude_prob = 0.85 if price_signal == "UP" else 0.15

    return {
        "market_id":      market["id"],
        "question":       market["question"],
        "market_prob":    market_prob,
        "claude_prob":    claude_prob,
        "edge":           claude_prob - market_prob,
        "confidence":     "high",
        "reasoning": (
            f"Live {symbol}=${live_price:.2f} vs strike=${strike:.2f} "
            f"({price_diff_pct:+.2%}), momentum={momentum}, "
            f"closes_in={market.get('seconds_to_close')}s"
        ),
        "end_date":       market.get("end_date"),
        "is_crypto_5min": True,
    }


def _parse_strike_price(question: str) -> float | None:
    """
    Extract dollar strike price from market question.
    Handles: "Will BTC be above $95,432.56 at 12:05?"
    """
    matches = re.findall(r'\$([0-9,]+(?:\.[0-9]+)?)', question)
    if not matches:
        return None
    try:
        return float(matches[0].replace(",", ""))
    except ValueError:
        return None


def analyze_markets(client: OpenAI, markets: list[dict]) -> list[dict]:
    """
    Split markets by type: crypto 5-min → price_feed path; all others → LLM path.
    Skips markets that fail without crashing the cycle.
    """
    results = []

    crypto_markets = [m for m in markets if m.get("is_crypto_5min")]
    llm_markets    = [m for m in markets if not m.get("is_crypto_5min")]

    # Fast path: price-feed + momentum for 5-min crypto (no LLM)
    for m in crypto_markets:
        result = _analyze_crypto_5min(m)
        if result:
            results.append(result)

    # Existing path: LLM for non-crypto / long-horizon
    if llm_markets:
        with ThreadPoolExecutor(max_workers=len(llm_markets)) as pool:
            futures = {pool.submit(analyze_market, client, m): m for m in llm_markets}
            for future in as_completed(futures):
                m = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    print(f"[analyzer] Skipping market {m.get('id', '?')} ({m.get('question', '')[:50]}): {e}")

    return results
