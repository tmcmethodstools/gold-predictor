#!/usr/bin/env python3
"""
MCX Gold Predictor — Evening Run Script
Usage:
  python run_evening.py                  # Run full prediction pipeline
  python run_evening.py --update-actual  # Record next-morning actual open price
"""
import sys
import os

# Ensure UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from zoneinfo import ZoneInfo
from rich.console import Console
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, TextColumn

IST = ZoneInfo("Asia/Kolkata")
console = Console()


def _step(n: int, label: str):
    console.print(Rule(f"[bold cyan]Step {n}: {label}[/bold cyan]"))


def run_prediction():
    now = datetime.now(IST)
    date_str = now.strftime("%Y-%m-%d")

    console.print(Rule("[bold yellow]MCX GOLD PREDICTOR — Evening Run[/bold yellow]"))
    console.print(f"[dim]Started: {now.strftime('%Y-%m-%d %H:%M:%S')} IST[/dim]\n")

    # ── Init DB ──────────────────────────────────────────────────────────
    _step(0, "Initialising database")
    from db.database import init_db, prediction_exists, save_prediction
    init_db()
    console.print(f"[green]Database ready[/green]")

    if prediction_exists(date_str):
        console.print(f"\n[yellow]A prediction for {date_str} already exists.[/yellow]")
        answer = input("Overwrite? (y/N): ").strip().lower()
        if answer != "y":
            console.print("[dim]Aborted.[/dim]")
            sys.exit(0)

    # ── Step 1: Price data ───────────────────────────────────────────────
    _step(1, "Fetching price data")
    from data.fetch_price import fetch_all_price_data
    price_data = fetch_all_price_data()

    mcx = price_data.get("mcx_close")
    comex = price_data.get("comex_close")
    usdinr = price_data.get("usdinr_close")
    console.print(f"  MCX close:    [green]{_fmt_inr(mcx)}[/green]")
    console.print(f"  COMEX close:  [green]${comex:.2f}[/green]" if comex else "  COMEX: N/A")
    console.print(f"  USD/INR:      [green]{usdinr:.4f}[/green]" if usdinr else "  USD/INR: N/A")

    # ── Step 2: Macro data ───────────────────────────────────────────────
    _step(2, "Fetching macro data (FRED)")
    from data.fetch_macro import fetch_macro_data
    macro_data = fetch_macro_data()
    fed = macro_data.get("FEDFUNDS", {}).get("latest_value")
    console.print(f"  Fed Funds Rate: {fed}%" if fed else "  Fed Funds Rate: N/A")

    # ── Step 3: News ─────────────────────────────────────────────────────
    _step(3, "Fetching news & RSS feeds")
    from data.fetch_news import fetch_all_news
    news_data = fetch_all_news()
    console.print(f"  {news_data['total_articles']} articles collected")
    if news_data["festival"]["is_festival_season"]:
        console.print(f"  [yellow]⭐ {news_data['festival']['note']}[/yellow]")

    # ── Step 4: Features ─────────────────────────────────────────────────
    _step(4, "Building technical features")
    from features.build_features import build_features
    features = build_features(price_data)
    rsi = features.get("rsi_14")
    macd = features.get("macd_crossover")
    console.print(f"  RSI(14): {rsi:.1f} → {features.get('rsi_zone','N/A')}" if rsi else "  RSI: N/A")
    console.print(f"  MACD: {macd}")

    # ── Step 5: Claude signal ────────────────────────────────────────────
    _step(5, "Generating Claude AI signal")
    from analysis.claude_signal import generate_signal
    signal = generate_signal(price_data, macro_data, news_data, features)
    sig = signal.get("signal", "N/A")
    conf = signal.get("confidence", "N/A")
    low = signal.get("predicted_low")
    high = signal.get("predicted_high")
    sig_color = {"BULLISH": "green", "BEARISH": "red", "NEUTRAL": "yellow"}.get(sig, "white")
    console.print(f"  Signal:     [{sig_color}]{sig}[/{sig_color}]  ({conf}% confidence)")
    console.print(f"  Prediction: {_fmt_inr(low)} – {_fmt_inr(high)} / 10g")

    # ── Step 6: Report ───────────────────────────────────────────────────
    _step(6, "Generating report")
    from report.generate_report import generate_report, send_telegram
    # Attach news data to function object so generate_report can access it
    generate_report._news_data = news_data
    report_text = generate_report(date_str, price_data, macro_data, features, signal)

    # ── Step 7: Save to DB ───────────────────────────────────────────────
    _step(7, "Saving prediction to database")
    db_payload = {
        "mcx_close": price_data.get("mcx_close"),
        "comex_close": price_data.get("comex_close"),
        "usdinr_close": price_data.get("usdinr_close"),
        "rsi_14": features.get("rsi_14"),
        "signal": signal.get("signal"),
        "confidence": signal.get("confidence"),
        "predicted_low": signal.get("predicted_low"),
        "predicted_high": signal.get("predicted_high"),
        "driver_1": signal.get("driver_1"),
        "driver_2": signal.get("driver_2"),
        "driver_3": signal.get("driver_3"),
        "risk_factor": signal.get("risk_factor"),
        "rupee_outlook": signal.get("rupee_outlook"),
    }
    save_prediction(date_str, db_payload)
    console.print("[green]Prediction saved to local database[/green]")

    # Sync to Supabase cloud (pass report_text so it's visible on dashboard)
    from db.supabase_sync import push_prediction
    push_prediction(date_str, report_text=report_text)

    # ── Step 8: Telegram ─────────────────────────────────────────────────
    _step(8, "Telegram notification")
    from config import TELEGRAM_BOT_TOKEN
    if TELEGRAM_BOT_TOKEN:
        send_telegram(report_text, signal)
    else:
        console.print("[dim]Telegram not configured — skipping[/dim]")

    console.print(Rule("[bold green]✓ Evening run complete[/bold green]"))


