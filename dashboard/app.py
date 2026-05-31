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
    st.stop()

# ── Section 1: Summary metrics ────────────────────────────────────────────
st.header("📊 Summary Statistics")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Predictions", stats["total_predictions"])

with col2:
    dir_acc = stats["direction_accuracy_pct"]
    if dir_acc is not None:
        color = "normal" if dir_acc >= 55 else ("off" if dir_acc < 45 else "normal")
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

# Win/loss streak
evaluated = [p for p in all_preds if p["direction_correct"] is not None]
if evaluated:
    sorted_eval = sorted(evaluated, key=lambda x: x["date"])
    streak = 1
    streak_type = "WIN" if sorted_eval[-1]["direction_correct"] == 1 else "LOSS"
    for i in range(len(sorted_eval) - 2, -1, -1):
        same = (sorted_eval[i]["direction_correct"] == 1) == (streak_type == "WIN")
        if same:
            streak += 1
        else:
            break
    streak_label = f"{streak}-day {streak_type} streak"
    st.info(f"🔥 Current streak: **{streak_label}**")

st.divider()

# ── Section 2: Prediction vs Actual Chart ─────────────────────────────────
st.header("📈 Predictions vs Actuals")

df = pd.DataFrame(all_preds)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date")

range_filter = st.selectbox("Date range", ["Last 7 days", "Last 30 days", "All time"], index=1)
if range_filter == "Last 7 days":
    df_chart = df.tail(7)
elif range_filter == "Last 30 days":
    df_chart = df.tail(30)
else:
    df_chart = df

fig = go.Figure()

# Shaded prediction band
fig.add_trace(go.Scatter(
    x=pd.concat([df_chart["date"], df_chart["date"].iloc[::-1]]),
    y=pd.concat([df_chart["predicted_high"], df_chart["predicted_low"].iloc[::-1]]),
    fill="toself",
    fillcolor="rgba(255, 215, 0, 0.15)",
    line=dict(color="rgba(255,255,255,0)"),
    name="Predicted Range",
    showlegend=True,
))

# Actual MCX close
fig.add_trace(go.Scatter(
    x=df_chart["date"], y=df_chart["mcx_close"],
    mode="lines+markers",
    name="MCX Close (used as basis)",
    line=dict(color="steelblue", width=2),
    marker=dict(size=5),
))

# Actual open with colour coding
actuals = df_chart[df_chart["actual_open"].notna()].copy()
if not actuals.empty:
    colors = actuals["direction_correct"].map({1: "green", 0: "red"}).fillna("gray")
    fig.add_trace(go.Scatter(
        x=actuals["date"], y=actuals["actual_open"],
        mode="markers",
        name="Actual Open",
        marker=dict(color=list(colors), size=10, symbol="diamond"),
    ))

fig.update_layout(
    xaxis_title="Date",
    yaxis_title="MCX Gold (INR / 10g)",
    hovermode="x unified",
    height=420,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Section 3: Signal History Table ───────────────────────────────────────
st.header("📋 Signal History")

df_table = df.sort_values("date", ascending=False).copy()
df_table["date"] = df_table["date"].dt.strftime("%Y-%m-%d")
df_table["Predicted Range"] = df_table.apply(
    lambda r: f"₹{int(r['predicted_low']):,} – ₹{int(r['predicted_high']):,}"
    if pd.notna(r["predicted_low"]) and pd.notna(r["predicted_high"]) else "N/A",
    axis=1
)
df_table["Actual Open"] = df_table["actual_open"].apply(
    lambda v: f"₹{int(v):,}" if pd.notna(v) else "—"
)
df_table["Correct?"] = df_table["direction_correct"].map({1: "✅", 0: "❌"}).fillna("—")
df_table["In Range?"] = df_table["in_range"].map({1: "✅", 0: "❌"}).fillna("—")
df_table["Conf%"] = df_table["confidence"].apply(lambda v: f"{v}%" if pd.notna(v) else "N/A")

display_cols = {
    "date": "Date",
    "signal": "Signal",
    "Conf%": "Conf%",
    "Predicted Range": "Predicted Range",
    "Actual Open": "Actual Open",
    "Correct?": "Correct?",
    "In Range?": "In Range?",
}
st.dataframe(
    df_table[list(display_cols.keys())].rename(columns=display_cols),
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ── Section 4: Confidence Calibration ─────────────────────────────────────
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
        name="Accuracy %",
    ))
    fig2.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50% (random)")
    fig2.update_layout(
        xaxis_title="Confidence Band",
        yaxis_title="Direction Accuracy %",
        yaxis=dict(range=[0, 100]),
        height=350,
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("Is Claude well-calibrated? Higher confidence should yield higher accuracy.")
else:
    st.info("Not enough evaluated predictions to show calibration chart.")

st.divider()

# ── Section 5: Last Report Viewer ─────────────────────────────────────────
st.header("📄 Latest Evening Report")

# Try Supabase first (cloud), then local files
reports_with_text = [r for r in all_preds if r.get("report_text")]

if reports_with_text:
    dates = [r["date"] for r in reports_with_text]
    selected_date = st.selectbox("Select report date", dates)
    selected_report = next(r for r in reports_with_text if r["date"] == selected_date)
    st.code(selected_report["report_text"], language=None)
else:
    # Fall back to local .txt files
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), REPORT_DIR)
    report_files = sorted(glob.glob(os.path.join(report_dir, "*.txt")), reverse=True)
    if report_files:
        selected = st.selectbox(
            "Select report",
            report_files,
            format_func=lambda p: os.path.basename(p),
        )
        with open(selected, "r", encoding="utf-8") as f:
            content = f.read()
        st.code(content, language=None)
    else:
        st.info("No reports available yet. Run the evening script to generate one.")

# ── Footer ────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "MCX Gold Predictor | Powered by Claude AI | "
    f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)
