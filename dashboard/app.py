"""
MCX Gold Predictor — Performance Dashboard
Run with: streamlit run dashboard/app.py
"""
import os
import sys
import glob
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, get_all_predictions, get_accuracy_stats
from db.supabase_sync import fetch_all_from_supabase, test_connection
from config import REPORT_DIR

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCX Gold Predictor",
    page_icon="🥇",
    layout="wide",
)

st.title("🥇 MCX Gold Predictor — Performance Dashboard")

init_db()

if st.button("🔄 Refresh data"):
    st.rerun()

# ── Data source: Supabase (cloud) or local SQLite ────────────────────────────
cloud_data = fetch_all_from_supabase()
if cloud_data:
    all_preds = cloud_data
    st.caption("Data source: Supabase (cloud)")
else:
    all_preds = get_all_predictions()
    st.caption("Data source: local SQLite (Supabase not reachable)")

# Recompute accuracy stats from whichever source we're using
evaluated  = [r for r in all_preds if r.get("direction_correct") is not None]
range_eval = [r for r in all_preds if r.get("in_range") is not None]
confidences = [r["confidence"] for r in all_preds if r.get("confidence")]

def _compute_stats(preds):
    ev  = [r for r in preds if r.get("direction_correct") is not None]
    rev = [r for r in preds if r.get("in_range") is not None]
    confs = [r["confidence"] for r in preds if r.get("confidence")]
    return {
        "total_predictions": len(preds),
        "direction_accuracy_pct": round(sum(r["direction_correct"] for r in ev) / len(ev) * 100, 1) if ev else None,
        "range_accuracy_pct": round(sum(r["in_range"] for r in rev) / len(rev) * 100, 1) if rev else None,
        "avg_confidence": round(sum(confs) / len(confs), 1) if confs else None,
    }

stats = _compute_stats(all_preds)

# ── Guard: not enough data ────────────────────────────────────────────────
if len(all_preds) < 3:
    st.warning(
        f"Only {len(all_preds)} prediction(s) in the database. "
        "Run `python run_evening.py` each evening to build up history. "
        "At least 3 predictions needed to display charts."
    )
    if all_preds:
        st.subheader("Predictions so far")
        df_raw = pd.DataFrame(all_preds)
        st.dataframe(df_raw)
    # Still show the update form even with fewer than 3 predictions

