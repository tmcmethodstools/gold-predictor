import sqlite3
from datetime import datetime
from config import DB_PATH


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                date             TEXT UNIQUE,
                mcx_close        REAL,
                comex_close      REAL,
                usdinr_close     REAL,
                rsi_14           REAL,
                signal           TEXT,
                confidence       INTEGER,
                predicted_low    REAL,
                predicted_high   REAL,
                predicted_mid    REAL,
                driver_1         TEXT,
                driver_2         TEXT,
                driver_3         TEXT,
                risk_factor      TEXT,
                rupee_outlook    TEXT,
                actual_open      REAL,
                actual_direction TEXT,
                direction_correct INTEGER,
                in_range         INTEGER,
                created_at       TEXT
            )
        """)
        conn.commit()


def save_prediction(date: str, data: dict):
    predicted_mid = None
    if data.get("predicted_low") and data.get("predicted_high"):
        try:
            predicted_mid = (float(data["predicted_low"]) + float(data["predicted_high"])) / 2
        except (TypeError, ValueError):
            pass

    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO predictions
            (date, mcx_close, comex_close, usdinr_close, rsi_14, signal, confidence,
             predicted_low, predicted_high, predicted_mid, driver_1, driver_2, driver_3,
             risk_factor, rupee_outlook, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date,
            data.get("mcx_close"),
            data.get("comex_close"),
            data.get("usdinr_close"),
            data.get("rsi_14"),
            data.get("signal"),
            data.get("confidence"),
            data.get("predicted_low"),
            data.get("predicted_high"),
            predicted_mid,
            data.get("driver_1"),
            data.get("driver_2"),
            data.get("driver_3"),
            data.get("risk_factor"),
            data.get("rupee_outlook"),
            datetime.now().isoformat(),
        ))
        conn.commit()


def update_actual(date: str, actual_open: float):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT signal, mcx_close, predicted_low, predicted_high FROM predictions WHERE date = ?",
            (date,)
        ).fetchone()

        if not row:
            return False

        signal, mcx_close, pred_low, pred_high = row

        actual_direction = None
        direction_correct = None
        if mcx_close and actual_open:
            actual_direction = "UP" if actual_open > mcx_close else "DOWN"
            if signal == "BULLISH":
                direction_correct = 1 if actual_direction == "UP" else 0
            elif signal == "BEARISH":
                direction_correct = 1 if actual_direction == "DOWN" else 0
            else:
                direction_correct = None  # NEUTRAL — no directional call

        in_range = None
        if pred_low and pred_high and actual_open:
            in_range = 1 if pred_low <= actual_open <= pred_high else 0

        conn.execute("""
            UPDATE predictions
            SET actual_open = ?, actual_direction = ?, direction_correct = ?, in_range = ?
            WHERE date = ?
        """, (actual_open, actual_direction, direction_correct, in_range, date))
        conn.commit()
        return True


def get_all_predictions() -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM predictions ORDER BY date DESC").fetchall()
        return [dict(r) for r in rows]


def get_recent(n: int = 30) -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM predictions ORDER BY date DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_accuracy_stats() -> dict:
    rows = get_all_predictions()
    evaluated = [r for r in rows if r["direction_correct"] is not None]
    range_evaluated = [r for r in rows if r["in_range"] is not None]

    if not rows:
        return {
            "total_predictions": 0,
            "direction_accuracy_pct": None,
            "range_accuracy_pct": None,
            "avg_confidence": None,
            "confidence_vs_accuracy": {},
        }

    direction_acc = (
        round(sum(r["direction_correct"] for r in evaluated) / len(evaluated) * 100, 1)
        if evaluated else None
    )
    range_acc = (
        round(sum(r["in_range"] for r in range_evaluated) / len(range_evaluated) * 100, 1)
        if range_evaluated else None
    )
    confidences = [r["confidence"] for r in rows if r["confidence"]]
    avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else None

    # Confidence band calibration
    bands = {"50-60": [], "60-70": [], "70-80": [], "80+": []}
    for r in evaluated:
        c = r["confidence"]
        if c is None:
            continue
        if c < 60:
            bands["50-60"].append(r["direction_correct"])
        elif c < 70:
            bands["60-70"].append(r["direction_correct"])
        elif c < 80:
            bands["70-80"].append(r["direction_correct"])
        else:
            bands["80+"].append(r["direction_correct"])

    conf_vs_acc = {}
    for band, results in bands.items():
        if results:
            conf_vs_acc[band] = {
                "count": len(results),
                "accuracy_pct": round(sum(results) / len(results) * 100, 1),
            }

    return {
        "total_predictions": len(rows),
        "evaluated_count": len(evaluated),
        "direction_accuracy_pct": direction_acc,
        "range_accuracy_pct": range_acc,
        "avg_confidence": avg_conf,
        "confidence_vs_accuracy": conf_vs_acc,
    }


def prediction_exists(date: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM predictions WHERE date = ?", (date,)
        ).fetchone()
        return row is not None
