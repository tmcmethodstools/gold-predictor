import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MCX_TICKER = "GOLDBEES.NS"
COMEX_TICKER = "GC=F"
USDINR_TICKER = "INR=X"
NIFTY_TICKER = "^NSEI"
SILVER_TICKER = "SI=F"
DXY_TICKER = "DX-Y.NYB"
BRENT_TICKER = "BZ=F"
WTI_TICKER = "CL=F"

LOOKBACK_DAYS = 60
REPORT_DIR = "reports"
DB_PATH = "gold_predictions.db"
CLAUDE_MODEL = "claude-sonnet-4-6"

# MCX formula constants
TROY_OZ_TO_10G = 0.3215
IMPORT_DUTY_PCT = 0.06
GST_PCT = 0.03

# Indian gold-buying festivals (approximate dates for 2025-2026)
FESTIVAL_DATES = {
    "Dhanteras 2025": "2025-10-20",
    "Diwali 2025": "2025-10-21",
    "Akshaya Tritiya 2026": "2026-04-29",
    "Gudi Padwa 2026": "2026-03-19",
    "Dhanteras 2026": "2026-11-07",
    "Diwali 2026": "2026-11-08",
}
FESTIVAL_WINDOW_DAYS = 14
