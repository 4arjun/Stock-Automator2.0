<div align="center">

# NSE Stock Automator

### Production-grade swing-trading scanner for the Indian equity market

Screens **NSE stocks** daily using price action, momentum, and volume — so you don't have to.

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Data Source](https://img.shields.io/badge/Data-Yahoo%20Finance-720E9E?style=for-the-badge&logo=yahoo&logoColor=white)](https://finance.yahoo.com/)
[![Supabase](https://img.shields.io/badge/Storage-Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](#license)

</div>

---

## What is this?

**NSE Stock Automator** is a rules-based screening engine that scans the entire NSE equity universe every day and flags stocks matching two independently backtested swing-trading setups — a **momentum reclaim** strategy and a **trend-continuation pullback** strategy.

No black-box ML, no guesswork — every signal is the output of explicit, auditable technical rules across trend, momentum, volume, and liquidity.

```
     Yahoo Finance Data  ──▶  Indicator Engine  ──▶  Strategy Rules  ──▶  Signals
                                                                          │
                                                              ┌───────────┴───────────┐
                                                              ▼                       ▼
                                                          CSV Export             Supabase DB
```

---

## Features

| | |
|---|---|
| 🎯 **Two live strategies** | RSI Dip-Reclaim and EMA21 Bounce, each with tightly defined entry rules |
| ⚡ **Full-market scans** | Screen every NSE EQ symbol in one run, or target a custom watchlist |
| 🧮 **Multi-factor filtering** | Trend (EMA/DMA stack), momentum (RSI), volume (relative volume), and liquidity (avg traded value) all checked together |
| 💾 **Flexible output** | Print to console, export to CSV, or persist straight to a Supabase table |
| 🔌 **CLI-first design** | Simple flags for symbols, strategy selection, and output — easy to slot into a cron job or CI pipeline |

---

## Installation

```bash
git clone https://github.com/4arjun/Stock-Automator2.0.git
cd Stock-Automator2.0
python3 -m pip install -r requirements.txt
```

Already have a virtual environment set up?

```bash
.venv/bin/python main.py --help
```

---

## ▶️ Usage

**Scan the entire NSE with every active strategy:**
```bash
.venv/bin/python main.py
```

**Run the optimized two-strategy bundle:**
```bash
.venv/bin/python main.py --strategy optimized
```

**Scan a specific watchlist:**
```bash
.venv/bin/python main.py --symbols RELIANCE TCS INFY --strategy optimized
```

**Export results to CSV:**
```bash
.venv/bin/python main.py --strategy optimized --output optimized_signals.csv
```

**Run a single strategy:**
```bash
.venv/bin/python main.py --strategy rsi-dip-reclaim-expanded-80
.venv/bin/python main.py --strategy ema21-bounce-expanded
```

| Strategy key | Description |
|---|---|
| `rsi-dip-reclaim-expanded-80` | Momentum reclaim off a mid-trend dip |
| `ema21-bounce-expanded` | Trend-continuation bounce off the 21 EMA |
| `optimized` | Curated bundle of the above two |
| `all` | Every active strategy |

---

## Strategy Logic

### 1️⃣ RSI Dip-Reclaim (Expanded 80)

A non-candlestick pullback play: catches a stock in a healthy uptrend whose RSI dipped under 50 and is now reclaiming strength as price reclaims the 21 EMA.

<details>
<summary><strong>View full rule set</strong></summary>

- 3-month return must be positive
- RSI(14) dipped below `50` within the last 10 trading days
- Latest RSI(14) reclaims above `55`, and sits between `55–65`
- Previous close below the 21 EMA → current close reclaims above it
- Close above 50 DMA, and 50 DMA above 200 DMA
- Relative volume between `1.0×–2.0×`
- Within `5–12%` of the 52-week high
- Within `3–6%` of the 21 EMA
- Avg. traded value ≥ ₹5 crore · Price ≥ ₹50

</details>

### 2️⃣ EMA21 Bounce (Expanded)

A trend-continuation setup: a stock above its key moving averages pulls back to the 21 EMA and closes strongly near the top of its daily range.

<details>
<summary><strong>View full rule set</strong></summary>

- Close above 21 EMA · 21 EMA above 50 DMA · 50 DMA above 200 DMA
- Latest low touches or comes within `1%` of the 21 EMA
- Close above open, on volume greater than the previous day
- Preceded by a 3–8 trading-day pullback
- Close lands in the top `35%` of the daily candle range
- RSI(14) between `58–68`
- Relative volume between `0.8×–2.0×`
- Within `3–12%` of the 52-week high
- Within `2–6%` of the 21 EMA
- Avg. traded value ≥ ₹5 crore · Price ≥ ₹50

</details>

---

## Supabase Integration

Persist every scan's signals straight to a Supabase table:

```bash
.venv/bin/python main.py --strategy optimized --save-db
```

Set these environment variables first:

```bash
export SUPABASE_URL="your-project-url"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
```

> `SUPABASE_ANON_KEY` also works if your table's row-level security policies allow inserts.

---

## Roadmap

- [ ] Backtesting module for historical signal performance
- [ ] Telegram / Discord alert integration
- [ ] Additional strategy presets
- [ ] Dockerized deployment for scheduled scans

---

## ⚠️ Disclaimer

This tool is built for **educational and research purposes only**. Nothing here constitutes financial advice. Trade at your own risk, and always do your own due diligence.

---

<div align="center">

Built with ☕ and pandas by [**Arjun**](https://github.com/4arjun)

⭐ Star this repo if it helped you spot your next trade!

</div>