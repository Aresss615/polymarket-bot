"""
Polymarket Compound Simulation Bot — entry point.

Usage:
    python main.py

Stop with Ctrl+C.
"""

import datetime
import os
import time
import traceback

from openai import OpenAI
from dotenv import load_dotenv

import config
import dashboard
import fetcher
import analyzer
import engine
import logger
import resolver
import bankroll


def run_cycle(client: OpenAI, cycle_num: int) -> None:
    # Auto-resolve any pending trades that have closed
    resolved = resolver.auto_resolve()
    dashboard.display_resolver(resolved)

    dashboard.display_info("Fetching markets...")
    try:
        markets = fetcher.get_markets()
    except Exception as e:
        dashboard.display_warning(f"Polymarket API error: {e}. Retrying in 30s...")
        time.sleep(30)
        try:
            markets = fetcher.get_markets()
        except Exception as e2:
            dashboard.display_error(f"Polymarket API still unavailable: {e2}. Skipping cycle.")
            return

    if not markets:
        dashboard.display_warning("No markets returned. Skipping cycle.")
        return

    dashboard.display_info(f"Analyzing {len(markets)} markets...")
    analyses = analyzer.analyze_markets(client, markets)

    # Pass end_date from market into analysis for date filtering in engine
    market_dates = {m["id"]: m.get("end_date") for m in markets}
    for a in analyses:
        a["end_date"] = market_dates.get(a["market_id"])

    pending_ids = logger.get_pending_market_ids()
    trades = engine.evaluate_trades(analyses, existing_pending=pending_ids)

    current_balance = bankroll.get_balance()
    logger.log_trades(trades, cycle=cycle_num, bankroll_balance=current_balance)

    portfolio = logger.get_portfolio_summary()
    progress = bankroll.get_progress()

    dashboard.display_cycle(cycle_num, markets, analyses, trades, portfolio, progress)


def seconds_until_next_cycle() -> float:
    """Wake up SECONDS_BEFORE_CLOSE seconds before the next 5-min boundary."""
    now = datetime.datetime.now()
    remainder = now.minute % 5
    minutes_to_boundary = 5 - remainder if remainder != 0 else 5
    boundary = now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=minutes_to_boundary)
    wake_time = boundary - datetime.timedelta(seconds=config.SECONDS_BEFORE_CLOSE)
    delta = (wake_time - datetime.datetime.now()).total_seconds()
    while delta < 10:  # need at least 10s to complete a cycle
        boundary += datetime.timedelta(minutes=5)
        wake_time = boundary - datetime.timedelta(seconds=config.SECONDS_BEFORE_CLOSE)
        delta = (wake_time - datetime.datetime.now()).total_seconds()
    return delta


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("Missing GROQ_API_KEY in .env")
    client = OpenAI(api_key=api_key, base_url=config.GROQ_BASE_URL)
    dashboard.display_startup()

    cycle_num = 0
    try:
        while True:
            cycle_num += 1
            try:
                run_cycle(client, cycle_num)
            except Exception:
                dashboard.display_error(f"Unexpected error in cycle {cycle_num}:")
                traceback.print_exc()

            wait = seconds_until_next_cycle()
            next_run = (datetime.datetime.now() + datetime.timedelta(seconds=wait)).strftime("%H:%M:%S")
            dashboard.display_info(f"Next cycle at {next_run} ({wait:.0f}s). Press Ctrl+C to stop.")
            time.sleep(wait)

    except KeyboardInterrupt:
        print()
        dashboard.display_info("Shutting down...")
        portfolio = logger.get_portfolio_summary()
        progress = bankroll.get_progress()
        dashboard.display_cycle(cycle_num, [], [], [], portfolio, progress)


if __name__ == "__main__":
    main()
