from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.columns import Columns

import config

console = Console()


def display_startup() -> None:
    lines = [
        f"[bold]Model:[/bold]          {config.MODEL_NAME}",
        f"[bold]Edge threshold:[/bold] {config.EDGE_THRESHOLD:.0%}",
        f"[bold]Min EV ROI:[/bold]    {config.MIN_EV_ROI:.0%}",
        f"[bold]Max Kelly:[/bold]      {config.MAX_KELLY_FRACTION:.0%} of bankroll",
        f"[bold]Min confidence:[/bold] {config.MIN_CONFIDENCE}",
        f"[bold]Min liquidity:[/bold]  ${config.MIN_LIQUIDITY:,.0f}",
        f"[bold]Max markets:[/bold]    {config.MAX_MARKETS_PER_CYCLE}",
        f"[bold]Resolve window:[/bold] {config.MIN_DAYS_TO_RESOLVE}–{config.MAX_DAYS_TO_RESOLVE} days",
        f"[bold]Loop interval:[/bold]  {config.LOOP_INTERVAL_SECONDS}s",
        f"[bold]Goal:[/bold]           ${config.GOAL_AMOUNT:,.0f}",
        f"[bold]CSV:[/bold]            {config.TRADES_CSV_PATH}",
    ]
    console.print(Panel("\n".join(lines), title="[bold cyan]Polymarket Compound Bot[/bold cyan]", border_style="cyan"))


