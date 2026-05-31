from datetime import datetime, timedelta
from rich.console import Console
from config import FRED_API_KEY

console = Console()

FRED_SERIES = {
    "FEDFUNDS":    "Fed Funds Rate",
    "DGS10":       "10Y Treasury Yield",
    "DFII10":      "10Y Real Yield (TIPS)",   # gold's #1 macro enemy — rising real yields hurt gold
    "T10YIE":      "10Y Inflation Breakeven",  # market's inflation expectation — rising = gold bullish
    "CPIAUCSL":    "US CPI",
    "DEXINUS":     "USD/INR (FRED)",
    "DCOILBRENTEU":"Brent Crude (FRED)",       # cross-check against yfinance BZ=F
    "VIXCLS":      "VIX Fear Index",           # spikes in VIX → risk-off → gold up
}


def fetch_macro_data() -> dict:
    if not FRED_API_KEY:
        console.print("[yellow]Warning: FRED_API_KEY not set — skipping macro data[/yellow]")
        return {k: {"latest_value": None, "prev_value": None, "change": None, "change_pct": None, "label": v}
                for k, v in FRED_SERIES.items()}

    try:
        from fredapi import Fred
    except ImportError:
        console.print("[yellow]Warning: fredapi not installed — skipping macro data[/yellow]")
        return {k: {"latest_value": None, "prev_value": None, "change": None, "change_pct": None, "label": v}
                for k, v in FRED_SERIES.items()}

    fred = Fred(api_key=FRED_API_KEY)
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    result = {}

    for series_id, label in FRED_SERIES.items():
        try:
            console.print(f"  Fetching FRED [cyan]{series_id}[/cyan]...")
            series = fred.get_series(series_id, observation_start=start).dropna()

            if series.empty:
                result[series_id] = {
                    "label": label, "latest_value": None, "prev_value": None,
                    "change": None, "change_pct": None,
                }
                continue

            latest = float(series.iloc[-1])
            # 30-day prior value
            cutoff = series.index[-1] - timedelta(days=30)
            prior_series = series[series.index <= cutoff]
            prev = float(prior_series.iloc[-1]) if not prior_series.empty else float(series.iloc[0])

            change = latest - prev
            change_pct = (change / prev * 100) if prev != 0 else None

            result[series_id] = {
                "label": label,
                "latest_value": round(latest, 4),
                "prev_value": round(prev, 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
            }
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to fetch {series_id}: {e}[/yellow]")
            result[series_id] = {
                "label": label, "latest_value": None, "prev_value": None,
                "change": None, "change_pct": None,
            }

    return result
