# MCX Gold Predictor

An AI-powered evening prediction system for MCX Gold prices (Indian market, INR/10g).
Each evening after market close, it fetches live price data, macro signals, and Indian news,
then uses the Claude API to generate a structured directional signal with a predicted price range
for the next trading day's open. All predictions are stored in SQLite for accuracy tracking.

A Streamlit dashboard lets you review prediction history, direction accuracy, range accuracy,
and confidence calibration — answering the question: "Does Claude's confidence actually match its win rate?"

## Setup

```bash
# 1. Clone or copy the project folder
cd gold-predictor

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
copy .env.example .env      # Windows
# cp .env.example .env      # Mac/Linux

# Edit .env and fill in your API keys (see Free API Keys section below)
```

## Running the Evening Prediction

```bash
python run_evening.py
```

Run this each evening after 10:00 PM IST (after MCX close and RBI releases).
The script will:
1. Fetch MCX/COMEX prices, USD/INR, Nifty from Yahoo Finance
2. Fetch macro data (Fed rate, CPI, Treasury yields) from FRED
3. Fetch gold/commodity news from NewsAPI and Indian RSS feeds
4. Compute technical indicators (RSI, MACD, Bollinger Bands, EMA)
5. Call Claude API for analysis and prediction
6. Save a `.txt` report to the `reports/` folder
7. Store the prediction in `gold_predictions.db`
8. Optionally send a Telegram message (if configured)

## Updating Actuals (Next Morning)

The next morning, look up MCX Gold's actual opening price and record it:

```bash
python run_evening.py --update-actual
```

Enter the date and actual opening price when prompted. The system will compute:
- Whether the direction prediction (UP/DOWN) was correct
- Whether the actual open fell inside the predicted range

## Running the Dashboard

```bash
streamlit run dashboard/app.py
```

Open `http://localhost:8501` in your browser. The dashboard shows:
- Direction accuracy %, range accuracy %, avg confidence
- Predicted range vs actual price chart
- Signal history table
- Confidence calibration chart (is Claude well-calibrated?)
- Latest report viewer

## Free API Keys

| Service | URL | Free Tier |
|---------|-----|-----------|
| Anthropic Claude | https://console.anthropic.com | Pay-per-token |
| NewsAPI | https://newsapi.org/register | 100 req/day |
| FRED (St. Louis Fed) | https://fred.stlouisfed.org/docs/api/api_key.html | Unlimited, free |
| Telegram Bot | https://t.me/BotFather | Free |

## MCX Gold Formula

```
MCX (INR/10g) ≈ COMEX (USD/oz) × USD/INR × 0.3215
```

The 0.3215 factor converts troy ounces to 10 grams.
Add ~6% import duty + 3% GST for the full duty-inclusive price.
Even when COMEX is flat, MCX can move if the Rupee moves — the system tracks both.

## Project Structure

```
gold-predictor/
├── config.py              API keys, constants, ticker symbols
├── requirements.txt
├── run_evening.py         Master script — run this each evening
├── data/
│   ├── fetch_price.py     MCX, COMEX, USD/INR, Nifty50, Silver
│   ├── fetch_macro.py     FRED: Fed rate, CPI, Treasury yields
│   └── fetch_news.py      NewsAPI + Indian RSS feeds + festival calendar
├── features/
│   └── build_features.py  RSI, MACD, Bollinger, EMA, momentum
├── analysis/
│   └── claude_signal.py   Claude API call + response parsing
├── report/
│   └── generate_report.py Report assembly, file save, Telegram send
├── db/
│   └── database.py        SQLite: predictions + accuracy tracking
├── dashboard/
│   └── app.py             Streamlit dashboard
├── reports/               One .txt report per day (auto-created)
└── gold_predictions.db    SQLite database (auto-created)
```
