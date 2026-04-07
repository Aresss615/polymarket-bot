import requests
import config
from datetime import datetime, timedelta, timezone


def fetch_active_markets() -> list[dict]:
    """Fetch active binary markets from Gamma API, filtered by liquidity and resolve window."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=config.MAX_DAYS_TO_RESOLVE)
    params = {
        "active": "true",
        "closed": "false",
        "limit": 250,  # over-fetch; we filter by date and keywords in Python
        "liquidity_num_min": config.MIN_LIQUIDITY,
        "order": "endDate",
        "ascending": "true",
        "end_date_min": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date_max": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    """Fetch the midpoint price for a token from the CLOB API. Returns 0.0–1.0 or None."""
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


def _parse_end_date(end_date: str | None) -> datetime | None:
    """Parse an end date string into a timezone-aware datetime, or return None."""
    if not end_date:
        return None
    try:
        if end_date.endswith("Z"):
            end_date = end_date[:-1] + "+00:00"
        dt = datetime.fromisoformat(end_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def enrich_markets(markets: list[dict]) -> list[dict]:
    """
    Enrich raw Gamma markets with CLOB prices and end date.
    Filters to MAX_DAYS_TO_RESOLVE window in Python (API param unreliable).
    Returns a clean, normalized list of market dicts.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=config.MAX_DAYS_TO_RESOLVE)

    n_excluded = n_no_date = n_too_far = 0

    enriched = []
    for m in markets:
        try:
            # --- Keyword filtering ---
            question = (m.get("question") or "").lower()
            slug = (m.get("slug") or "").lower()
            text = question + " " + slug

            excluded = any(kw.lower() in text for kw in config.MARKET_EXCLUDE_KEYWORDS)
            if excluded:
                n_excluded += 1
                continue

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
                yes_price = float(m.get("bestBid") or m.get("lastTradePrice") or 0.5)

            no_price = round(1.0 - yes_price, 4)

            # End date — try multiple field names Gamma API uses
            end_date = m.get("endDateIso") or m.get("endDate") or None

            # Skip markets with no end date or outside the 0-7 day resolve window
            dt = _parse_end_date(end_date)
            if dt is None:
                n_no_date += 1
                continue
            if dt > cutoff:
                n_too_far += 1
                continue  # too far out

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
                "end_date": end_date,
            })
        except Exception as e:
            print(f"[fetcher] Skipping market {m.get('id', '?')}: {e}")

    print(
        f"[fetcher] raw={len(markets)} | excluded_sport={n_excluded} "
        f"no_date={n_no_date} too_far={n_too_far} | passed={len(enriched)}"
    )
    return enriched[:config.MAX_MARKETS_PER_CYCLE]


def get_markets() -> list[dict]:
    """Top-level function: fetch and enrich active markets."""
    raw = fetch_active_markets()
    return enrich_markets(raw)
