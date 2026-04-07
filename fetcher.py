import re
import requests
import config
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

_CRYPTO_INTERVAL_SLUG = re.compile(
    r'^(btc|eth|sol|bnb|xrp|doge|avax|link|matic|ada|op|arb)-updown-\d+m-\d+$'
)

def _is_crypto_5min(slug: str) -> bool:
    return bool(_CRYPTO_INTERVAL_SLUG.match((slug or "").lower()))


def fetch_active_markets() -> list[dict]:
    """Fetch active binary markets from Gamma API, filtered by liquidity and resolve window."""
    now = datetime.now(timezone.utc)
    if getattr(config, "CRYPTO_5MIN_ENABLED", False):
        floor  = now + timedelta(seconds=config.MIN_SECONDS_TO_CLOSE)
        cutoff = now + timedelta(seconds=config.MAX_SECONDS_TO_CLOSE)
    else:
        min_minutes = getattr(config, "MIN_MINUTES_TO_RESOLVE", 0)
        floor = now + timedelta(minutes=min_minutes) if min_minutes else now
        max_minutes = getattr(config, "MAX_MINUTES_TO_RESOLVE", None)
        cutoff = now + timedelta(minutes=max_minutes) if max_minutes else now + timedelta(days=config.MAX_DAYS_TO_RESOLVE)
    params = {
        "active": "true",
        "closed": "false",
        "limit": 250,  # over-fetch; we filter by date and keywords in Python
        "liquidity_num_min": config.MIN_LIQUIDITY,
        "order": "endDate",
        "ascending": "true",
        "end_date_min": floor.strftime("%Y-%m-%dT%H:%M:%SZ"),
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


def _enrich_one(m: dict, now: datetime, cutoff: datetime) -> tuple[dict | None, str | None]:
    """
    Enrich a single market dict with its CLOB price.
    Returns (enriched_dict, skip_reason) where skip_reason is one of
    'excluded', 'no_date', 'too_far', or None (success).
    """
    import json as _json

    try:
        question = (m.get("question") or "").lower()
        slug = (m.get("slug") or "").lower()
        text = question + " " + slug

        if any(kw.lower() in text for kw in config.MARKET_EXCLUDE_KEYWORDS):
            return None, "excluded"

        focus = getattr(config, "MARKET_FOCUS_KEYWORDS", [])
        if focus and not any(kw.lower() in text for kw in focus):
            return None, "excluded"

        tokens = m.get("clobTokenIds") or []
        if isinstance(tokens, str):
            try:
                tokens = _json.loads(tokens)
            except Exception:
                tokens = []

        outcomes = m.get("_outcomes_parsed", [])
        yes_token_id = tokens[0] if len(tokens) > 0 else None
        no_token_id = tokens[1] if len(tokens) > 1 else None

        end_date = m.get("endDateIso") or m.get("endDate") or None
        dt = _parse_end_date(end_date)
        if dt is None:
            return None, "no_date"
        if dt > cutoff:
            return None, "too_far"
        seconds_to_close = max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
        if getattr(config, "CRYPTO_5MIN_ENABLED", False):
            if seconds_to_close < config.MIN_SECONDS_TO_CLOSE:
                return None, "too_soon"
        else:
            min_minutes = getattr(config, "MIN_MINUTES_TO_RESOLVE", 0)
            if min_minutes and dt < now + timedelta(minutes=min_minutes):
                return None, "too_soon"

        yes_price = fetch_market_price(yes_token_id) if yes_token_id else None
        if yes_price is None:
            yes_price = float(m.get("bestBid") or m.get("lastTradePrice") or 0.5)

        return {
            "id": m.get("id", ""),
            "slug": m.get("slug", ""),
            "question": m.get("question", ""),
            "outcomes": outcomes,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
            "yes_price": round(yes_price, 4),
            "no_price": round(1.0 - yes_price, 4),
            "liquidity": float(m.get("liquidityNum") or m.get("liquidity") or 0),
            "volume": float(m.get("volumeNum") or m.get("volume") or 0),
            "end_date": end_date,
            "seconds_to_close": seconds_to_close,
            "is_crypto_5min": _is_crypto_5min(m.get("slug", "")),
        }, None
    except Exception as e:
        print(f"[fetcher] Skipping market {m.get('id', '?')}: {e}")
        return None, "error"


def enrich_markets(markets: list[dict]) -> list[dict]:
    """
    Enrich raw Gamma markets with CLOB prices and end date.
    Filters to MAX_DAYS_TO_RESOLVE window in Python (API param unreliable).
    Fetches CLOB prices in parallel to reduce latency.
    Returns a clean, normalized list of market dicts.
    """
    now = datetime.now(timezone.utc)
    if getattr(config, "CRYPTO_5MIN_ENABLED", False):
        cutoff = now + timedelta(seconds=config.MAX_SECONDS_TO_CLOSE)
    else:
        minutes = getattr(config, "MAX_MINUTES_TO_RESOLVE", None)
        cutoff = now + timedelta(minutes=minutes) if minutes is not None else now + timedelta(days=config.MAX_DAYS_TO_RESOLVE)

    n_excluded = n_no_date = n_too_far = n_too_soon = 0
    enriched = []

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_enrich_one, m, now, cutoff): m for m in markets}
        for future in as_completed(futures):
            result, skip_reason = future.result()
            if skip_reason == "excluded":
                n_excluded += 1
            elif skip_reason == "no_date":
                n_no_date += 1
            elif skip_reason == "too_far":
                n_too_far += 1
            elif skip_reason == "too_soon":
                n_too_soon += 1
            elif result is not None:
                enriched.append(result)

    # Restore original ordering (futures complete out of order)
    order = {m.get("id", ""): i for i, m in enumerate(markets)}
    enriched.sort(key=lambda m: order.get(m["id"], 0))

    print(
        f"[fetcher] raw={len(markets)} | excluded={n_excluded} "
        f"too_soon={n_too_soon} no_date={n_no_date} too_far={n_too_far} | passed={len(enriched)}"
    )
    return enriched[:config.MAX_MARKETS_PER_CYCLE]


def get_markets() -> list[dict]:
    """Top-level function: fetch and enrich active markets."""
    raw = fetch_active_markets()
    return enrich_markets(raw)
