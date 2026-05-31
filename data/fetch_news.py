import time as _time
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from rich.console import Console
from config import NEWS_API_KEY, FESTIVAL_DATES, FESTIVAL_WINDOW_DAYS

console = Console()

INDIA_RSS_FEEDS = [
    ("Livemint Markets", "https://www.livemint.com/rss/markets"),
    ("Livemint Economy", "https://www.livemint.com/rss/economy"),
    ("BusinessLine Markets", "https://www.thehindubusinessline.com/markets/?service=rss"),
    ("RBI Press Releases", "https://www.rbi.org.in/scripts/rss.aspx"),
]

GOLD_KEYWORDS = ["gold", "mcx", "rupee", "rbi", "commodity", "silver", "bullion", "inr", "rate", "metal"]

NEWSAPI_QUERIES = [
    "gold price",
    "MCX gold India",
    "gold rupee India commodity",
]

# Widen the window: RSS feeds often lag or have timezone quirks
RSS_RECENCY_HOURS = 72


def _parse_entry_date(entry) -> datetime | None:
    """Try to extract a timezone-aware datetime from an RSS entry."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                # feedparser returns struct_time in UTC — use calendar.timegm, NOT mktime
                # mktime() interprets the struct as *local* time, causing an IST offset error
                import calendar
                ts = calendar.timegm(t)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
    # Try parsing the raw published string as a last resort
    raw = getattr(entry, "published", "") or getattr(entry, "updated", "")
    if raw:
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%dT%H:%M:%S%z",
        ):
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
    return None


def _is_recent(entry, hours: int = RSS_RECENCY_HOURS) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    dt = _parse_entry_date(entry)
    if dt is None:
        # No date found — include the article rather than silently drop it
        return True
    return dt >= cutoff


def _is_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in GOLD_KEYWORDS)


def fetch_global_news() -> list[dict]:
    if not NEWS_API_KEY:
        console.print("[yellow]Warning: NEWS_API_KEY not set — skipping global news[/yellow]")
        return []

    articles = []

    # Strategy 1: top-headlines (most reliable on free tier, no date restriction)
    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"q": "gold", "language": "en", "pageSize": 5, "apiKey": NEWS_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        for a in resp.json().get("articles", []):
            title = a.get("title") or ""
            if _is_relevant(title + " " + (a.get("description") or "")):
                articles.append({
                    "title": title,
                    "description": (a.get("description") or "")[:200],
                    "source": (a.get("source") or {}).get("name", ""),
                    "published_at": a.get("publishedAt", ""),
                    "type": "global",
                })
        console.print(f"  top-headlines: {len(articles)} relevant gold articles")
    except Exception as e:
        console.print(f"[yellow]Warning: NewsAPI top-headlines failed: {e}[/yellow]")

    # Strategy 2: everything endpoint — last 3 days to avoid indexing lag
    from_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    for query in NEWSAPI_QUERIES:
        if len(articles) >= 10:
            break
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "sortBy": "publishedAt",
                    "pageSize": 5,
                    "language": "en",
                    "apiKey": NEWS_API_KEY,
                    "from": from_date,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ok":
                console.print(f"[yellow]NewsAPI '{query}': {data.get('message','unknown error')}[/yellow]")
                continue
            added = 0
            for a in data.get("articles", []):
                title = a.get("title") or ""
                if any(a["title"] == x["title"] for x in articles):
                    continue  # deduplicate
                articles.append({
                    "title": title,
                    "description": (a.get("description") or "")[:200],
                    "source": (a.get("source") or {}).get("name", ""),
                    "published_at": a.get("publishedAt", ""),
                    "type": "global",
                })
                added += 1
            console.print(f"  everything '{query}': {added} articles")
        except Exception as e:
            console.print(f"[yellow]Warning: NewsAPI query '{query}' failed: {e}[/yellow]")

    return articles[:10]


def fetch_india_news() -> list[dict]:
    articles = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
    }

    for feed_name, feed_url in INDIA_RSS_FEEDS:
        try:
            console.print(f"  RSS [cyan]{feed_name}[/cyan]...")
            # Fetch via requests first so we can set User-Agent (feedparser's default is blocked by some sites)
            try:
                r = requests.get(feed_url, headers=headers, timeout=10)
                feed = feedparser.parse(r.text)
            except Exception:
                feed = feedparser.parse(feed_url)
            feed_count = 0
            skipped_date = 0
            skipped_relevance = 0

            for entry in feed.entries:
                text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                recent = _is_recent(entry)
                relevant = _is_relevant(text)

                if not recent:
                    skipped_date += 1
                    continue
                if not relevant:
                    skipped_relevance += 1
                    continue

                articles.append({
                    "title": entry.get("title", "").strip(),
                    "description": entry.get("summary", "")[:200].strip(),
                    "source": feed_name,
                    "published_at": entry.get("published", ""),
                    "type": "india",
                })
                feed_count += 1

            total = len(feed.entries)
            console.print(
                f"    {total} entries → {feed_count} kept "
                f"({skipped_date} too old, {skipped_relevance} not relevant)"
            )
        except Exception as e:
            console.print(f"[yellow]Warning: RSS feed {feed_name} failed: {e}[/yellow]")

    return articles[:10]


def check_festival_season() -> dict:
    today = datetime.now().date()
    active_festivals = []

    for name, date_str in FESTIVAL_DATES.items():
        try:
            festival_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_diff = abs((today - festival_date).days)
            if days_diff <= FESTIVAL_WINDOW_DAYS:
                active_festivals.append({
                    "name": name,
                    "date": date_str,
                    "days_away": (festival_date - today).days,
                })
        except ValueError:
            pass

    return {
        "is_festival_season": len(active_festivals) > 0,
        "active_festivals": active_festivals,
        "note": "FESTIVAL SEASON ACTIVE — elevated gold demand expected" if active_festivals else "No major festival within 14 days",
    }


def fetch_all_news() -> dict:
    console.print("  Fetching global news (NewsAPI)...")
    global_news = fetch_global_news()

    console.print("  Fetching India RSS feeds...")
    india_news = fetch_india_news()

    festival_info = check_festival_season()

    total = len(global_news) + len(india_news)
    console.print(f"  Total: [green]{total} articles[/green] ({len(global_news)} global, {len(india_news)} India)")

    return {
        "global_news": global_news,
        "india_news": india_news,
        "festival": festival_info,
        "total_articles": total,
    }
