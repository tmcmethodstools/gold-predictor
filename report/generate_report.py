import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from config import REPORT_DIR, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

console = Console(highlight=False)
IST = ZoneInfo("Asia/Kolkata")


def _fmt_inr(val) -> str:
    if val is None:
        return "N/A"
    try:
        # Indian number format: 1,00,000
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


def _pct(val) -> str:
    if val is None:
        return "N/A"
    sign = "+" if float(val) >= 0 else ""
    return f"{sign}{float(val):.2f}%"


def _safe(val, decimals=2, default="N/A") -> str:
    if val is None:
        return default
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return default


def generate_report(date: str, price_data: dict, macro_data: dict,
                    features: dict, signal: dict) -> str:

    os.makedirs(REPORT_DIR, exist_ok=True)
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    # ── Helpers ────────────────────────────────────────────────────────────
    mcx_close = price_data.get("mcx_close")
    comex_close = price_data.get("comex_close")
    usdinr_close = price_data.get("usdinr_close")
    mcx_premium = price_data.get("mcx_premium")

    rsi_val = features.get("rsi_14")
    rsi_zone = features.get("rsi_zone", "N/A")
    macd_status = features.get("macd_crossover", "N/A")
    bb_pos = features.get("bb_position")
    ema_status = features.get("ema_crossover", "N/A")
    vol_10d = features.get("volatility_10d")

    fed_rate = macro_data.get("FEDFUNDS", {}).get("latest_value")
    yield_10y = macro_data.get("DGS10", {}).get("latest_value")
    cpi = macro_data.get("CPIAUCSL", {}).get("latest_value")

    sig = signal.get("signal", "N/A")
    confidence = signal.get("confidence", "N/A")
    pred_low = signal.get("predicted_low")
    pred_high = signal.get("predicted_high")
    driver_1 = signal.get("driver_1", "N/A")
    driver_2 = signal.get("driver_2", "N/A")
    driver_3 = signal.get("driver_3", "N/A")
    risk_factor = signal.get("risk_factor", "N/A")
    reasoning = signal.get("reasoning", "N/A")
    rupee_outlook = signal.get("rupee_outlook", "N/A")

    # Determine DXY direction
    dxy_df = price_data.get("dxy")
    dxy_dir = "N/A"
    if dxy_df is not None and not dxy_df.empty and len(dxy_df) >= 2:
        try:
            last2 = dxy_df["Close"].dropna().iloc[-2:]
            dxy_dir = "STRENGTHENING" if last2.iloc[-1] > last2.iloc[-2] else "WEAKENING"
        except Exception:
            pass

    # Festival note
    festival_note = "None"
    from data.fetch_news import check_festival_season
    festival_info = check_festival_season()
    if festival_info.get("is_festival_season"):
        names = [f["name"] for f in festival_info.get("active_festivals", [])]
        festival_note = f"FESTIVAL SEASON — {', '.join(names)}"

    # News headlines
    news_all = (price_data.get("news_global", []) + price_data.get("news_india", [])) if False else []
    from data.fetch_news import fetch_all_news as _fn
    _cached_news = getattr(generate_report, "_cached_news", None)

    # Build report text
    width = 58
    bar = "═" * width

    lines = [
        f"╔{'═' * width}╗",
        f"║{'MCX GOLD EVENING REPORT — ' + date:^{width}}║",
        f"╚{'═' * width}╝",
        "",
        "PRICE SNAPSHOT",
        "──────────────",
        f"MCX Gold (NSE):      {_fmt_inr(mcx_close)} / 10g    ({_pct(price_data.get('mcx_change_pct'))})",
        f"COMEX Gold:          ${_safe(comex_close)} / oz    ({_pct(price_data.get('comex_change_pct'))})",
        f"USD/INR:             {_safe(usdinr_close, 4)}              ({_pct(price_data.get('usdinr_change_pct'))})",
        f"Brent Crude:         ${_safe(price_data.get('brent_close'))} / bbl   ({_pct(price_data.get('brent_change_pct'))})",
        f"WTI Crude:           ${_safe(price_data.get('wti_close'))} / bbl   ({_pct(price_data.get('wti_change_pct'))})",
        f"Nifty 50:            {_pct(price_data.get('nifty_change_pct'))}",
        f"MCX Local Premium:   {_fmt_inr(mcx_premium)} (ETF vs pre-duty formula — expected negative)",
        f"Gold/Silver Ratio:   {_safe(price_data.get('gold_silver_ratio'), 1)}",
        "",
        "TECHNICAL SIGNALS",
        "─────────────────",
        f"RSI (14):         {_safe(rsi_val, 1)}   → {rsi_zone}",
        f"MACD:             {macd_status}",
        f"Bollinger:        Price at {_safe(bb_pos * 100, 0) if bb_pos is not None else 'N/A'}% of band",
        f"EMA 9/21:         {ema_status}",
        f"Volatility:       {_safe(vol_10d, 2)}% (10-day)",
        f"1-day change:     {_pct(features.get('price_change_1d'))}",
        f"5-day change:     {_pct(features.get('price_change_5d'))}",
        "",
        "MACRO ENVIRONMENT",
        "─────────────────",
        f"Fed Funds Rate:   {_safe(fed_rate, 2)}%",
        f"10Y Nominal Yield:{_safe(yield_10y, 2)}%",
        f"10Y REAL Yield:   {_safe(macro_data.get('DFII10', {}).get('latest_value'), 2)}%  (rising = gold bearish)",
        f"Inflation Breakevn:{_safe(macro_data.get('T10YIE', {}).get('latest_value'), 2)}%  (rising = gold bullish)",
        f"US CPI:           {_safe(cpi, 1)}",
        f"VIX Fear Index:   {_safe(macro_data.get('VIXCLS', {}).get('latest_value'), 2)}",
        f"DXY Dollar:       {dxy_dir}",
        "",
        "INDIA FACTORS",
        "─────────────",
        f"Rupee Outlook:    {rupee_outlook}",
        f"USD/INR 1-day:    {_pct(features.get('usdinr_change_1d'))}",
        f"Festival Alert:   {festival_note}",
        "",
        "CRUDE OIL (India Import Impact)",
        "────────────────────────────────",
        f"Brent 1-day:      {_pct(features.get('brent_change_1d'))}",
        f"Brent 5-day:      {_pct(features.get('brent_change_5d'))}",
        f"Crude-Gold Today: {features.get('crude_gold_alignment', 'N/A')}",
        "",
    ]

    # ── News section (use passed-through news_data if available) ───────────
    # News is fetched in run_evening.py and not re-fetched here
    # We use whatever was stored on the function object
    news_data = getattr(generate_report, "_news_data", {})
    all_headlines = news_data.get("global_news", []) + news_data.get("india_news", [])

    lines += ["TOP NEWS HEADLINES", "──────────────────"]
    if all_headlines:
        for item in all_headlines[:6]:
            tag = "[IN]" if item.get("type") == "india" else "[GL]"
            title = item.get("title", "")[:80]
            src = item.get("source", "")
            lines.append(f"  {tag} {title} — {src}")
    else:
        lines.append("  No headlines available.")

    sig_color = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(sig, "⬜")

    lines += [
        "",
        bar,
        f"{'CLAUDE\'S PREDICTION':^{width}}",
        bar,
        f"Signal:           {sig_color} {sig}",
        f"Confidence:       {confidence}%",
        f"Predicted Open:   {_fmt_inr(pred_low)} – {_fmt_inr(pred_high)} / 10g",
        "",
        "Key Drivers:",
        f"  1. {driver_1}",
        f"  2. {driver_2}",
        f"  3. {driver_3}",
        "",
        f"Risk Factor:      {risk_factor}",
        "",
        "Reasoning:",
        reasoning or "N/A",
        "",
        bar,
        f"Report generated: {timestamp} IST",
        bar,
    ]

    if signal.get("is_mock"):
        lines.insert(3, "⚠️  MOCK SIGNAL — Set ANTHROPIC_API_KEY for real predictions")
        lines.insert(4, "")

    report_text = "\n".join(lines)

    # Save to file
    filename = os.path.join(REPORT_DIR, f"{date}_gold_report.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report_text)

    console.print(f"\n[green]Report saved: {filename}[/green]")

    # Print to console with rich styling
    _print_rich(report_text, sig)

    return report_text


def _print_rich(report_text: str, signal: str):
    color = {"BULLISH": "green", "BEARISH": "red", "NEUTRAL": "yellow"}.get(signal, "white")
    try:
        panel = Panel(
            report_text,
            title="[bold]MCX Gold Evening Report[/bold]",
            border_style=color,
            expand=False,
        )
        console.print(panel)
    except Exception:
        # Fallback: encode to ascii with replacement for terminals that lack unicode
        safe = report_text.encode("ascii", errors="replace").decode("ascii")
        print(safe)


def send_telegram(report_text: str, signal: dict):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    sig = signal.get("signal", "N/A")
    confidence = signal.get("confidence", "N/A")
    pred_low = signal.get("predicted_low")
    pred_high = signal.get("predicted_high")
    driver_1 = signal.get("driver_1", "N/A")
    risk_factor = signal.get("risk_factor", "N/A")

    emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(sig, "⬜")

    message = (
        f"*MCX Gold Prediction — {datetime.now(IST).strftime('%d %b %Y')}*\n\n"
        f"{emoji} *Signal:* {sig}\n"
        f"*Confidence:* {confidence}%\n"
        f"*Predicted Open:* {_fmt_inr(pred_low)} – {_fmt_inr(pred_high)}\n\n"
        f"*Key Driver:* {driver_1}\n"
        f"*Risk:* {risk_factor}"
    )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
        if resp.status_code == 200:
            console.print("[green]Telegram message sent[/green]")
        else:
            console.print(f"[yellow]Telegram failed: {resp.status_code} {resp.text}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Telegram error: {e}[/yellow]")