if len(all_preds) >= 3:
    # ── Section 1: Summary metrics ──────────────────────────────────────────
    st.header("📊 Summary Statistics")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Predictions", stats["total_predictions"])
    with col2:
        dir_acc = stats["direction_accuracy_pct"]
        if dir_acc is not None:
            delta = f"{'Good' if dir_acc >= 55 else ('Weak' if dir_acc < 45 else 'Average')}"
            st.metric("Direction Accuracy", f"{dir_acc}%", delta=delta)
        else:
            st.metric("Direction Accuracy", "N/A (no actuals yet)")
    with col3:
        range_acc = stats["range_accuracy_pct"]
        st.metric("Range Accuracy", f"{range_acc}%" if range_acc is not None else "N/A")
    with col4:
        avg_conf = stats["avg_confidence"]
        st.metric("Avg Confidence", f"{avg_conf}%" if avg_conf is not None else "N/A")

    evaluated = [p for p in all_preds if p["direction_correct"] is not None]
    if evaluated:
        sorted_eval = sorted(evaluated, key=lambda x: x["date"])
        streak = 1
        streak_type = "WIN" if sorted_eval[-1]["direction_correct"] == 1 else "LOSS"
        for i in range(len(sorted_eval) - 2, -1, -1):
            if (sorted_eval[i]["direction_correct"] == 1) == (streak_type == "WIN"):
                streak += 1
            else:
                break
        st.info(f"🔥 Current streak: **{streak}-day {streak_type} streak**")

    st.divider()

    # ── Section 2: Prediction vs Actual Chart ─────────────────────────────
    st.header("📈 Predictions vs Actuals")

    df = pd.DataFrame(all_preds)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    range_filter = st.selectbox("Date range", ["Last 7 days", "Last 30 days", "All time"], index=1)
    df_chart = df.tail(7) if range_filter == "Last 7 days" else df.tail(30) if range_filter == "Last 30 days" else df

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.concat([df_chart["date"], df_chart["date"].iloc[::-1]]),
        y=pd.concat([df_chart["predicted_high"], df_chart["predicted_low"].iloc[::-1]]),
        fill="toself", fillcolor="rgba(255, 215, 0, 0.15)",
        line=dict(color="rgba(255,255,255,0)"), name="Predicted Range",
    ))
    fig.add_trace(go.Scatter(
        x=df_chart["date"], y=df_chart["mcx_close"], mode="lines+markers",
        name="MCX Close", line=dict(color="steelblue", width=2), marker=dict(size=5),
    ))
    actuals = df_chart[df_chart["actual_open"].notna()].copy()
    if not actuals.empty:
        colors = actuals["direction_correct"].map({1: "green", 0: "red"}).fillna("gray")
        fig.add_trace(go.Scatter(
            x=actuals["date"], y=actuals["actual_open"], mode="markers",
            name="Actual Open", marker=dict(color=list(colors), size=10, symbol="diamond"),
        ))
    fig.update_layout(xaxis_title="Date", yaxis_title="MCX Gold (INR / 10g)",
                      hovermode="x unified", height=420)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Section 3: Signal History Table ───────────────────────────────────
    st.header("📋 Signal History")

    df_table = df.sort_values("date", ascending=False).copy()
    df_table["date"] = df_table["date"].dt.strftime("%Y-%m-%d")
    df_table["Predicted Range"] = df_table.apply(
        lambda r: f"Rs.{int(r['predicted_low']):,} - Rs.{int(r['predicted_high']):,}"
        if pd.notna(r["predicted_low"]) and pd.notna(r["predicted_high"]) else "N/A", axis=1)
    df_table["Actual Open"] = df_table["actual_open"].apply(
        lambda v: f"Rs.{int(v):,}" if pd.notna(v) else "-")
    df_table["Correct?"] = df_table["direction_correct"].map({1: "YES", 0: "NO"}).fillna("-")
    df_table["In Range?"] = df_table["in_range"].map({1: "YES", 0: "NO"}).fillna("-")
    df_table["Conf%"] = df_table["confidence"].apply(lambda v: f"{v}%" if pd.notna(v) else "N/A")
    display_cols = {"date": "Date", "signal": "Signal", "Conf%": "Conf%",
                    "Predicted Range": "Predicted Range", "Actual Open": "Actual Open",
                    "Correct?": "Correct?", "In Range?": "In Range?"}
    st.dataframe(df_table[list(display_cols.keys())].rename(columns=display_cols),
                 use_container_width=True, hide_index=True)

    st.divider()

    # ── Section 4: Confidence Calibration ─────────────────────────────────
    st.header("🎯 Confidence Calibration")
    conf_data = stats.get("confidence_vs_accuracy", {})
    if conf_data:
        bands = list(conf_data.keys())
        accuracies = [conf_data[b]["accuracy_pct"] for b in bands]
        counts = [conf_data[b]["count"] for b in bands]
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=bands, y=accuracies,
            text=[f"{a}%<br>({c} preds)" for a, c in zip(accuracies, counts)],
            textposition="auto",
            marker_color=["green" if a >= 60 else "orange" if a >= 45 else "red" for a in accuracies],
        ))
        fig2.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50% (random)")
        fig2.update_layout(xaxis_title="Confidence Band", yaxis_title="Direction Accuracy %",
                           yaxis=dict(range=[0, 100]), height=350)
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("Is Claude well-calibrated? Higher confidence should yield higher accuracy.")
    else:
        st.info("Not enough evaluated predictions to show calibration chart.")

    st.divider()

    # ── Section 5: Last Report Viewer ─────────────────────────────────────
    st.header("📄 Latest Evening Report")
    reports_with_text = [r for r in all_preds if r.get("report_text")]
    if reports_with_text:
        dates = [r["date"] for r in reports_with_text]
        selected_date = st.selectbox("Select report date", dates)
        selected_report = next(r for r in reports_with_text if r["date"] == selected_date)
        st.code(selected_report["report_text"], language=None)
    else:
        report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), REPORT_DIR)
        report_files = sorted(glob.glob(os.path.join(report_dir, "*.txt")), reverse=True)
        if report_files:
            selected = st.selectbox("Select report", report_files,
                                    format_func=lambda p: os.path.basename(p))
            with open(selected, "r", encoding="utf-8") as f:
                st.code(f.read(), language=None)
        else:
            st.info("No reports available yet. Run the evening script to generate one.")

