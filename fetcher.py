import re
import requests
import config
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

_ANY_CRYPTO_UPDOWN_SLUG = re.compile(
    r'^(btc|eth|sol|bnb|xrp|doge|avax|link|matic|ada|op|arb|ltc|dot|trx|ton|shib|pepe|sui|apt|sei)-updown-(\d+)m-\d+$'
)


def _up_outcome_index(question: str, slug: str, outcomes: list[str]) -> int | None:
    labels = [str(outcome).strip().lower() for outcome in outcomes]
    for idx, label in enumerate(labels):
        if "up" in label:
            return idx
    for idx, label in enumerate(labels):
        if "down" in label:
            return 1 - idx if len(labels) == 2 else None
    if "-updown-" in (slug or "").lower() or "up or down" in (question or "").lower():
        return 0
    return None

def _is_crypto_5min(slug: str) -> bool:
    match = _ANY_CRYPTO_UPDOWN_SLUG.match((slug or "").lower())
    return bool(match and int(match.group(2)) in {5, 15})


def _crypto_interval_minutes(slug: str) -> int | None:
    match = _ANY_CRYPTO_UPDOWN_SLUG.match((slug or "").lower())
    if not match:
        return None
    return int(match.group(2))


def _crypto_max_seconds_to_close(interval_minutes: int | None, cycle_phase: str | None = None) -> int:
    """Dynamic late-entry window based on interval duration and phase."""
    if interval_minutes is None:
        base = config.MAX_SECONDS_TO_CLOSE
    else:
        table = getattr(config, "CRYPTO_INTERVAL_ENTRY_SECONDS", {}) or {}
        if interval_minutes in table:
            base = int(table[interval_minutes])
        else:
            base = config.MAX_SECONDS_TO_CLOSE
    if cycle_phase == "t30":
        return min(base, int(getattr(config, "SECOND_CHANCE_SECONDS", 30)))
    if cycle_phase == "t45":
        return min(base, int(getattr(config, "SECONDS_BEFORE_CLOSE", 45)))
    return base


def fetch_active_markets() -> list[dict]:
    """Fetch active binary markets from Gamma API, filtered by liquidity and resolve window."""
    now = datetime.now(timezone.utc)
    if getattr(config, "CRYPTO_5MIN_ENABLED", False):
        # Combined API window: keep both crypto-seconds and non-crypto-minute candidates.
        min_minutes = getattr(config, "MIN_MINUTES_TO_RESOLVE", 0)
        max_minutes = getattr(config, "MAX_MINUTES_TO_RESOLVE", None)
        floor = now + timedelta(seconds=min(config.MIN_SECONDS_TO_CLOSE, min_minutes * 60 if min_minutes else config.MIN_SECONDS_TO_CLOSE))
        if max_minutes:
            cutoff_seconds = max(config.MAX_SECONDS_TO_CLOSE, max_minutes * 60)
            cutoff = now + timedelta(seconds=cutoff_seconds)
        else:
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
        mid = float(data.get("mid") or 0)
        return mid if mid > 0 else None
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


def _enrich_one(m: dict, now: datetime, cycle_phase: str | None = None) -> tuple[dict | None, str | None]:
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

        any_crypto_updown = _ANY_CRYPTO_UPDOWN_SLUG.match(slug)
        interval_minutes = _crypto_interval_minutes(slug)
        configured_crypto_intervals = set((getattr(config, "CRYPTO_INTERVAL_ENTRY_SECONDS", {}) or {}).keys())
        if any_crypto_updown and interval_minutes not in configured_crypto_intervals:
            return None, "excluded"

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
        up_outcome_index = _up_outcome_index(m.get("question", ""), slug, outcomes)

        end_date = m.get("endDate") or m.get("endDateIso") or None
        dt = _parse_end_date(end_date)
        if dt is None:
            return None, "no_date"
        seconds_to_close = max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
        is_crypto_5min = _is_crypto_5min(m.get("slug", ""))
        interval_minutes = _crypto_interval_minutes(m.get("slug", ""))

        if getattr(config, "CRYPTO_5MIN_ENABLED", False) and is_crypto_5min:
            max_seconds_to_close = _crypto_max_seconds_to_close(interval_minutes, cycle_phase=cycle_phase)
            if seconds_to_close < config.MIN_SECONDS_TO_CLOSE:
                return None, "too_soon"
            if seconds_to_close > max_seconds_to_close:
                return None, "too_far"
        else:
            min_minutes = getattr(config, "MIN_MINUTES_TO_RESOLVE", 0)
            max_minutes = getattr(config, "MAX_MINUTES_TO_RESOLVE", None)
            if min_minutes and dt < now + timedelta(minutes=min_minutes):
                return None, "too_soon"
            if max_minutes and dt > now + timedelta(minutes=max_minutes):
                return None, "too_far"

        yes_price = fetch_market_price(yes_token_id) if yes_token_id else None
        if yes_price is None:
            bid = float(m.get("bestBid") or 0)
            last = float(m.get("lastTradePrice") or 0)
            yes_price = bid if bid > 0 else (last if last > 0 else 0.5)
        no_price = round(1.0 - yes_price, 4)
        best_bid = float(m.get("bestBid") or 0) or None
        best_ask = float(m.get("bestAsk") or 0) or None
        market_spread = None
        if best_bid is not None and best_ask is not None and best_ask >= best_bid:
            market_spread = round(best_ask - best_bid, 4)
        implied_up_prob = round(yes_price, 4)
        if up_outcome_index == 1:
            implied_up_prob = no_price

        return {
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
            "seconds_to_close": seconds_to_close,
            "is_crypto_5min": is_crypto_5min,
            "interval_minutes": interval_minutes,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "market_spread": market_spread,
            "last_trade_price": float(m.get("lastTradePrice") or 0) or None,
            "up_outcome_index": up_outcome_index,
            "market_implied_up_prob": implied_up_prob,
            "display_up_label": "UP",
            "display_down_label": "DOWN",
        }, None
    except Exception as e:
        print(f"[fetcher] Skipping market {m.get('id', '?')}: {e}")
        return None, "error"


def enrich_markets(markets: list[dict], cycle_phase: str | None = None) -> list[dict]:
    """
    Enrich raw Gamma markets with CLOB prices and end date.
    Filters to MAX_DAYS_TO_RESOLVE window in Python (API param unreliable).
    Fetches CLOB prices in parallel to reduce latency.
    Returns a clean, normalized list of market dicts.
    """
    now = datetime.now(timezone.utc)

    n_excluded = n_no_date = n_too_far = n_too_soon = 0
    enriched = []

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_enrich_one, m, now, cycle_phase): m for m in markets}
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


def get_markets(cycle_phase: str | None = None) -> list[dict]:
    """Top-level function: fetch and enrich active markets for the current phase."""
    raw = fetch_active_markets()
    return enrich_markets(raw, cycle_phase=cycle_phase)
