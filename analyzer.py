import anthropic
import config

_SYSTEM_PROMPT = """\
You are a calibrated probability estimator for prediction markets. Your job is to estimate the TRUE probability of events, independent of current market prices.

Rules:
- Base your estimate on publicly available information up to your knowledge cutoff.
- Be calibrated: when you say 70%, events should happen ~70% of the time.
- State "low" confidence when you lack domain knowledge or the question is highly uncertain.
- Do NOT anchor to the market price provided — form your own independent estimate first.
- Keep reasoning concise: 2-4 sentences covering the key factors.\
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


def analyze_market(client: anthropic.Anthropic, market: dict) -> dict:
    """
    Send a single market to Claude for probability estimation.
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

    response = client.messages.create(
        model=config.MODEL_NAME,
        max_tokens=config.MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        betas=["structured-outputs-2025-11-13"],
        output_config={"format": "json", "schema": _ANALYSIS_SCHEMA},  # type: ignore[call-overload]
    )

    result = response.content[0].text  # type: ignore[union-attr]
    import json
    data = json.loads(result)

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


def analyze_markets(client: anthropic.Anthropic, markets: list[dict]) -> list[dict]:
    """
    Analyze each market. Skips markets that fail without crashing the cycle.
    """
    analyses = []
    for market in markets:
        try:
            analysis = analyze_market(client, market)
            analyses.append(analysis)
        except Exception as e:
            print(f"[analyzer] Skipping market {market.get('id', '?')} ({market.get('question', '')[:50]}): {e}")
    return analyses