# ── Section 6: Update Actual Open Price ───────────────────────────────────
st.divider()
st.header("✏️ Update Actual Open Price")
st.caption("Use this every morning to record the actual MCX Gold opening price.")

with st.expander("Open update form"):
    # Simple password protection via Streamlit secrets or hardcoded
    try:
        import streamlit as _st
        update_password = _st.secrets.get("UPDATE_PASSWORD", "gold2026")
    except Exception:
        update_password = os.environ.get("UPDATE_PASSWORD", "gold2026")

    col1, col2, col3 = st.columns(3)
    with col1:
        upd_date = st.date_input(
            "Prediction date",
            value=datetime.now().date(),
            help="The date of the prediction (yesterday's date usually)",
        )
    with col2:
        upd_price = st.number_input(
            "Actual MCX open price (INR/10g)",
            min_value=50000.0,
            max_value=300000.0,
            value=130000.0,
            step=100.0,
            help="Check mcxindia.com for the Gold June futures opening price",
        )
    with col3:
        upd_password = st.text_input("Password", type="password", help="Required to submit")

    if st.button("Submit Actual Price", type="primary"):
        if upd_password != update_password:
            st.error("Incorrect password.")
        else:
            date_str = upd_date.strftime("%Y-%m-%d")
            # Update Supabase directly
            url, key = None, None
            try:
                url = st.secrets.get("SUPABASE_URL", "")
                key = st.secrets.get("SUPABASE_KEY", "")
            except Exception:
                import os as _os
                url = _os.environ.get("SUPABASE_URL", "")
                key = _os.environ.get("SUPABASE_KEY", "")

            if not url or not key:
                st.error("Supabase not configured.")
            else:
                import requests as _req
                from datetime import datetime as _dt

                # First fetch the prediction to compute accuracy
                headers = {
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                fetch = _req.get(
                    f"{url}/rest/v1/predictions?date=eq.{date_str}&select=*",
                    headers=headers, timeout=10,
                )
                rows = fetch.json() if fetch.status_code == 200 else []

                if not rows:
                    st.error(f"No prediction found for {date_str}. Run the evening script first.")
                else:
                    pred = rows[0]
                    mcx_close = pred.get("mcx_close")
                    signal = pred.get("signal")
                    pred_low = pred.get("predicted_low")
                    pred_high = pred.get("predicted_high")

                    actual_direction = "UP" if upd_price > mcx_close else "DOWN" if mcx_close else None
                    direction_correct = None
                    if signal == "BULLISH":
                        direction_correct = 1 if actual_direction == "UP" else 0
                    elif signal == "BEARISH":
                        direction_correct = 1 if actual_direction == "DOWN" else 0

                    in_range = None
                    if pred_low and pred_high:
                        in_range = 1 if pred_low <= upd_price <= pred_high else 0

                    payload = {
                        "actual_open": upd_price,
                        "actual_direction": actual_direction,
                        "direction_correct": direction_correct,
                        "in_range": in_range,
                    }
                    resp = _req.patch(
                        f"{url}/rest/v1/predictions?date=eq.{date_str}",
                        headers=headers, json=payload, timeout=10,
                    )

                    if resp.status_code in (200, 204):
                        result = "CORRECT" if direction_correct == 1 else "WRONG" if direction_correct == 0 else "N/A"
                        in_range_txt = "Yes" if in_range == 1 else "No" if in_range == 0 else "N/A"
                        st.success(
                            f"Updated {date_str}!\n\n"
                            f"Actual open: Rs.{int(upd_price):,}\n"
                            f"Signal was: {signal} — Direction: {result}\n"
                            f"In predicted range: {in_range_txt}"
                        )
                        st.rerun()
                    else:
                        st.error(f"Update failed: {resp.status_code} {resp.text[:100]}")

# ── Footer ────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "MCX Gold Predictor | Powered by Claude AI | "
    f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)
