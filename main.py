#!/usr/bin/env python3
"""
NSE 21 EMA pullback stock screener.

Install dependencies:
    python3 -m pip install -r requirements.txt

Run:
    python3 main.py
    python3 main.py --limit 50 --output nse_21ema_pullbacks.csv
    python3 main.py --symbols RELIANCE TCS INFY
    python3 main.py --symbols RELIANCE TCS INFY --strategy 1.0
    python3 main.py --symbols RELIANCE TCS INFY --strategy 2.0
    python3 main.py --symbols RELIANCE TCS INFY --strategy be-volume-rsi-65-68
    python3 main.py --symbols RELIANCE TCS INFY --save-db --update-trigger-prices
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
from typing import Iterable

try:
    import numpy as np
    import pandas as pd
    import requests
    import yfinance as yf
    from dotenv import load_dotenv
    from tabulate import tabulate
except ImportError as exc:
    missing = exc.name or "a required package"
    print(
        f"Missing dependency: {missing}\n"
        "Install dependencies with:\n"
        "  python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)


load_dotenv()

NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
MIN_PRICE = 50.0
MIN_AVG_TRADED_VALUE = 5 * 10_000_000  # Rs 5 crore
STRATEGY_V1 = "NSE_21_EMA_PULLBACK"
STRATEGY_V2 = "NSE_21_EMA_PULLBACK_2_0"
STRATEGY_BE_VOLUME_RSI_65_68 = "BE_VOLUME_REVERSAL_RSI_65_68"
STRATEGY_BE_VOLUME_HIGH_CONFIDENCE = "BE_VOLUME_REVERSAL_HIGH_CONFIDENCE"
STRATEGY_RANGE_BREAKOUT_RSI_65_68 = "RANGE_BREAKOUT_VOLUME_RSI_65_68"
STRATEGY_MOMENTUM_TIGHT_EMA = "MOMENTUM_PULLBACK_TIGHT_EMA"
STRATEGY_BE_VOLUME_HC_MID_52W = "BE_VOLUME_HC_MID_52W"
STRATEGY_BE_VOLUME_HC_BALANCED = "BE_VOLUME_HC_BALANCED"
STRATEGY_BE_VOLUME_HC_EARLY_SURGE = "BE_VOLUME_HC_EARLY_SURGE"
STRATEGY_BE_VOLUME_HC_COOL_RVOL = "BE_VOLUME_HC_COOL_RVOL"
STRATEGY_RSI_DIP_RECLAIM_OPTIMAL = "RSI_DIP_RECLAIM_OPTIMAL"
STRATEGY_RSI_DIP_RECLAIM_PRECISION = "RSI_DIP_RECLAIM_PRECISION"
STRATEGY_RSI_DIP_RECLAIM_EXPANDED_80 = "RSI_DIP_RECLAIM_EXPANDED_80"
STRATEGY_EMA21_BOUNCE_EXPANDED = "EMA21_BOUNCE_EXPANDED"
STRATEGY_NAMES = {
    "1.0": STRATEGY_V1,
    "2.0": STRATEGY_V2,
    "be-volume-rsi-65-68": STRATEGY_BE_VOLUME_RSI_65_68,
    "be-volume-high-confidence": STRATEGY_BE_VOLUME_HIGH_CONFIDENCE,
    "range-breakout-rsi-65-68": STRATEGY_RANGE_BREAKOUT_RSI_65_68,
    "momentum-tight-ema": STRATEGY_MOMENTUM_TIGHT_EMA,
    "be-volume-hc-mid-52w": STRATEGY_BE_VOLUME_HC_MID_52W,
    "be-volume-hc-balanced": STRATEGY_BE_VOLUME_HC_BALANCED,
    "be-volume-hc-early-surge": STRATEGY_BE_VOLUME_HC_EARLY_SURGE,
    "be-volume-hc-cool-rvol": STRATEGY_BE_VOLUME_HC_COOL_RVOL,
    "rsi-dip-reclaim-optimal": STRATEGY_RSI_DIP_RECLAIM_OPTIMAL,
    "rsi-dip-reclaim-precision": STRATEGY_RSI_DIP_RECLAIM_PRECISION,
    "rsi-dip-reclaim-expanded-80": STRATEGY_RSI_DIP_RECLAIM_EXPANDED_80,
    "ema21-bounce-expanded": STRATEGY_EMA21_BOUNCE_EXPANDED,
}


@dataclass(frozen=True)
class ScreenConfig:
    period: str = "18mo"
    batch_size: int = 80
    sleep_seconds: float = 1.0
    limit: int | None = None
    output: str | None = None
    strategy: str = "all"
    save_db: bool = False
    update_trigger_prices: bool = False


class SupabaseRestClient:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        json: list[dict] | dict | None = None,
        prefer: str | None = None,
    ) -> list[dict] | dict:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer

        response = requests.request(
            method,
            f"{self.url}/rest/v1/{table}",
            headers=headers,
            params=params,
            json=json,
            timeout=60,
        )
        response.raise_for_status()
        if not response.text:
            return []
        return response.json()


def get_supabase_client() -> SupabaseRestClient:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before using --save-db. "
            "SUPABASE_ANON_KEY also works if your table policies allow inserts."
        )
    return SupabaseRestClient(url, key)


def fetch_nse_symbols() -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    response = requests.get(NSE_EQUITY_LIST_URL, headers=headers, timeout=30)
    response.raise_for_status()

    equity_list = pd.read_csv(StringIO(response.text))
    equity_list.columns = equity_list.columns.str.strip()

    # SERIES == EQ filters ordinary equity shares and avoids BE/BZ/SME style series.
    symbols = (
        equity_list.loc[equity_list[" SERIES"].str.strip().eq("EQ"), "SYMBOL"]
        if " SERIES" in equity_list.columns
        else equity_list.loc[equity_list["SERIES"].str.strip().eq("EQ"), "SYMBOL"]
    )
    return sorted(symbol.strip() for symbol in symbols.dropna().unique())


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def yahoo_symbol(nse_symbol: str) -> str:
    return f"{nse_symbol}.NS"


def nse_symbol(yahoo_ticker: str) -> str:
    return yahoo_ticker.removesuffix(".NS")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    relative_strength = avg_gain / avg_loss.replace(0, np.nan)
    indicator = 100 - (100 / (1 + relative_strength))
    return indicator.fillna(100).where(avg_loss.ne(0), 100)


def flatten_downloaded_data(data: pd.DataFrame, requested_tickers: list[str]) -> dict[str, pd.DataFrame]:
    if data.empty:
        return {}

    if isinstance(data.columns, pd.MultiIndex):
        ticker_level = 0 if data.columns.names[0] == "Ticker" else 1
        return {
            ticker: data.xs(ticker, axis=1, level=ticker_level).dropna(how="all")
            for ticker in requested_tickers
            if ticker in data.columns.get_level_values(ticker_level)
        }

    return {requested_tickers[0]: data.dropna(how="all")}


def latest_completed_row(history: pd.DataFrame) -> pd.Series | None:
    required_columns = {"Open", "High", "Low", "Close", "Volume"}
    if history.empty or not required_columns.issubset(history.columns):
        return None

    cleaned = history.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
    cleaned = cleaned[cleaned["Volume"] > 0]
    if len(cleaned) < 252:
        return None

    return cleaned.iloc[-1]


def iso_date_from_index(index_value: object) -> str:
    return pd.Timestamp(index_value).date().isoformat()


def candle_body(row: pd.Series) -> float:
    return abs(float(row["Close"]) - float(row["Open"]))


def candle_range(row: pd.Series) -> float:
    return max(float(row["High"]) - float(row["Low"]), 0.0)


def closes_in_top_pct(row: pd.Series, pct: float) -> bool:
    daily_range = candle_range(row)
    if daily_range <= 0:
        return False
    close_location = (float(row["Close"]) - float(row["Low"])) / daily_range
    return close_location >= 1 - pct


def candle_near_ema21(row: pd.Series, ema21: float, tolerance_pct: float = 1.0) -> bool:
    low = float(row["Low"])
    high = float(row["High"])
    lower_bound = ema21 * (1 - tolerance_pct / 100)
    upper_bound = ema21 * (1 + tolerance_pct / 100)
    return low <= upper_bound and high >= lower_bound


def pullback_or_sideways_consolidation(history: pd.DataFrame) -> bool:
    previous = history.iloc[-6:-1].copy()
    if len(previous) < 3:
        return False

    for window_size in (3, 4, 5):
        window = previous.tail(window_size)
        closes = window["Close"]
        ema21 = window["EMA21"]
        avg_close = float(closes.mean())
        close_change_pct = (float(closes.iloc[-1]) - float(closes.iloc[0])) / avg_close * 100
        range_pct = (float(closes.max()) - float(closes.min())) / avg_close * 100

        is_pullback = close_change_pct <= -0.75 and float(closes.iloc[-1]) <= float(ema21.iloc[-1]) * 1.03
        is_sideways = range_pct <= 4 and abs(float(closes.iloc[-1]) - float(ema21.iloc[-1])) / float(ema21.iloc[-1]) * 100 <= 3
        if is_pullback or is_sideways:
            return True

    return False


def pullback_volume_below_average(history: pd.DataFrame, avg_volume20: float) -> bool:
    previous = history.iloc[-6:-1].copy()
    if len(previous) < 3 or avg_volume20 <= 0:
        return False

    for window_size in (3, 4, 5):
        window = previous.tail(window_size)
        if float(window["Volume"].mean()) < avg_volume20:
            return True

    return False


def low_near_level(low_price: float, level: float, tolerance_pct: float) -> bool:
    return low_price <= level * (1 + tolerance_pct / 100)


def has_recent_pullback(history: pd.DataFrame, min_days: int = 3, max_days: int = 8) -> bool:
    if len(history) < max_days + 2:
        return False

    previous = history.iloc[:-1]
    for window_size in range(min_days, max_days + 1):
        window = previous.tail(window_size)
        if len(window) < window_size:
            continue
        first_close = float(window["Close"].iloc[0])
        last_close = float(window["Close"].iloc[-1])
        if first_close <= 0:
            continue
        decline_pct = (first_close - last_close) / first_close * 100
        if 1 <= decline_pct <= 12:
            return True
    return False


def three_month_return_positive(history: pd.DataFrame) -> bool:
    if len(history) < 64:
        return False
    past_close = float(history.iloc[-64]["Close"])
    latest_close = float(history.iloc[-1]["Close"])
    return past_close > 0 and latest_close > past_close


def recent_rsi_dip_and_reclaim(history: pd.DataFrame, lookback: int, dip_below: float, reclaim_above: float) -> bool:
    if len(history) < lookback + 1:
        return False
    previous_rsi = history["RSI14"].iloc[-lookback - 1 : -1]
    latest_rsi = float(history.iloc[-1]["RSI14"])
    return float(previous_rsi.min()) < dip_below and latest_rsi > reclaim_above


def bullish_engulfing(previous: pd.Series, latest: pd.Series) -> bool:
    previous_bearish = float(previous["Close"]) < float(previous["Open"])
    latest_bullish = float(latest["Close"]) > float(latest["Open"])
    engulfs_body = float(latest["Open"]) <= float(previous["Close"]) and float(latest["Close"]) >= float(previous["Open"])
    return previous_bearish and latest_bullish and engulfs_body


def hammer_near_ema21(latest: pd.Series, ema21: float) -> bool:
    daily_range = candle_range(latest)
    body = candle_body(latest)
    if daily_range <= 0 or body <= 0:
        return False

    lower_wick = min(float(latest["Open"]), float(latest["Close"])) - float(latest["Low"])
    upper_wick = float(latest["High"]) - max(float(latest["Open"]), float(latest["Close"]))
    return (
        candle_near_ema21(latest, ema21, tolerance_pct=1.0)
        and lower_wick >= body * 2
        and upper_wick <= body * 1.25
        and body / daily_range <= 0.4
    )


def morning_star(history: pd.DataFrame) -> bool:
    if len(history) < 3:
        return False

    first = history.iloc[-3]
    second = history.iloc[-2]
    third = history.iloc[-1]
    first_body = candle_body(first)
    second_body = candle_body(second)
    midpoint = (float(first["Open"]) + float(first["Close"])) / 2

    return (
        float(first["Close"]) < float(first["Open"])
        and first_body > 0
        and second_body <= first_body * 0.5
        and float(third["Close"]) > float(third["Open"])
        and float(third["Close"]) >= midpoint
    )


def bullish_patterns(history: pd.DataFrame, latest: pd.Series, ema21: float, avg_volume20: float) -> tuple[str, int]:
    patterns: list[str] = []
    score = 0
    previous = history.iloc[-2]

    if bullish_engulfing(previous, latest):
        patterns.append("Bullish Engulfing")
        score += 1
    if hammer_near_ema21(latest, ema21):
        patterns.append("Hammer near 21 EMA")
        score += 1
    if morning_star(history):
        patterns.append("Morning Star")
        score += 1
    if float(latest["Volume"]) > avg_volume20 * 1.5:
        patterns.append("Bounce volume > 1.5x AvgVol20")
        score += 1

    return ", ".join(patterns) if patterns else "None", score


def prepare_history(history: pd.DataFrame) -> pd.DataFrame | None:
    if history.empty:
        return None

    history = history.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
    history = history[history["Volume"] > 0]
    if len(history) < 252:
        return None

    close = history["Close"]
    volume = history["Volume"]

    history["EMA21"] = close.ewm(span=21, adjust=False).mean()
    history["EMA50"] = close.ewm(span=50, adjust=False).mean()
    history["DMA50"] = close.rolling(50).mean()
    history["DMA200"] = close.rolling(200).mean()
    history["RSI14"] = rsi(close, 14)
    history["AvgVol20"] = volume.rolling(20).mean()
    history["High52W"] = history["High"].rolling(252).max()
    return history


def base_screen_values(symbol: str, history: pd.DataFrame, strategy_name: str) -> dict[str, float | str] | None:
    latest = latest_completed_row(history)
    if latest is None:
        return None

    close_price = float(latest["Close"])
    ema21 = float(latest["EMA21"])
    dma50 = float(latest["DMA50"])
    dma200 = float(latest["DMA200"])
    rsi14 = float(latest["RSI14"])
    latest_volume = float(latest["Volume"])
    avg_volume20 = float(latest["AvgVol20"])
    high_52w = float(latest["High52W"])

    values = [close_price, ema21, dma50, dma200, rsi14, latest_volume, avg_volume20, high_52w]
    if any(math.isnan(value) or value <= 0 for value in values):
        return None

    return {
        "Strategy Name": strategy_name,
        "Symbol": symbol,
        "Triggered Date": iso_date_from_index(latest.name),
        "Recommendation": "BUY",
        "Close Price": close_price,
        "21 EMA": ema21,
        "50 DMA": dma50,
        "200 DMA": dma200,
        "RSI(14)": rsi14,
        "Today's Volume": latest_volume,
        "Average Volume(20)": avg_volume20,
        "Relative Volume (RVOL)": latest_volume / avg_volume20,
        "Distance from 52-week High (%)": (high_52w - close_price) / high_52w * 100,
        "Distance from 21 EMA (%)": abs(close_price - ema21) / ema21 * 100,
        "Bullish Pattern Detected": "None",
        "Signal Score": 0,
        "Avg Traded Value": close_price * avg_volume20,
    }


def screen_history_v1(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    latest = latest_completed_row(history)
    result = base_screen_values(symbol, history, STRATEGY_V1)
    if latest is None or result is None:
        return None

    ema50 = float(latest["EMA50"])
    values = [ema50]
    if any(math.isnan(value) or value <= 0 for value in values):
        return None

    passes = [
        float(result["Close Price"]) > float(result["200 DMA"]),
        float(result["21 EMA"]) > ema50,
        float(result["Distance from 21 EMA (%)"]) <= 2,
        float(result["Today's Volume"]) < float(result["Average Volume(20)"]),
        float(latest["Close"]) > float(latest["Open"]),
        float(result["RSI(14)"]) > 55,
        float(result["Distance from 52-week High (%)"]) <= 15,
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    return result


def screen_history_v2(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = base_screen_values(symbol, history, STRATEGY_V2)
    if result is None:
        return None

    latest = latest_completed_row(history)
    if latest is None:
        return None

    close_price = float(latest["Close"])
    open_price = float(latest["Open"])
    low_price = float(latest["Low"])
    high_price = float(latest["High"])
    ema21 = float(latest["EMA21"])
    latest_volume = float(latest["Volume"])
    previous_volume = float(history.iloc[-2]["Volume"])
    avg_volume20 = float(result["Average Volume(20)"])

    values = [close_price, open_price, low_price, high_price, ema21, latest_volume, previous_volume, avg_volume20]
    if any(math.isnan(value) or value <= 0 for value in values):
        return None

    pattern_detected, signal_score = bullish_patterns(history, latest, ema21, avg_volume20)

    passes = [
        float(result["Close Price"]) > float(result["200 DMA"]),
        float(result["21 EMA"]) > float(result["50 DMA"]),
        float(result["Distance from 21 EMA (%)"]) <= 2,
        pullback_volume_below_average(history, avg_volume20),
        float(result["RSI(14)"]) > 55,
        float(result["Distance from 52-week High (%)"]) <= 15,
        close_price > open_price,
        closes_in_top_pct(latest, 0.30),
        latest_volume > previous_volume,
        candle_near_ema21(latest, ema21, tolerance_pct=1.0),
        pullback_or_sideways_consolidation(history),
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    result["Bullish Pattern Detected"] = pattern_detected
    result["Signal Score"] = signal_score
    return result


def screen_be_volume_reversal(symbol: str, history: pd.DataFrame, strategy_name: str) -> dict[str, float | str] | None:
    result = base_screen_values(symbol, history, strategy_name)
    if result is None:
        return None

    latest = latest_completed_row(history)
    if latest is None or len(history) < 2:
        return None

    previous = history.iloc[-2]
    close_price = float(latest["Close"])
    previous_high = float(previous["High"])
    previous_volume = float(previous["Volume"])
    latest_volume = float(result["Today's Volume"])
    avg_volume20 = float(result["Average Volume(20)"])

    values = [close_price, previous_high, previous_volume, latest_volume, avg_volume20]
    if any(math.isnan(value) or value <= 0 for value in values):
        return None

    passes = [
        bullish_engulfing(previous, latest),
        latest_volume >= avg_volume20 * 1.2,
        float(previous["Close"]) < float(previous["Open"]),
        close_price > previous_high,
        close_price > float(result["200 DMA"]),
        float(result["RSI(14)"]) > 50,
        float(result["Distance from 21 EMA (%)"]) <= 8,
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    result["Bullish Pattern Detected"] = "Bullish Engulfing"
    result["Signal Score"] = 1
    return result


def screen_be_volume_rsi_65_68(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_be_volume_reversal(symbol, history, STRATEGY_BE_VOLUME_RSI_65_68)
    if result is None:
        return None

    passes = [
        65 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) >= 1.2,
        float(result["Distance from 52-week High (%)"]) <= 10,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    return result if all(passes) else None


def screen_be_volume_high_confidence(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_be_volume_reversal(symbol, history, STRATEGY_BE_VOLUME_HIGH_CONFIDENCE)
    if result is None:
        return None

    passes = [
        62 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) >= 1.5,
        float(result["Distance from 52-week High (%)"]) <= 5,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    return result if all(passes) else None


def screen_range_breakout_rsi_65_68(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = base_screen_values(symbol, history, STRATEGY_RANGE_BREAKOUT_RSI_65_68)
    if result is None or len(history) < 22:
        return None

    latest = latest_completed_row(history)
    if latest is None:
        return None

    previous_20_day_high = float(history.iloc[-21:-1]["High"].max())
    close_price = float(result["Close Price"])
    latest_volume = float(result["Today's Volume"])
    avg_volume20 = float(result["Average Volume(20)"])
    values = [previous_20_day_high, close_price, latest_volume, avg_volume20]
    if any(math.isnan(value) or value <= 0 for value in values):
        return None

    passes = [
        close_price > previous_20_day_high,
        latest_volume >= avg_volume20 * 1.5,
        close_price > float(result["21 EMA"]) > float(result["50 DMA"]) > float(result["200 DMA"]),
        65 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) >= 2.0,
        float(result["Distance from 52-week High (%)"]) <= 8,
        float(result["Distance from 21 EMA (%)"]) <= 8,
        closes_in_top_pct(latest, 0.25),
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    result["Bullish Pattern Detected"] = "20D High Breakout"
    result["Signal Score"] = 0
    return result


def screen_momentum_tight_ema(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = base_screen_values(symbol, history, STRATEGY_MOMENTUM_TIGHT_EMA)
    if result is None or len(history) < 64:
        return None

    latest = latest_completed_row(history)
    if latest is None:
        return None

    previous = history.iloc[-2]
    passes = [
        three_month_return_positive(history),
        has_recent_pullback(history),
        float(previous["Close"]) < float(previous["EMA21"]),
        float(latest["Close"]) > float(latest["EMA21"]),
        float(latest["Close"]) > float(latest["Open"]),
        float(latest["Volume"]) > float(previous["Volume"]),
        55 <= float(result["RSI(14)"]) <= 70,
        float(result["Relative Volume (RVOL)"]) >= 0.8,
        float(result["Distance from 52-week High (%)"]) <= 10,
        float(result["Distance from 21 EMA (%)"]) <= 1.5,
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    result["Bullish Pattern Detected"] = "21 EMA Reclaim"
    result["Signal Score"] = 0
    return result


def screen_be_volume_hc_mid_52w(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_be_volume_high_confidence(symbol, history)
    if result is None:
        return None

    passes = [
        58 <= float(result["RSI(14)"]) <= 66,
        float(result["Relative Volume (RVOL)"]) <= 2.5,
        2 <= float(result["Distance from 52-week High (%)"]) <= 8,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    if not all(passes):
        return None

    result["Strategy Name"] = STRATEGY_BE_VOLUME_HC_MID_52W
    return result


def screen_be_volume_hc_balanced(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_be_volume_high_confidence(symbol, history)
    if result is None:
        return None

    passes = [
        60 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) <= 2.5,
        2 <= float(result["Distance from 52-week High (%)"]) <= 8,
        1 <= float(result["Distance from 21 EMA (%)"]) <= 6,
    ]
    if not all(passes):
        return None

    result["Strategy Name"] = STRATEGY_BE_VOLUME_HC_BALANCED
    return result


def screen_be_volume_hc_early_surge(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_be_volume_high_confidence(symbol, history)
    if result is None:
        return None

    passes = [
        58 <= float(result["RSI(14)"]) <= 66,
        float(result["Relative Volume (RVOL)"]) <= 2.5,
        float(result["Distance from 52-week High (%)"]) <= 5,
        1 <= float(result["Distance from 21 EMA (%)"]) <= 6,
    ]
    if not all(passes):
        return None

    result["Strategy Name"] = STRATEGY_BE_VOLUME_HC_EARLY_SURGE
    return result


def screen_be_volume_hc_cool_rvol(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_be_volume_high_confidence(symbol, history)
    if result is None:
        return None

    passes = [
        58 <= float(result["RSI(14)"]) <= 66,
        float(result["Relative Volume (RVOL)"]) <= 2.5,
        float(result["Distance from 52-week High (%)"]) <= 5,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    if not all(passes):
        return None

    result["Strategy Name"] = STRATEGY_BE_VOLUME_HC_COOL_RVOL
    return result


def screen_rsi_dip_reclaim_base(symbol: str, history: pd.DataFrame, strategy_name: str) -> dict[str, float | str] | None:
    result = base_screen_values(symbol, history, strategy_name)
    if result is None or len(history) < 64:
        return None

    latest = latest_completed_row(history)
    if latest is None:
        return None

    previous = history.iloc[-2]
    passes = [
        three_month_return_positive(history),
        recent_rsi_dip_and_reclaim(history, lookback=10, dip_below=50, reclaim_above=55),
        float(previous["Close"]) < float(previous["EMA21"]),
        float(latest["Close"]) > float(latest["EMA21"]),
        float(result["Close Price"]) > float(result["50 DMA"]) > float(result["200 DMA"]),
        float(result["Relative Volume (RVOL)"]) >= 1.0,
        float(result["Distance from 52-week High (%)"]) <= 15,
        float(result["Distance from 21 EMA (%)"]) <= 6,
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    result["Bullish Pattern Detected"] = "RSI Dip Reclaim"
    result["Signal Score"] = 0
    return result


def screen_rsi_dip_reclaim_optimal(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_rsi_dip_reclaim_base(symbol, history, STRATEGY_RSI_DIP_RECLAIM_OPTIMAL)
    if result is None:
        return None

    passes = [
        58 <= float(result["RSI(14)"]) <= 68,
        1.2 <= float(result["Relative Volume (RVOL)"]) <= 3.0,
        2 <= float(result["Distance from 52-week High (%)"]) <= 10,
        float(result["Distance from 21 EMA (%)"]) <= 3,
    ]
    return result if all(passes) else None


def screen_rsi_dip_reclaim_precision(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_rsi_dip_reclaim_base(symbol, history, STRATEGY_RSI_DIP_RECLAIM_PRECISION)
    if result is None:
        return None

    passes = [
        58 <= float(result["RSI(14)"]) <= 65,
        float(result["Relative Volume (RVOL)"]) <= 2.0,
        3 <= float(result["Distance from 52-week High (%)"]) <= 10,
        float(result["Distance from 21 EMA (%)"]) <= 3,
    ]
    return result if all(passes) else None


def screen_rsi_dip_reclaim_expanded_80(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = screen_rsi_dip_reclaim_base(symbol, history, STRATEGY_RSI_DIP_RECLAIM_EXPANDED_80)
    if result is None:
        return None

    passes = [
        55 <= float(result["RSI(14)"]) <= 65,
        float(result["Relative Volume (RVOL)"]) <= 2.0,
        5 <= float(result["Distance from 52-week High (%)"]) <= 12,
        3 <= float(result["Distance from 21 EMA (%)"]) <= 6,
    ]
    return result if all(passes) else None


def screen_ema21_bounce_expanded(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = base_screen_values(symbol, history, STRATEGY_EMA21_BOUNCE_EXPANDED)
    if result is None or len(history) < 64:
        return None

    latest = latest_completed_row(history)
    if latest is None:
        return None

    previous = history.iloc[-2]
    passes = [
        float(result["Close Price"]) > float(result["21 EMA"]) > float(result["50 DMA"]) > float(result["200 DMA"]),
        float(latest["Low"]) <= float(result["21 EMA"]) * 1.01,
        float(latest["Close"]) > float(latest["Open"]),
        float(latest["Volume"]) > float(previous["Volume"]),
        has_recent_pullback(history, min_days=3, max_days=8),
        closes_in_top_pct(latest, 0.35),
        58 <= float(result["RSI(14)"]) <= 68,
        0.8 <= float(result["Relative Volume (RVOL)"]) <= 2.0,
        3 <= float(result["Distance from 52-week High (%)"]) <= 12,
        2 <= float(result["Distance from 21 EMA (%)"]) <= 6,
        float(result["Avg Traded Value"]) >= MIN_AVG_TRADED_VALUE,
        float(result["Close Price"]) >= MIN_PRICE,
    ]
    if not all(passes):
        return None

    result["Bullish Pattern Detected"] = "21 EMA Bounce"
    result["Signal Score"] = 0
    return result


SCREENERS = {
    "1.0": screen_history_v1,
    "2.0": screen_history_v2,
    "be-volume-rsi-65-68": screen_be_volume_rsi_65_68,
    "be-volume-high-confidence": screen_be_volume_high_confidence,
    "range-breakout-rsi-65-68": screen_range_breakout_rsi_65_68,
    "momentum-tight-ema": screen_momentum_tight_ema,
    "be-volume-hc-mid-52w": screen_be_volume_hc_mid_52w,
    "be-volume-hc-balanced": screen_be_volume_hc_balanced,
    "be-volume-hc-early-surge": screen_be_volume_hc_early_surge,
    "be-volume-hc-cool-rvol": screen_be_volume_hc_cool_rvol,
    "rsi-dip-reclaim-optimal": screen_rsi_dip_reclaim_optimal,
    "rsi-dip-reclaim-precision": screen_rsi_dip_reclaim_precision,
    "rsi-dip-reclaim-expanded-80": screen_rsi_dip_reclaim_expanded_80,
    "ema21-bounce-expanded": screen_ema21_bounce_expanded,
}


def selected_strategy_versions(strategy: str) -> list[str]:
    if strategy == "all":
        return list(SCREENERS)
    if strategy == "optimized":
        return [
            "be-volume-high-confidence",
            "be-volume-hc-mid-52w",
            "be-volume-hc-balanced",
            "be-volume-hc-early-surge",
            "be-volume-hc-cool-rvol",
            "rsi-dip-reclaim-optimal",
            "rsi-dip-reclaim-precision",
            "rsi-dip-reclaim-expanded-80",
            "ema21-bounce-expanded",
        ]
    return [strategy]


def screen_history(symbol: str, history: pd.DataFrame, strategy: str) -> list[dict[str, float | str]]:
    prepared_history = prepare_history(history)
    if prepared_history is None:
        return []

    results: list[dict[str, float | str]] = []
    for strategy_version in selected_strategy_versions(strategy):
        result = SCREENERS[strategy_version](symbol, prepared_history)
        if result:
            results.append(result)
    return results


def download_histories(symbols: list[str], config: ScreenConfig) -> list[dict[str, float | str]]:
    matches: list[dict[str, float | str]] = []
    total_batches = math.ceil(len(symbols) / config.batch_size)

    for index, symbol_batch in enumerate(chunks(symbols, config.batch_size), start=1):
        tickers = [yahoo_symbol(symbol) for symbol in symbol_batch]
        print(f"Downloading batch {index}/{total_batches} ({len(tickers)} stocks)...", file=sys.stderr)

        try:
            data = yf.download(
                tickers=tickers,
                period=config.period,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            print(f"Skipping batch {index}: {exc}", file=sys.stderr)
            continue

        for ticker, history in flatten_downloaded_data(data, tickers).items():
            matches.extend(screen_history(nse_symbol(ticker), history, config.strategy))

        if index < total_batches and config.sleep_seconds:
            time.sleep(config.sleep_seconds)

    return matches


def supabase_trigger_payload(frame: pd.DataFrame) -> list[dict]:
    payload: list[dict] = []
    for row in frame.to_dict("records"):
        payload.append(
            {
                "strategy_name": row["Strategy Name"],
                "symbol": row["Symbol"],
                "triggered_date": row["Triggered Date"],
                "recommendation": row["Recommendation"],
                "close_price": round(float(row["Close Price"]), 4),
                "ema21": round(float(row["21 EMA"]), 4),
                "dma50": round(float(row["50 DMA"]), 4),
                "dma200": round(float(row["200 DMA"]), 4),
                "rsi14": round(float(row["RSI(14)"]), 4),
                "volume": int(row["Today's Volume"]),
                "avg_volume20": round(float(row["Average Volume(20)"]), 4),
                "distance_from_52w_high_pct": round(float(row["Distance from 52-week High (%)"]), 4),
                "distance_from_21ema_pct": round(float(row["Distance from 21 EMA (%)"]), 4),
                "relative_volume": round(float(row["Relative Volume (RVOL)"]), 6),
                "bullish_pattern_detected": row["Bullish Pattern Detected"],
                "signal_score": int(row["Signal Score"]),
                "avg_traded_value": round(float(row["Avg Traded Value"]), 2),
            }
        )
    return payload


def save_triggers_to_supabase(frame: pd.DataFrame, client: SupabaseRestClient) -> list[dict]:
    payload = supabase_trigger_payload(frame)
    if not payload:
        return []

    client.request(
        "POST",
        "screener_triggers",
        params={"on_conflict": "strategy_name,symbol,triggered_date"},
        json=payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )

    symbols = sorted({row["symbol"] for row in payload})
    strategy_names = sorted({row["strategy_name"] for row in payload})
    triggered_dates = sorted({row["triggered_date"] for row in payload})
    return client.request(
        "GET",
        "screener_triggers",
        params={
            "select": "id,strategy_name,symbol,triggered_date,recommendation,close_price",
            "strategy_name": f"in.({','.join(strategy_names)})",
            "symbol": f"in.({','.join(symbols)})",
            "triggered_date": f"in.({','.join(triggered_dates)})",
        },
    )


def fetch_triggers_for_price_updates(client: SupabaseRestClient) -> list[dict]:
    return client.request(
        "GET",
        "screener_triggers",
        params={
            "select": "id,symbol,triggered_date",
            "strategy_name": f"in.({','.join(STRATEGY_NAMES.values())})",
            "order": "triggered_date.asc",
        },
    )


def download_close_history(symbols: list[str], start_date: str) -> dict[str, pd.DataFrame]:
    end_date = (date.today() + timedelta(days=1)).isoformat()
    tickers = [yahoo_symbol(symbol) for symbol in symbols]
    data = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    return {nse_symbol(ticker): history for ticker, history in flatten_downloaded_data(data, tickers).items()}


def price_payload_for_triggers(triggers: list[dict]) -> list[dict]:
    if not triggers:
        return []

    symbols = sorted({trigger["symbol"] for trigger in triggers})
    start_date = min(trigger["triggered_date"] for trigger in triggers)
    histories = download_close_history(symbols, start_date)

    payload: list[dict] = []
    for trigger in triggers:
        history = histories.get(trigger["symbol"])
        if history is None or history.empty:
            continue

        history = history.dropna(subset=["Close"])
        history = history.loc[pd.Timestamp(trigger["triggered_date"]) :]
        for index, row in history.iterrows():
            close_price = row.get("Close")
            if pd.isna(close_price):
                continue
            payload.append(
                {
                    "trigger_id": trigger["id"],
                    "symbol": trigger["symbol"],
                    "price_date": iso_date_from_index(index),
                    "close_price": round(float(close_price), 4),
                }
            )
    return payload


def save_trigger_prices_to_supabase(client: SupabaseRestClient, triggers: list[dict]) -> int:
    payload = price_payload_for_triggers(triggers)
    if not payload:
        return 0

    saved = 0
    for payload_chunk in chunks(payload, 500):
        client.request(
            "POST",
            "trigger_price_history",
            params={"on_conflict": "trigger_id,price_date"},
            json=payload_chunk,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        saved += len(payload_chunk)
    return saved


def sort_results(results: list[dict[str, float | str]]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    frame = pd.DataFrame(results)
    return frame.sort_values(
        by=["Strategy Name", "Distance from 52-week High (%)", "Relative Volume (RVOL)", "RSI(14)", "Distance from 21 EMA (%)"],
        ascending=[True, True, False, False, True],
    ).reset_index(drop=True)


def format_output(frame: pd.DataFrame) -> pd.DataFrame:
    visible_columns = [
        "Strategy Name",
        "Symbol",
        "Triggered Date",
        "Recommendation",
        "Close Price",
        "21 EMA",
        "50 DMA",
        "200 DMA",
        "RSI(14)",
        "Today's Volume",
        "Average Volume(20)",
        "Relative Volume (RVOL)",
        "Distance from 52-week High (%)",
        "Bullish Pattern Detected",
    ]
    output = frame.loc[:, visible_columns].copy()

    for column in [
        "Close Price",
        "21 EMA",
        "50 DMA",
        "200 DMA",
        "RSI(14)",
        "Relative Volume (RVOL)",
        "Distance from 52-week High (%)",
    ]:
        output[column] = output[column].map(lambda value: f"{value:.2f}")

    for column in ["Today's Volume", "Average Volume(20)"]:
        output[column] = output[column].map(lambda value: f"{value:,.0f}")

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Screen NSE stocks with the configured swing-trading strategy."
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Optional NSE symbols to scan, for example: RELIANCE TCS INFY. Defaults to all NSE EQ stocks.",
    )
    parser.add_argument("--period", default="18mo", help="Yahoo Finance history period. Default: 18mo.")
    parser.add_argument("--batch-size", type=int, default=80, help="Yahoo Finance batch size. Default: 80.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between batches. Default: 1.")
    parser.add_argument("--limit", type=int, help="Limit displayed results.")
    parser.add_argument("--output", help="Optional CSV output path.")
    parser.add_argument(
        "--strategy",
        choices=["all", "optimized", *SCREENERS.keys()],
        default="all",
        help="Strategy version to run. Default: all.",
    )
    parser.add_argument(
        "--save-db",
        action="store_true",
        help="Save matching BUY triggers to Supabase. Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
    )
    parser.add_argument(
        "--update-trigger-prices",
        action="store_true",
        help="Update close-price history for stored triggers from trigger date through the latest market data.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ScreenConfig(
        period=args.period,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
        limit=args.limit,
        output=args.output,
        strategy=args.strategy,
        save_db=args.save_db,
        update_trigger_prices=args.update_trigger_prices,
    )

    symbols = [symbol.upper().replace(".NS", "") for symbol in args.symbols] if args.symbols else fetch_nse_symbols()
    print(f"Scanning {len(symbols)} NSE stocks with strategy={config.strategy}...", file=sys.stderr)

    results = sort_results(download_histories(symbols, config))
    if results.empty:
        if config.update_trigger_prices:
            client = get_supabase_client()
            price_rows = save_trigger_prices_to_supabase(client, fetch_triggers_for_price_updates(client))
            print(f"Upserted {price_rows} trigger close-price rows to Supabase.", file=sys.stderr)
        print("No stocks matched the selected strategy setup.")
        return 0

    if config.limit:
        results = results.head(config.limit)

    if config.output:
        results.to_csv(config.output, index=False)
        print(f"Saved full numeric results to {config.output}", file=sys.stderr)

    if config.save_db:
        client = get_supabase_client()
        saved_triggers = save_triggers_to_supabase(results, client)
        print(f"Saved {len(saved_triggers)} trigger rows to Supabase.", file=sys.stderr)

        if config.update_trigger_prices:
            price_rows = save_trigger_prices_to_supabase(client, fetch_triggers_for_price_updates(client))
            print(f"Upserted {price_rows} trigger close-price rows to Supabase.", file=sys.stderr)
    elif config.update_trigger_prices:
        client = get_supabase_client()
        price_rows = save_trigger_prices_to_supabase(client, fetch_triggers_for_price_updates(client))
        print(f"Upserted {price_rows} trigger close-price rows to Supabase.", file=sys.stderr)

    print(tabulate(format_output(results), headers="keys", tablefmt="github", showindex=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
