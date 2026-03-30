"""
Polymarket Simulation Bot — entry point.

Usage:
    python main.py

Stop with Ctrl+C.
"""

import os
import time
import traceback

import anthropic
from dotenv import load_dotenv

import config
import dashboard
import fetcher
import analyzer
import engine
import logger


def run_cycle(client: anthropic.Anthropic, cycle_num: int) -> None:
    dashboard.display_info(f"Fetching markets...")
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

    dashboard.display_info(f"Analyzing {len(markets)} markets with Claude...")
    analyses = analyzer.analyze_markets(client, markets)

    pending_ids = logger.get_pending_market_ids()
    trades = engine.evaluate_trades(analyses, existing_pending=pending_ids)

    logger.log_trades(trades, cycle=cycle_num)
    portfolio = logger.get_portfolio_summary()

    dashboard.display_cycle(cycle_num, markets, analyses, trades, portfolio)


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        dashboard.display_error("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        return

    client = anthropic.Anthropic(api_key=api_key)
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

            dashboard.display_info(
                f"Next cycle in {config.LOOP_INTERVAL_SECONDS}s. Press Ctrl+C to stop."
            )
            time.sleep(config.LOOP_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print()
        dashboard.display_info("Shutting down...")
        portfolio = logger.get_portfolio_summary()
        dashboard.display_cycle(cycle_num, [], [], [], portfolio)


if __name__ == "__main__":
    main()