def run_update_actual():
    console.print(Rule("[bold yellow]MCX GOLD — Update Actual Open Price[/bold yellow]"))
    date_str = input("Date of prediction to update (YYYY-MM-DD): ").strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        console.print("[red]Invalid date format. Use YYYY-MM-DD.[/red]")
        sys.exit(1)

    price_str = input(f"MCX Gold actual open price on {date_str} (INR/10g): ").strip()
    try:
        actual_open = float(price_str.replace(",", ""))
    except ValueError:
        console.print("[red]Invalid price. Enter a number like 75000[/red]")
        sys.exit(1)

    from db.database import init_db, update_actual, get_accuracy_stats
    init_db()
    success = update_actual(date_str, actual_open)

    if success:
        console.print(f"[green]Updated {date_str} with actual open: {_fmt_inr(actual_open)}[/green]")
        # Sync actuals to Supabase
        from db.supabase_sync import push_actual
        push_actual(date_str)
        stats = get_accuracy_stats()
        console.print(f"\n[bold]Accuracy Stats:[/bold]")
        console.print(f"  Total predictions:   {stats['total_predictions']}")
        console.print(f"  Direction accuracy:  {stats['direction_accuracy_pct']}%")
        console.print(f"  Range accuracy:      {stats['range_accuracy_pct']}%")
        console.print(f"  Avg confidence:      {stats['avg_confidence']}%")
    else:
        console.print(f"[red]No prediction found for {date_str}[/red]")


def _fmt_inr(val) -> str:
    if val is None:
        return "N/A"
    try:
        v = int(round(float(val)))
        s = str(v)
        if len(s) > 3:
            last3 = s[-3:]
            rest = s[:-3]
            groups = []
            while len(rest) > 2:
                groups.append(rest[-2:])
                rest = rest[:-2]
            if rest:
                groups.append(rest)
            groups.reverse()
            s = ",".join(groups) + "," + last3
        return f"₹{s}"
    except (TypeError, ValueError):
        return "N/A"


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if "--update-actual" in sys.argv:
        run_update_actual()
    else:
        run_prediction()
