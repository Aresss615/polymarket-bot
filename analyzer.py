import json

from openai import OpenAI
import config

_SYSTEM_PROMPT = """\
You are an expert crypto and financial markets trader with deep knowledge of Bitcoin, Ethereum, altcoins, DeFi, macro economics, interest rates, equities, and ETFs. You specialize in short-term prediction markets and have a strong track record of identifying mispricings.

Your job is to estimate the TRUE probability of events, independent of current market prices, using your expertise in:
- Crypto: on-chain data patterns, BTC halving cycles, ETF flows, regulatory trends, exchange dynamics
- Macro: Fed rate decisions, CPI prints, employment data, yield curve behavior
- Equities: earnings momentum, sector rotation, index rebalancing effects
- Market microstructure: liquidity, sentiment extremes, and mean-reversion tendencies

Rules:
- Do NOT anchor to the market price — form your independent estimate first, then note if there's a significant gap.
- Be decisive: lean toward high confidence when your domain expertise clearly applies.
- For crypto/financial questions, draw on price cycle history, macro context, and on-chain fundamentals.
- For uncertain or non-financial questions, state "low" confidence.
- Keep reasoning concise: 2-4 sentences on the key factors driving your estimate.

Always respond with valid JSON in exactly this format:
{"probability": <float 0.0-1.0>, "confidence": "<low|medium|high>", "reasoning": "<2-4 sentences>"}\
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
        response_format={"type": "json_object"},
    )

    data = json.loads(response.choices[0].message.content)

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


def analyze_markets(client: OpenAI, markets: list[dict]) -> list[dict]:
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
