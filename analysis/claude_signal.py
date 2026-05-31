import re
from datetime import datetime
from zoneinfo import ZoneInfo
from rich.console import Console
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

console = Console()
IST = ZoneInfo("Asia/Kolkata")

SYSTEM_PROMPT = """You are an expert commodities analyst specialising in MCX Gold (Indian market).
You analyse market data and news to predict the next trading day's MCX Gold opening price.
Always think in INR per 10 grams (typical MCX unit).
Be specific with price ranges, not vague. State your confidence honestly.
Structure your response EXACTLY as specified — it will be parsed by code."""


def _fmt(val, prefix="", suffix="", decimals=2, fallback="N/A"):
    if val is None:
        return fallback
    try:
        return f"{prefix}{val:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return fallback


def _pct(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"


def _build_prompt(price_data: dict, macro_data: dict, news_data: dict, features: dict) -> str:
    today = datetime.now(IST).strftime("%d %B %Y")

    # ── Section 1: Price Snapshot ─────────────────────────────────────────
    lines = [
        f"=== MCX GOLD MARKET ANALYSIS — {today} ===",
        "",
        "SECTION 1: PRICE SNAPSHOT",
        f"MCX Gold (NSE proxy):          ₹{_fmt(price_data.get('mcx_close'), decimals=0)} / 10g  ({_pct(price_data.get('mcx_change_pct'))})",
        f"COMEX Gold:                    ${_fmt(price_data.get('comex_close'))} / oz  ({_pct(price_data.get('comex_change_pct'))})",
        f"USD/INR:                       {_fmt(price_data.get('usdinr_close'), decimals=4)}  ({_pct(price_data.get('usdinr_change_pct'))})",
        f"Estimated MCX (COMEX formula): ₹{_fmt(price_data.get('estimated_mcx_from_comex'), decimals=0)} (COMEX × USDINR × 0.3215, pre-duty estimate)",
        f"MCX Local Premium:             ₹{_fmt(price_data.get('mcx_premium'), decimals=0)}",
        f"Gold/Silver Ratio:             {_fmt(price_data.get('gold_silver_ratio'), decimals=1)}",
        f"Nifty 50:                      {_pct(price_data.get('nifty_change_pct'))}",
        f"Brent Crude (India benchmark): ${_fmt(price_data.get('brent_close'))} / bbl  ({_pct(price_data.get('brent_change_pct'))})",
        f"WTI Crude:                     ${_fmt(price_data.get('wti_close'))} / bbl  ({_pct(price_data.get('wti_change_pct'))})",
        "",
    ]

    # ── Section 2: Technical Signals ──────────────────────────────────────
    lines += [
        "SECTION 2: TECHNICAL SIGNALS",
        f"RSI (14-day):      {_fmt(features.get('rsi_14'), decimals=1)} → {features.get('rsi_zone', 'N/A')}",
        f"MACD:              Line={_fmt(features.get('macd_line'), decimals=2)}, Signal={_fmt(features.get('macd_signal'), decimals=2)}, Status={features.get('macd_crossover', 'N/A')}",
        f"Bollinger Bands:   Price at {_fmt(features.get('bb_position', 0), decimals=0, suffix='%') if features.get('bb_position') is not None else 'N/A'} of band (Upper=₹{_fmt(features.get('bb_upper'), decimals=0)}, Lower=₹{_fmt(features.get('bb_lower'), decimals=0)})",
        f"EMA 9/21:          {features.get('ema_crossover', 'N/A')}",
        f"ATR (14-day):      {_fmt(features.get('atr_14'), decimals=2)} (volatility measure)",
        f"1-day change:      {_pct(features.get('price_change_1d'))}",
        f"5-day change:      {_pct(features.get('price_change_5d'))}",
        f"20-day change:     {_pct(features.get('price_change_20d'))}",
        f"10-day volatility: {_fmt(features.get('volatility_10d'), decimals=2, suffix='%')}",
        f"Volume ratio:      {_fmt(features.get('volume_ratio'), decimals=2)}x (vs 20-day avg)",
        "",
    ]

    # ── Section 3: Macro Environment ──────────────────────────────────────
    lines += ["SECTION 3: MACRO ENVIRONMENT"]

    def _macro_line(key, label, note=""):
        m = macro_data.get(key, {})
        if m and m.get("latest_value") is not None:
            chg = m.get("change")
            chg_str = f"  Δ{chg:+.3f} vs 30d ago" if chg is not None else ""
            return f"{label:<30} {m['latest_value']:>8}{chg_str}   {note}"
        return f"{label:<30}      N/A"

    lines += [
        _macro_line("FEDFUNDS", "Fed Funds Rate (%)",        ""),
        _macro_line("DGS10",    "10Y Nominal Yield (%)",     ""),
        _macro_line("DFII10",   "10Y REAL Yield/TIPS (%)",   "← KEY: rising real yield = gold bearish"),
        _macro_line("T10YIE",   "10Y Inflation Breakeven",   "← rising = inflation fears = gold bullish"),
        _macro_line("CPIAUCSL", "US CPI",                    ""),
        _macro_line("DEXINUS",  "USD/INR (FRED cross-check)",""),
        _macro_line("DCOILBRENTEU", "Brent Crude (FRED)",    "cross-check vs live price"),
        _macro_line("VIXCLS",   "VIX Fear Index",            "← >25 = fear/risk-off = gold bullish"),
        "",
        "MACRO INTERPRETATION GUIDE:",
        "  Real yield (DFII10) is gold's most important macro driver.",
        "  When real yields fall → opportunity cost of holding gold drops → gold rises.",
        "  When inflation breakeven (T10YIE) rises → gold is an inflation hedge → gold rises.",
        "  VIX spike above 25 signals market fear — historically gold rallies in these episodes.",
        "",
    ]

    # ── Section 4: News ───────────────────────────────────────────────────
    lines += ["SECTION 4: NEWS HEADLINES (last 24 hours)"]
    all_news = news_data.get("global_news", []) + news_data.get("india_news", [])
    for i, item in enumerate(all_news[:8], 1):
        tag = "[INDIA]" if item.get("type") == "india" else "[GLOBAL]"
        lines.append(f"{i}. {tag} {item.get('title', 'No title')} — {item.get('source', '')}")
    if not all_news:
        lines.append("No news available.")
    lines.append("")

    # ── Section 5: India Context ──────────────────────────────────────────
    festival = news_data.get("festival", {})
    lines += [
        "SECTION 5: INDIA CONTEXT",
        f"Festival Season:  {festival.get('note', 'N/A')}",
        f"USD/INR 1-day:    {_pct(features.get('usdinr_change_1d'))}  (positive = rupee weakening → higher MCX)",
        f"USD/INR 5-day:    {_pct(features.get('usdinr_change_5d'))}",
        f"USD/INR Vol(10d): {_fmt(features.get('usdinr_volatility_10d'), decimals=3, suffix='%')}",
        "",
        "CRUDE OIL — INDIA IMPACT CHANNEL",
        f"Brent 1-day:      {_pct(features.get('brent_change_1d'))}",
        f"Brent 5-day:      {_pct(features.get('brent_change_5d'))}",
        f"Brent 20-day:     {_pct(features.get('brent_change_20d'))}",
        f"Crude-Gold today: {features.get('crude_gold_alignment', 'N/A')}",
        "Note: Rising Brent widens India trade deficit → weakens INR → lifts MCX gold even if COMEX is flat.",
        "",
    ]

    # ── Response format instruction ───────────────────────────────────────
    lines += [
        "=== YOUR TASK ===",
        "Based on all the above data, predict MCX Gold's opening price for the NEXT trading day.",
        "Respond in EXACTLY this format (no extra text before or after):",
        "",
        "SIGNAL: [BULLISH / BEARISH / NEUTRAL]",
        "CONFIDENCE: [number 1-100]%",
        "PREDICTED_OPEN_LOW: [INR value as integer]",
        "PREDICTED_OPEN_HIGH: [INR value as integer]",
        "KEY_DRIVER_1: [one sentence]",
        "KEY_DRIVER_2: [one sentence]",
        "KEY_DRIVER_3: [one sentence]",
        "RISK_FACTOR: [one sentence — what could invalidate this prediction]",
        "INDIA_RUPEE_OUTLOOK: [STRENGTHENING / WEAKENING / STABLE]",
        "REASONING:",
        "[2-3 paragraph narrative explanation]",
    ]

    return "\n".join(lines)


def _parse_response(text: str) -> dict:
    def extract(pattern, default=None):
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else default

    signal = extract(r"^SIGNAL:\s*(.+)$")
    confidence_str = extract(r"^CONFIDENCE:\s*([\d]+)")
    pred_low_str = extract(r"^PREDICTED_OPEN_LOW:\s*([\d,]+)")
    pred_high_str = extract(r"^PREDICTED_OPEN_HIGH:\s*([\d,]+)")

    def parse_num(s):
        if s is None:
            return None
        try:
            return float(s.replace(",", ""))
        except (ValueError, AttributeError):
            return None

    # Extract REASONING block (everything after "REASONING:")
    reasoning_match = re.search(r"^REASONING:\s*\n([\s\S]+)", text, re.MULTILINE | re.IGNORECASE)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else None

    return {
        "signal": signal,
        "confidence": int(confidence_str) if confidence_str and confidence_str.isdigit() else None,
        "predicted_low": parse_num(pred_low_str),
        "predicted_high": parse_num(pred_high_str),
        "driver_1": extract(r"^KEY_DRIVER_1:\s*(.+)$"),
        "driver_2": extract(r"^KEY_DRIVER_2:\s*(.+)$"),
        "driver_3": extract(r"^KEY_DRIVER_3:\s*(.+)$"),
        "risk_factor": extract(r"^RISK_FACTOR:\s*(.+)$"),
        "rupee_outlook": extract(r"^INDIA_RUPEE_OUTLOOK:\s*(.+)$"),
        "reasoning": reasoning,
        "raw_response": text,
    }


def _mock_signal(price_data: dict) -> dict:
    mcx = price_data.get("mcx_close") or 75000
    return {
        "signal": "NEUTRAL",
        "confidence": 50,
        "predicted_low": round(mcx * 0.995),
        "predicted_high": round(mcx * 1.005),
        "driver_1": "MOCK: No API key configured",
        "driver_2": "MOCK: Using placeholder values for testing",
        "driver_3": "MOCK: Pipeline verification mode",
        "risk_factor": "MOCK: Real prediction requires ANTHROPIC_API_KEY",
        "rupee_outlook": "STABLE",
        "reasoning": "This is a mock signal generated because ANTHROPIC_API_KEY is not set. Configure your .env file to enable real predictions.",
        "raw_response": "MOCK RESPONSE",
        "is_mock": True,
    }


def generate_signal(price_data: dict, macro_data: dict, news_data: dict, features: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        console.print("[yellow]Warning: ANTHROPIC_API_KEY not set — returning mock signal[/yellow]")
        return _mock_signal(price_data)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        console.print("[red]Error: anthropic package not installed[/red]")
        return _mock_signal(price_data)

    prompt = _build_prompt(price_data, macro_data, news_data, features)

    console.print("  Sending request to Claude API...")
    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        console.print(f"  Claude responded ({len(raw)} chars)")
        result = _parse_response(raw)
        result["is_mock"] = False
        return result
    except Exception as e:
        console.print(f"[red]Claude API error: {e}[/red]")
        result = _mock_signal(price_data)
        result["error"] = str(e)
        return result
