"""
Supabase sync — writes predictions to cloud DB via REST API (no extra dependencies).
Falls back silently if Supabase is not configured or unreachable.
"""
import requests
from rich.console import Console
from config import DB_PATH

console = Console()

def _get_config():
    import os
    # Try Streamlit secrets first (when running on Streamlit Cloud)
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_KEY", "")
        if url and key:
            return url.rstrip("/"), key
    except Exception:
        pass
    # Fall back to .env / environment variables (local runs)
    from dotenv import load_dotenv
    load_dotenv(override=True)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    return url, key


def _headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }


def push_prediction(date: str, report_text: str = None) -> bool:
    """Read one prediction from local SQLite and upsert it to Supabase."""
    url, key = _get_config()
    if not url or not key:
        return False

    import sqlite3, os
    from config import REPORT_DIR
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM predictions WHERE date = ?", (date,)).fetchone()
        conn.close()
        if not row:
            console.print(f"[yellow]Supabase sync: no local row for {date}[/yellow]")
            return False
        data = dict(row)
        data.pop("id", None)
    except Exception as e:
        console.print(f"[yellow]Supabase sync: failed to read local DB: {e}[/yellow]")
        return False

    # Attach report text — passed directly or read from file
    if report_text:
        data["report_text"] = report_text
    else:
        report_file = os.path.join(REPORT_DIR, f"{date}_gold_report.txt")
        if os.path.exists(report_file):
            with open(report_file, "r", encoding="utf-8") as f:
                data["report_text"] = f.read()

    try:
        h = _headers(key)
        h["Prefer"] = "resolution=merge-duplicates,return=minimal"
        resp = requests.post(
            f"{url}/rest/v1/predictions",
            headers=h,
            json=data,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            console.print(f"[green]Supabase: prediction {date} synced[/green]")
            return True
        # 409 conflict → row exists, use PATCH to update
        if resp.status_code == 409:
            resp2 = requests.patch(
                f"{url}/rest/v1/predictions?date=eq.{date}",
                headers=_headers(key),
                json=data,
                timeout=10,
            )
            if resp2.status_code in (200, 204):
                console.print(f"[green]Supabase: prediction {date} updated[/green]")
                return True
            console.print(f"[yellow]Supabase update failed: {resp2.status_code} {resp2.text[:120]}[/yellow]")
            return False
        console.print(f"[yellow]Supabase sync failed: {resp.status_code} {resp.text[:120]}[/yellow]")
        return False
    except Exception as e:
        console.print(f"[yellow]Supabase sync error: {e}[/yellow]")
        return False


def push_actual(date: str) -> bool:
    """Sync the actual_open + accuracy fields for a date after update_actual() runs."""
    url, key = _get_config()
    if not url or not key:
        return False

    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actual_open, actual_direction, direction_correct, in_range FROM predictions WHERE date = ?",
            (date,)
        ).fetchone()
        conn.close()
        if not row:
            return False
        payload = dict(row)
    except Exception as e:
        console.print(f"[yellow]Supabase actual sync: read error: {e}[/yellow]")
        return False

    try:
        resp = requests.patch(
            f"{url}/rest/v1/predictions?date=eq.{date}",
            headers=_headers(key),
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 204):
            console.print(f"[green]Supabase: actual for {date} synced[/green]")
            return True
        else:
            console.print(f"[yellow]Supabase actual sync failed: {resp.status_code} {resp.text[:120]}[/yellow]")
            return False
    except Exception as e:
        console.print(f"[yellow]Supabase actual sync error: {e}[/yellow]")
        return False


def fetch_all_from_supabase() -> list[dict]:
    """Fetch all predictions from Supabase (used by dashboard)."""
    url, key = _get_config()
    if not url or not key:
        return []

    try:
        resp = requests.get(
            f"{url}/rest/v1/predictions?select=*&order=date.desc",
            headers=_headers(key),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            console.print(f"[yellow]Supabase fetch failed: {resp.status_code} {resp.text[:120]}[/yellow]")
            return []
    except Exception as e:
        console.print(f"[yellow]Supabase fetch error: {e}[/yellow]")
        return []


def test_connection() -> bool:
    url, key = _get_config()
    if not url or not key:
        console.print("[yellow]Supabase not configured[/yellow]")
        return False
    try:
        resp = requests.get(
            f"{url}/rest/v1/predictions?select=id&limit=1",
            headers=_headers(key),
            timeout=10,
        )
        if resp.status_code == 200:
            console.print(f"[green]Supabase connected — {len(resp.json())} rows in predictions table[/green]")
            return True
        else:
            console.print(f"[red]Supabase error: {resp.status_code} {resp.text[:120]}[/red]")
            return False
    except Exception as e:
        console.print(f"[red]Supabase connection failed: {e}[/red]")
        return False
