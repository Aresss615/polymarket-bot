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
import price_feed


def run_cycle(
    client: OpenAI,
    cycle_num: int,
    cycle_phase: str,
    boundary_time: datetime.datetime,
) -> None:
    # Auto-resolve any pending trades that have closed
    resolved = resolver.auto_resolve()
    dashboard.display_resolver(resolved)

    boundary_iso = boundary_time.isoformat()
    dashboard.display_info(
        f"Fetching markets for {cycle_phase.upper()} "
        f"(boundary {boundary_time.strftime('%H:%M:%S')})..."
    )
    try:
        markets = fetcher.get_markets(cycle_phase=cycle_phase)
    except Exception as e:
        dashboard.display_warning(f"Polymarket API error: {e}. Retrying in 30s...")
        time.sleep(30)
        try:
            markets = fetcher.get_markets(cycle_phase=cycle_phase)
        except Exception as e2:
            dashboard.display_error(f"Polymarket API still unavailable: {e2}. Skipping cycle.")
            return

    if not markets:
        dashboard.display_warning("No markets returned. Skipping cycle.")
        return

    for market in markets:
        market["cycle_phase"] = cycle_phase
        market["boundary_time"] = boundary_iso

    active_crypto_symbols = {
        str(m.get("slug", "")).split("-")[0].upper()
        for m in markets
        if m.get("is_crypto_5min") and int(m.get("interval_minutes") or 0) == 5
    }
    if active_crypto_symbols:
        price_feed.register_symbols(sorted(active_crypto_symbols))

    dashboard.display_info(f"Analyzing {len(markets)} markets...")
    analyses = analyzer.analyze_markets(client, markets)
    analysis_skip_summary = analyzer.get_skip_summary()

    # Pass end_date from market into analysis for date filtering in engine
    market_dates = {m["id"]: m.get("end_date") for m in markets}
    for a in analyses:
        a["end_date"] = market_dates.get(a["market_id"])
        a.setdefault("cycle_phase", cycle_phase)
        a.setdefault("boundary_time", boundary_iso)

    all_trades = logger.load_trades()
    pending_trades = logger.get_pending_trades()
    bucket_stats = logger.get_strategy_bucket_stats()
    direction_bucket_stats = logger.get_direction_bucket_stats()
    trades = engine.evaluate_trades(
        analyses,
        existing_pending_trades=pending_trades,
        bucket_stats=bucket_stats,
        direction_bucket_stats=direction_bucket_stats,
        all_trades=all_trades,
        current_cycle=cycle_num,
    )
    engine_rejection_summary = engine.get_rejection_summary()

    current_balance = bankroll.get_balance()
    logger.log_trades(trades, cycle=cycle_num, bankroll_balance=current_balance)

    portfolio = logger.get_portfolio_summary()
    progress = bankroll.get_progress()

    dashboard.display_cycle(
        cycle_num,
        markets,
        analyses,
        trades,
        portfolio,
        progress,
        analysis_skip_summary=analysis_skip_summary,
        engine_rejection_summary=engine_rejection_summary,
    )


def _next_boundary_after(now: datetime.datetime) -> datetime.datetime:
    minute_floor = now.minute - (now.minute % 5)
    boundary = now.replace(minute=minute_floor, second=0, microsecond=0)
    if boundary <= now:
        boundary += datetime.timedelta(minutes=5)
    return boundary


def next_cycle_schedule(
    now: datetime.datetime | None = None,
) -> tuple[float, str, datetime.datetime]:
    """Return the next phase wake-up as (wait_seconds, phase, boundary_time)."""
    now = now or datetime.datetime.now()
    boundaries = [
        _next_boundary_after(now),
        _next_boundary_after(now) + datetime.timedelta(minutes=5),
    ]
    phases = [
        ("t45", int(getattr(config, "SECONDS_BEFORE_CLOSE", 45))),
        ("t30", int(getattr(config, "SECOND_CHANCE_SECONDS", 30))),
    ]

    for boundary in boundaries:
        for phase, seconds_before in phases:
            wake_time = boundary - datetime.timedelta(seconds=seconds_before)
            delta = (wake_time - now).total_seconds()
            if delta >= 0.25:
                return delta, phase, boundary
            if -0.75 <= delta < 0.25:
                return 0.0, phase, boundary

    boundary = boundaries[-1] + datetime.timedelta(minutes=5)
    wake_time = boundary - datetime.timedelta(seconds=int(getattr(config, "SECONDS_BEFORE_CLOSE", 45)))
    delta = max(0.0, (wake_time - now).total_seconds())
    return delta, "t45", boundary


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "ollama"
    client = OpenAI(api_key=api_key, base_url=config.API_BASE_URL)
    price_feed.start_price_stream()
    dashboard.display_startup()
    dashboard.display_info(f"Underlying stream: {price_feed.get_stream_status()}")

    cycle_num = 0
    try:
        while True:
            wait, phase, boundary = next_cycle_schedule()
            next_run = (datetime.datetime.now() + datetime.timedelta(seconds=wait)).strftime("%H:%M:%S")
            dashboard.display_info(
                f"Next cycle {phase.upper()} at {next_run} "
                f"for {boundary.strftime('%H:%M:%S')} boundary "
                f"({wait:.0f}s). Press Ctrl+C to stop."
            )
            if wait > 0:
                time.sleep(wait)

            cycle_num += 1
            try:
                run_cycle(client, cycle_num, cycle_phase=phase, boundary_time=boundary)
            except Exception:
                dashboard.display_error(f"Unexpected error in cycle {cycle_num}:")
                traceback.print_exc()

    except KeyboardInterrupt:
        print()
        price_feed.stop_price_stream()
        dashboard.display_info("Shutting down...")
        portfolio = logger.get_portfolio_summary()
        progress = bankroll.get_progress()
        dashboard.display_cycle(cycle_num, [], [], [], portfolio, progress)


if __name__ == "__main__":
    main()
