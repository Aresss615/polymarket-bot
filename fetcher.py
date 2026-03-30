import requests
import config


def fetch_active_markets() -> list[dict]:
    """Fetch active binary markets from Gamma API, filtered by liquidity."""
    params = {
        "active": "true",
        "closed": "false",
        "limit": config.MAX_MARKETS_PER_CYCLE,
        "liquidity_num_min": config.MIN_LIQUIDITY,
        "order": "volume",
        "ascending": "false",
    }
    resp = requests.get(
        f"{config.GAMMA_API_URL}/markets",
        params=params,
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    markets = resp.json()

    # Keep only binary (Yes/No) markets with token data
    binary = []
    for m in markets:
        outcomes = m.get("outcomes", [])
        tokens = m.get("clobTokenIds") or m.get("tokens") or []
        # outcomes can be a JSON string or a list
        if isinstance(outcomes, str):
            import json as _json
            try:
                outcomes = _json.loads(outcomes)
            except Exception:
                continue
        if len(outcomes) == 2 and tokens:
            m["_outcomes_parsed"] = outcomes
            binary.append(m)

    return binary


def fetch_market_price(token_id: str) -> float | None:
    """Fetch the midpoint price for a token from the CLOB API. Returns 0.0–1.0 or None on error."""
    try:
        resp = requests.get(
            f"{config.CLOB_API_URL}/midpoint",
            params={"token_id": token_id},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("mid", 0.5))
    except Exception:
        return None


def enrich_markets(markets: list[dict]) -> list[dict]:
    """
    Enrich raw Gamma markets with CLOB prices.
    Returns a clean, normalized list of market dicts.
    """
    enriched = []
    for m in markets:
        try:
            tokens = m.get("clobTokenIds") or []
            if isinstance(tokens, str):
                import json as _json
                try:
                    tokens = _json.loads(tokens)
                except Exception:
                    tokens = []

            outcomes = m.get("_outcomes_parsed", [])

            yes_token_id = tokens[0] if len(tokens) > 0 else None
            no_token_id = tokens[1] if len(tokens) > 1 else None

            yes_price = fetch_market_price(yes_token_id) if yes_token_id else None
            if yes_price is None:
                # Fall back to Gamma API price fields
                yes_price = float(m.get("bestBid") or m.get("lastTradePrice") or 0.5)

            no_price = round(1.0 - yes_price, 4)

            enriched.append({
                "id": m.get("id", ""),
                "slug": m.get("slug", ""),
                "question": m.get("question", ""),
                "outcomes": outcomes,
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
                "yes_price": round(yes_price, 4),
                "no_price": no_price,
                "liquidity": float(m.get("liquidityNum") or m.get("liquidity") or 0),
                "volume": float(m.get("volumeNum") or m.get("volume") or 0),
            })
        except Exception as e:
            print(f"[fetcher] Skipping market {m.get('id', '?')}: {e}")

    return enriched


def get_markets() -> list[dict]:
    """Top-level function: fetch and enrich active markets."""
    raw = fetch_active_markets()
    return enrich_markets(raw)
