import pandas as pd
import numpy as np
from rich.console import Console

console = Console()


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def build_features(price_data: dict) -> dict:
    features = {}

    comex_df = price_data.get("comex")
    usdinr_df = price_data.get("usdinr")

    if comex_df is None or comex_df.empty:
        console.print("[yellow]Warning: COMEX data unavailable — features will be empty[/yellow]")
        return features

    close = comex_df["Close"].dropna().copy()
    high = comex_df["High"].dropna().copy() if "High" in comex_df else close
    low = comex_df["Low"].dropna().copy() if "Low" in comex_df else close
    volume = comex_df["Volume"].dropna().copy() if "Volume" in comex_df else pd.Series(dtype=float)

    # ── RSI 14 ──────────────────────────────────────────────────────────────
    try:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi_val = _safe_float(rsi.iloc[-1]) if len(rsi) > 0 else None
        features["rsi_14"] = rsi_val
        if rsi_val is not None:
            if rsi_val < 30:
                features["rsi_zone"] = "OVERSOLD"
            elif rsi_val > 70:
                features["rsi_zone"] = "OVERBOUGHT"
            else:
                features["rsi_zone"] = "NEUTRAL"
        features["is_oversold"] = rsi_val is not None and rsi_val < 30
        features["is_overbought"] = rsi_val is not None and rsi_val > 70
    except Exception as e:
        console.print(f"[yellow]RSI calculation failed: {e}[/yellow]")

    # ── MACD (12, 26, 9) ────────────────────────────────────────────────────
    try:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        features["macd_line"] = _safe_float(macd_line.iloc[-1])
        features["macd_signal"] = _safe_float(signal_line.iloc[-1])
        features["macd_histogram"] = _safe_float(histogram.iloc[-1])

        if len(macd_line) >= 2:
            prev_cross = macd_line.iloc[-2] - signal_line.iloc[-2]
            curr_cross = macd_line.iloc[-1] - signal_line.iloc[-1]
            if prev_cross < 0 and curr_cross >= 0:
                features["macd_crossover"] = "BULLISH_CROSS"
            elif prev_cross > 0 and curr_cross <= 0:
                features["macd_crossover"] = "BEARISH_CROSS"
            elif curr_cross > 0:
                features["macd_crossover"] = "BULLISH"
            else:
                features["macd_crossover"] = "BEARISH"
        else:
            features["macd_crossover"] = None
    except Exception as e:
        console.print(f"[yellow]MACD calculation failed: {e}[/yellow]")

    # ── Bollinger Bands (20, 2) ──────────────────────────────────────────────
    try:
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        features["bb_upper"] = _safe_float(bb_upper.iloc[-1])
        features["bb_lower"] = _safe_float(bb_lower.iloc[-1])
        features["bb_mid"] = _safe_float(bb_mid.iloc[-1])

        curr_close = _safe_float(close.iloc[-1])
        bbu = _safe_float(bb_upper.iloc[-1])
        bbl = _safe_float(bb_lower.iloc[-1])
        if curr_close and bbu and bbl and (bbu - bbl) > 0:
            features["bb_position"] = (curr_close - bbl) / (bbu - bbl)
        else:
            features["bb_position"] = None
    except Exception as e:
        console.print(f"[yellow]Bollinger calculation failed: {e}[/yellow]")

    # ── ATR 14 ───────────────────────────────────────────────────────────────
    try:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        features["atr_14"] = _safe_float(atr.iloc[-1])
    except Exception as e:
        console.print(f"[yellow]ATR calculation failed: {e}[/yellow]")

    # ── EMA 9 / 21 ───────────────────────────────────────────────────────────
    try:
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        features["ema_9"] = _safe_float(ema9.iloc[-1])
        features["ema_21"] = _safe_float(ema21.iloc[-1])

        if len(ema9) >= 2:
            prev = ema9.iloc[-2] - ema21.iloc[-2]
            curr = ema9.iloc[-1] - ema21.iloc[-1]
            if prev < 0 and curr >= 0:
                features["ema_crossover"] = "BULLISH_CROSS"
            elif prev > 0 and curr <= 0:
                features["ema_crossover"] = "BEARISH_CROSS"
            elif curr > 0:
                features["ema_crossover"] = "BULLISH"
            else:
                features["ema_crossover"] = "BEARISH"
        else:
            features["ema_crossover"] = None
    except Exception as e:
        console.print(f"[yellow]EMA calculation failed: {e}[/yellow]")

    # ── Momentum ─────────────────────────────────────────────────────────────
    try:
        if len(close) >= 2:
            features["price_change_1d"] = _safe_float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
        if len(close) >= 6:
            features["price_change_5d"] = _safe_float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100)
        if len(close) >= 21:
            features["price_change_20d"] = _safe_float((close.iloc[-1] - close.iloc[-21]) / close.iloc[-21] * 100)

        returns = close.pct_change().dropna()
        if len(returns) >= 10:
            features["volatility_10d"] = _safe_float(returns.iloc[-10:].std() * 100)

        if not volume.empty and len(volume) >= 20:
            vol_avg = volume.iloc[-20:].mean()
            if vol_avg > 0:
                features["volume_ratio"] = _safe_float(volume.iloc[-1] / vol_avg)
    except Exception as e:
        console.print(f"[yellow]Momentum calculation failed: {e}[/yellow]")

    # ── USD/INR features ─────────────────────────────────────────────────────
    if usdinr_df is not None and not usdinr_df.empty:
        try:
            fx = usdinr_df["Close"].dropna()
            if len(fx) >= 2:
                features["usdinr_change_1d"] = _safe_float((fx.iloc[-1] - fx.iloc[-2]) / fx.iloc[-2] * 100)
            if len(fx) >= 6:
                features["usdinr_change_5d"] = _safe_float((fx.iloc[-1] - fx.iloc[-6]) / fx.iloc[-6] * 100)
            fx_returns = fx.pct_change().dropna()
            if len(fx_returns) >= 10:
                features["usdinr_volatility_10d"] = _safe_float(fx_returns.iloc[-10:].std() * 100)
        except Exception as e:
            console.print(f"[yellow]USD/INR feature calculation failed: {e}[/yellow]")

    # ── USD/INR features ─────────────────────────────────────────────────────
    if usdinr_df is not None and not usdinr_df.empty:
        pass  # already computed above

    # ── Crude Oil features (Brent — India's import benchmark) ────────────────
    brent_df = price_data.get("brent")
    wti_df = price_data.get("wti")
    for label, crude_df in (("brent", brent_df), ("wti", wti_df)):
        if crude_df is not None and not crude_df.empty:
            try:
                c = crude_df["Close"].dropna()
                if len(c) >= 2:
                    features[f"{label}_change_1d"] = _safe_float((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100)
                if len(c) >= 6:
                    features[f"{label}_change_5d"] = _safe_float((c.iloc[-1] - c.iloc[-6]) / c.iloc[-6] * 100)
                if len(c) >= 21:
                    features[f"{label}_change_20d"] = _safe_float((c.iloc[-1] - c.iloc[-21]) / c.iloc[-21] * 100)
                c_ret = c.pct_change().dropna()
                if len(c_ret) >= 10:
                    features[f"{label}_volatility_10d"] = _safe_float(c_ret.iloc[-10:].std() * 100)
            except Exception as e:
                console.print(f"[yellow]{label} feature calculation failed: {e}[/yellow]")

    # Crude-gold correlation signal: if both crude and gold rising → inflation fear confirmed
    brent_1d = features.get("brent_change_1d")
    comex_1d = features.get("price_change_1d")
    if brent_1d is not None and comex_1d is not None:
        if brent_1d > 0 and comex_1d > 0:
            features["crude_gold_alignment"] = "BOTH_RISING"
        elif brent_1d < 0 and comex_1d < 0:
            features["crude_gold_alignment"] = "BOTH_FALLING"
        elif brent_1d > 1.0 and comex_1d < 0:
            features["crude_gold_alignment"] = "CRUDE_UP_GOLD_DOWN"  # unusual — watch rupee
        else:
            features["crude_gold_alignment"] = "DIVERGING"

    # ── Derived signals ───────────────────────────────────────────────────────
    features["gold_silver_ratio"] = price_data.get("gold_silver_ratio")
    features["mcx_premium"] = price_data.get("mcx_premium")
    features["estimated_mcx_from_comex"] = price_data.get("estimated_mcx_from_comex")

    return features
