from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

import config

console = Console()


def display_startup() -> None:
    lines = [
        f"[bold]Model:[/bold]          {config.MODEL_NAME}",
        f"[bold]Edge threshold:[/bold] {config.EDGE_THRESHOLD:.0%}",
        f"[bold]Bet size:[/bold]       ${config.BET_SIZE:,.0f}",
        f"[bold]Min confidence:[/bold] {config.MIN_CONFIDENCE}",
        f"[bold]Min liquidity:[/bold]  ${config.MIN_LIQUIDITY:,.0f}",
        f"[bold]Max markets:[/bold]    {config.MAX_MARKETS_PER_CYCLE}",
        f"[bold]Loop interval:[/bold]  {config.LOOP_INTERVAL_SECONDS}s",
        f"[bold]CSV:[/bold]            {config.TRADES_CSV_PATH}",
    ]
    console.print(Panel("\n".join(lines), title="[bold cyan]Polymarket Simulation Bot[/bold cyan]", border_style="cyan"))


def display_cycle(
    cycle_num: int,
    markets: list[dict],
    analyses: list[dict],
    trades: list[dict],
    portfolio: dict,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    console.print(f"\n[bold cyan]── Cycle {cycle_num}[/bold cyan]  [dim]{now}[/dim]")

    # Markets table
    if markets:
        _render_markets_table(markets, analyses)

    # Trades table
    if trades:
        _render_trades_table(trades)
    else:
        console.print("[dim]  No trades triggered this cycle.[/dim]")

    # Portfolio summary
    _render_portfolio(portfolio)


def _render_markets_table(markets: list[dict], analyses: list[dict]) -> None:
    analysis_by_id = {a["market_id"]: a for a in analyses}

    table = Table(
        title=f"Markets Analyzed ({len(markets)})",
        box=box.SIMPLE_HEAD,
        show_edge=False,
        highlight=True,
    )
    table.add_column("Question", style="white", max_width=52, no_wrap=False)
    table.add_column("Mkt %", justify="right", style="dim")
    table.add_column("Claude %", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Conf", justify="center")
    table.add_column("Liquidity", justify="right", style="dim")

    for m in markets:
        a = analysis_by_id.get(m["id"])
        if not a:
            table.add_row(
                m["question"][:52],
                f"{m['yes_price']:.0%}", "—", "—", "—",
                f"${m['liquidity']:,.0f}",
            )
            continue

        edge = a["edge"]
        edge_str = Text(f"{edge:+.1%}")
        if abs(edge) >= config.EDGE_THRESHOLD:
            edge_str.stylize("bold green" if edge > 0 else "bold red")
        else:
            edge_str.stylize("dim")

        conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(a["confidence"], "white")

        table.add_row(
            m["question"][:52],
            f"{m['yes_price']:.0%}",
            f"{a['claude_prob']:.0%}",
            edge_str,
            f"[{conf_color}]{a['confidence']}[/{conf_color}]",
            f"${m['liquidity']:,.0f}",
        )

    console.print(table)


def _render_trades_table(trades: list[dict]) -> None:
    table = Table(
        title=f"Trades Placed ({len(trades)})",
        box=box.SIMPLE_HEAD,
        show_edge=False,
    )
    table.add_column("Question", style="white", max_width=44, no_wrap=False)
    table.add_column("Direction", justify="center")
    table.add_column("Edge", justify="right")
    table.add_column("Proj. P&L", justify="right")
    table.add_column("Confidence", justify="center")

    for t in trades:
        direction_color = "green" if t["direction"] == "BUY_YES" else "red"
        table.add_row(
            t["question"][:44],
            f"[{direction_color}]{t['direction']}[/{direction_color}]",
            f"{t['edge']:+.1%}",
            f"${t['projected_pnl']:.2f}",
            t["confidence"],
        )

    console.print(table)


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
        f"P&L: [{pnl_color}]${pnl:,.2f}[/{pnl_color}]"
    )
    console.print(Panel(summary, title="Portfolio", border_style="dim", padding=(0, 1)))


def display_error(msg: str) -> None:
    console.print(f"[bold red][ERROR][/bold red] {msg}")


def display_warning(msg: str) -> None:
    console.print(f"[bold yellow][WARN][/bold yellow] {msg}")


def display_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")
