import warnings
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from rich.console import Console
from config import (
    MCX_TICKER, COMEX_TICKER, USDINR_TICKER,
    NIFTY_TICKER, SILVER_TICKER, DXY_TICKER, BRENT_TICKER, WTI_TICKER,
    LOOKBACK_DAYS, TROY_OZ_TO_10G,
)

warnings.filterwarnings("ignore")
console = Console()

TICKERS = {
    "mcx": MCX_TICKER,
    "comex": COMEX_TICKER,
    "usdinr": USDINR_TICKER,
    "nifty": NIFTY_TICKER,
    "silver": SILVER_TICKER,
    "dxy": DXY_TICKER,
    "brent": BRENT_TICKER,
    "wti": WTI_TICKER,
}


def _fetch_ticker(key: str, ticker: str, period: str = "60d") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            console.print(f"[yellow]Warning: No data returned for {ticker} ({key})[/yellow]")
            return None
        df.index = pd.to_datetime(df.index)
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to fetch {ticker} ({key}): {e}[/yellow]")
        return None


def _safe_last(df: pd.DataFrame, col: str = "Close"):
    if df is None or df.empty:
        return None
    try:
        val = df[col].dropna().iloc[-1]
        return float(val)
    except Exception:
        return None


def _pct_change(df: pd.DataFrame, col: str = "Close") -> float | None:
    if df is None or len(df) < 2:
        return None
    try:
        series = df[col].dropna()
        if len(series) < 2:
            return None
        return float((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100)
    except Exception:
        return None


def fetch_all_price_data() -> dict:
    data = {}

    for key, ticker in TICKERS.items():
        console.print(f"  Fetching [cyan]{key}[/cyan] ({ticker})...")
        data[key] = _fetch_ticker(key, ticker)

    comex_close = _safe_last(data.get("comex"))
    usdinr_close = _safe_last(data.get("usdinr"))
    silver_close = _safe_last(data.get("silver"))
    mcx_close = _safe_last(data.get("mcx"))
    brent_close = _safe_last(data.get("brent"))
    wti_close = _safe_last(data.get("wti"))

    # Derived calculations
    estimated_mcx = None
    if comex_close and usdinr_close:
        estimated_mcx = comex_close * usdinr_close * TROY_OZ_TO_10G

    gold_silver_ratio = None
    if comex_close and silver_close and silver_close > 0:
        gold_silver_ratio = comex_close / silver_close

    mcx_premium = None
    if mcx_close and estimated_mcx:
        mcx_premium = mcx_close - estimated_mcx

    # GOLDBEES.NS: each unit tracks ~0.01g of gold; scale to INR/10g for MCX parity.
    # Note: GOLDBEES already includes import duty + GST in its NAV, so mcx_premium
    # vs the pre-duty COMEX formula will be negative by design (~9-12%).
    if mcx_close is not None:
        mcx_close = mcx_close * 1000

    return {
        # Raw DataFrames
        "mcx": data.get("mcx"),
        "comex": data.get("comex"),
        "usdinr": data.get("usdinr"),
        "nifty": data.get("nifty"),
        "silver": data.get("silver"),
        "dxy": data.get("dxy"),
        "brent": data.get("brent"),
        "wti": data.get("wti"),
        # Derived scalar values for today
        "mcx_close": mcx_close,
        "comex_close": comex_close,
        "usdinr_close": usdinr_close,
        "silver_close": silver_close,
        "brent_close": brent_close,
        "wti_close": wti_close,
        "mcx_change_pct": _pct_change(data.get("mcx")),
        "comex_change_pct": _pct_change(data.get("comex")),
        "usdinr_change_pct": _pct_change(data.get("usdinr")),
        "nifty_change_pct": _pct_change(data.get("nifty")),
        "brent_change_pct": _pct_change(data.get("brent")),
        "wti_change_pct": _pct_change(data.get("wti")),
        "estimated_mcx_from_comex": estimated_mcx,
        "gold_silver_ratio": gold_silver_ratio,
        "mcx_premium": mcx_premium,
    }