def display_cycle(
    cycle_num: int,
    markets: list[dict],
    analyses: list[dict],
    trades: list[dict],
    portfolio: dict,
    progress: dict,
    analysis_skip_summary: dict[str, int] | None = None,
    engine_rejection_summary: dict[str, int] | None = None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    console.print(f"\n[bold cyan]── Cycle {cycle_num}[/bold cyan]  [dim]{now}[/dim]")

    if markets:
        _render_markets_table(markets, analyses)

    if trades:
        _render_trades_table(trades)
    else:
        console.print("[dim]  No trades triggered this cycle.[/dim]")

    _render_skip_summary(analysis_skip_summary or {}, engine_rejection_summary or {})

    _render_goal_tracker(progress)
    _render_portfolio(portfolio)


def _render_markets_table(markets: list[dict], analyses: list[dict]) -> None:
    analysis_by_id = {a["market_id"]: a for a in analyses}

    table = Table(
        title=f"Markets Analyzed ({len(markets)})",
        box=box.SIMPLE_HEAD,
        show_edge=False,
        highlight=False,
    )
    table.add_column("Question", style="white", max_width=40, no_wrap=True)
    table.add_column("Mkt %", justify="right", style="dim")
    table.add_column("AI %", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Window", justify="right", style="dim")
    table.add_column("L60", justify="right", style="dim")
    table.add_column("L30", justify="right", style="dim")
    table.add_column("L15", justify="right", style="dim")
    table.add_column("Pat", justify="center")
    table.add_column("Src", justify="center", style="dim")
    table.add_column("Conf", justify="center")
    table.add_column("Days", justify="right", style="dim")
    table.add_column("Liquidity", justify="right", style="dim")

    for m in markets:
        a = analysis_by_id.get(m["id"])
        days = _format_days(m.get("end_date"))
        market_prob_display = m.get("market_implied_up_prob", m["yes_price"])
        if not a:
            table.add_row(
                m["question"][:48], f"{market_prob_display:.0%}", "—", "—", "—", "—", "—", "—", "—", "—", "—",
                days, f"${m['liquidity']:,.0f}",
            )
            continue

        edge = a["edge"]
        edge_str = Text(f"{edge:+.1%}")
        threshold = getattr(config, "CRYPTO_EDGE_THRESHOLD", config.EDGE_THRESHOLD) if a.get("is_crypto_5min") else config.EDGE_THRESHOLD
        if abs(edge) >= threshold:
            edge_str.stylize("bold green" if edge > 0 else "bold red")
        else:
            edge_str.stylize("dim")

        conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(a["confidence"], "white")
        ai_prob_display = a.get("probability_up") if a.get("probability_up") is not None else a["claude_prob"]

        table.add_row(
            m["question"][:48],
            f"{market_prob_display:.0%}",
            f"{ai_prob_display:.0%}",
            edge_str,
            _format_pct(a.get("window_move_pct")),
            _format_pct(a.get("last60_move_pct")),
            _format_pct(a.get("last30_move_pct")),
            _format_pct(a.get("last15_move_pct")),
            (a.get("pattern") or "—")[:10],
            (a.get("data_source") or "—")[:10],
            f"[{conf_color}]{a['confidence']}[/{conf_color}]",
            days,
            f"${m['liquidity']:,.0f}",
        )

    console.print(table)


def _format_days(end_date: str | None) -> str:
    if not end_date:
        return "—"
    try:
        from datetime import timedelta
        if end_date.endswith("Z"):
            end_date = end_date[:-1] + "+00:00"
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(end_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = (dt - datetime.now(timezone.utc)).days
        return f"{days}d"
    except Exception:
        return "—"


def _render_trades_table(trades: list[dict]) -> None:
    table = Table(
        title=f"Trades Placed ({len(trades)})",
        box=box.SIMPLE_HEAD,
        show_edge=False,
    )
    table.add_column("Question", style="white", max_width=40, no_wrap=False)
    table.add_column("Direction", justify="center")
    table.add_column("Edge", justify="right")
    table.add_column("Window", justify="right", style="dim")
    table.add_column("L30", justify="right", style="dim")
    table.add_column("L15", justify="right", style="dim")
    table.add_column("Pat", justify="center")
    table.add_column("Src", justify="center", style="dim")
    table.add_column("Bet", justify="right")
    table.add_column("EV", justify="right")
    table.add_column("Conf", justify="center")

    for t in trades:
        display_direction = t.get("display_direction") or t["direction"]
        direction_color = "green" if display_direction in {"BUY_YES", "BUY_UP"} else "red"
        table.add_row(
            t["question"][:40],
            f"[{direction_color}]{display_direction}[/{direction_color}]",
            f"{t['edge']:+.1%}",
            _format_pct(t.get("window_move_pct")),
            _format_pct(t.get("last30_move_pct")),
            _format_pct(t.get("last15_move_pct")),
            (t.get("pattern") or "—")[:10],
            (t.get("data_source") or "—")[:10],
            f"${t['bet_size']:.2f}",
            f"${t['projected_pnl']:.2f}",
            t["confidence"],
        )

    console.print(table)


def _render_skip_summary(analysis_skip_summary: dict[str, int], engine_rejection_summary: dict[str, int]) -> None:
    if not analysis_skip_summary and not engine_rejection_summary:
        return

    lines = []
    if analysis_skip_summary:
        analysis_bits = [f"{reason}={count}" for reason, count in analysis_skip_summary.items()]
        lines.append("[bold]Analysis skips:[/bold] " + "  ".join(analysis_bits))
    if engine_rejection_summary:
        engine_bits = [f"{reason}={count}" for reason, count in engine_rejection_summary.items()]
        lines.append("[bold]Engine rejects:[/bold] " + "  ".join(engine_bits))

    console.print(Panel("\n".join(lines), title="Cycle Reasons", border_style="dim", padding=(0, 1)))


def _render_goal_tracker(progress: dict) -> None:
    balance = progress["balance"]
    goal = progress["goal"]
    total_return = progress["total_return"]
    drawdown = progress["drawdown"]
    days_to_goal = progress.get("days_to_goal")
    elapsed = progress["elapsed_days"]

    pct_to_goal = min(balance / goal * 100, 100)
    bar_filled = int(pct_to_goal / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    bal_color = "green" if balance >= progress["start_balance"] else "red"
    ret_color = "green" if total_return >= 0 else "red"
    dd_color = "red" if drawdown < -0.1 else "yellow" if drawdown < 0 else "green"

    dtg = f"~{days_to_goal:.1f} days" if days_to_goal and days_to_goal < 9999 else "calculating..."

    lines = [
        f"[bold]Bankroll:[/bold]   [{bal_color}]${balance:,.4f}[/{bal_color}]  /  [dim]${goal:,.0f} goal[/dim]",
        f"[bold]Progress:[/bold]   [cyan]{bar}[/cyan]  {pct_to_goal:.4f}%",
        f"[bold]Return:[/bold]     [{ret_color}]{total_return:+.1%}[/{ret_color}]  |  "
        f"[bold]Drawdown:[/bold] [{dd_color}]{drawdown:.1%}[/{dd_color}]  |  "
        f"[bold]ATH:[/bold] ${progress['peak']:,.4f}",
        f"[bold]Elapsed:[/bold]    {elapsed:.1f} days  |  "
        f"[bold]Projected to $1M:[/bold] [bold yellow]{dtg}[/bold yellow]  |  "
        f"[bold]Resolved:[/bold] {progress['trades_resolved']} trades",
    ]
    console.print(Panel("\n".join(lines), title="[bold yellow]$1M Goal Tracker[/bold yellow]", border_style="yellow"))


def _render_portfolio(portfolio: dict) -> None:
    win_rate = f"{portfolio['win_rate']:.0%}" if portfolio["win_rate"] is not None else "—"
    pnl = portfolio["total_pnl"]
    pnl_color = "green" if pnl >= 0 else "red"

    summary = (
        f"[bold]Total trades:[/bold] {portfolio['total']}  "
        f"[green]Won: {portfolio['won']}[/green]  "
        f"[red]Lost: {portfolio['lost']}[/red]  "
        f"[yellow]Pending: {portfolio['pending']}[/yellow]  "
        f"Win rate: {win_rate}  "
        f"Resolved P&L: [{pnl_color}]${pnl:,.2f}[/{pnl_color}]"
    )
    console.print(Panel(summary, title="Portfolio", border_style="dim", padding=(0, 1)))


def display_resolver(resolved: int) -> None:
    if resolved > 0:
        console.print(f"[bold green]  ✓ Auto-resolved {resolved} trade(s)[/bold green]")


def display_error(msg: str) -> None:
    console.print(f"[bold red][ERROR][/bold red] {msg}")


def display_warning(msg: str) -> None:
    console.print(f"[bold yellow][WARN][/bold yellow] {msg}")


def display_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def _format_pct(value) -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"{float(value):+.2%}"
    except Exception:
        return "—"
