#!/usr/bin/env python3
"""
Discovery backtest for 1-month NSE swing strategy variants.

This script does not write to Supabase and does not modify main.py. It reuses
the existing NSE/Yahoo helpers and indicators, then writes two CSV files:
    strategy_discovery_trades.csv
    strategy_discovery_summary.csv
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from main import (
    MIN_AVG_TRADED_VALUE,
    MIN_PRICE,
    bullish_engulfing,
    chunks,
    closes_in_top_pct,
    fetch_nse_symbols,
    flatten_downloaded_data,
    iso_date_from_index,
    nse_symbol,
    prepare_history,
    pullback_or_sideways_consolidation,
    yahoo_symbol,
)


DEFAULT_START_DATE = "2025-01-01"
DEFAULT_TRADES_OUTPUT = "strategy_discovery_trades.csv"
DEFAULT_SUMMARY_OUTPUT = "strategy_discovery_summary.csv"
DEFAULT_MAX_SYMBOLS = 2400
WARMUP_DAYS = 450
HOLDING_DAYS = 30
TARGET_PCT = 5.0
STOP_PCT = 4.0


@dataclass(frozen=True)
class DiscoveryConfig:
    start_date: str
    end_date: str
    batch_size: int
    sleep_seconds: float
    max_symbols: int | None
    trades_output: str
    summary_output: str
    target_pct: float
    stop_pct: float
    holding_days: int


StrategyFn = Callable[[str, pd.DataFrame], Optional[dict]]


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD format.") from exc


def pct_return(exit_price: float | None, entry_price: float) -> float | None:
    if exit_price is None or entry_price <= 0:
        return None
    return (exit_price - entry_price) / entry_price * 100


def is_positive_number(value: float) -> bool:
    return not math.isnan(value) and value > 0


def close_at(history: pd.DataFrame, trigger_position: int, offset: int) -> float | None:
    target_position = trigger_position + offset
    if target_position >= len(history):
        return None
    close_price = history.iloc[target_position].get("Close")
    if pd.isna(close_price):
        return None
    return float(close_price)


def daily_close_values(history: pd.DataFrame, trigger_position: int, holding_days: int) -> dict[str, float | None]:
    return {
        f"Day {offset} Close": close_at(history, trigger_position, offset)
        for offset in range(1, holding_days + 1)
    }


def distance_from_level_pct(price: float, level: float) -> float:
    return abs(price - level) / level * 100


def latest_signal_values(symbol: str, history: pd.DataFrame, strategy_variant: str, signal_pattern: str) -> dict[str, float | str] | None:
    if len(history) < 252:
        return None

    latest = history.iloc[-1]
    close_price = float(latest["Close"])
    ema21 = float(latest["EMA21"])
    dma50 = float(latest["DMA50"])
    dma200 = float(latest["DMA200"])
    rsi14 = float(latest["RSI14"])
    latest_volume = float(latest["Volume"])
    avg_volume20 = float(latest["AvgVol20"])
    high_52w = float(latest["High52W"])

    values = [close_price, ema21, dma50, dma200, rsi14, latest_volume, avg_volume20, high_52w]
    if not all(is_positive_number(value) for value in values):
        return None

    avg_traded_value = close_price * avg_volume20
    if avg_traded_value < MIN_AVG_TRADED_VALUE or close_price < MIN_PRICE:
        return None

    return {
        "Strategy Variant": strategy_variant,
        "Symbol": symbol,
        "Entry Date": iso_date_from_index(latest.name),
        "Recommendation": "BUY",
        "Signal Pattern": signal_pattern,
        "Entry Close": close_price,
        "21 EMA": ema21,
        "50 DMA": dma50,
        "200 DMA": dma200,
        "RSI(14)": rsi14,
        "Volume": latest_volume,
        "Average Volume(20)": avg_volume20,
        "Relative Volume (RVOL)": latest_volume / avg_volume20,
        "Distance from 52-week High (%)": (high_52w - close_price) / high_52w * 100,
        "Distance from 21 EMA (%)": distance_from_level_pct(close_price, ema21),
        "Avg Traded Value": avg_traded_value,
    }


def low_near_level(low_price: float, level: float, tolerance_pct: float) -> bool:
    return low_price <= level * (1 + tolerance_pct / 100)


def has_bullish_engulfing(history: pd.DataFrame) -> bool:
    if len(history) < 2:
        return False
    return bullish_engulfing(history.iloc[-2], history.iloc[-1])


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


def strategy_be_pullback_continuation(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = latest_signal_values(symbol, history, "BE_PULLBACK_CONTINUATION", "Bullish Engulfing")
    if result is None or not has_bullish_engulfing(history):
        return None

    latest = history.iloc[-1]
    passes = [
        float(result["Entry Close"]) > float(result["200 DMA"]),
        float(result["21 EMA"]) > float(result["50 DMA"]),
        float(result["Distance from 21 EMA (%)"]) <= 2,
        55 <= float(result["RSI(14)"]) <= 72,
        pullback_or_sideways_consolidation(history),
        closes_in_top_pct(latest, 0.30),
    ]
    return result if all(passes) else None


def strategy_be_52w_high_pullback(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = latest_signal_values(symbol, history, "BE_52W_HIGH_PULLBACK", "Bullish Engulfing")
    if result is None or not has_bullish_engulfing(history):
        return None

    latest = history.iloc[-1]
    previous = history.iloc[-2]
    low_price = float(latest["Low"])
    passes = [
        float(result["Distance from 52-week High (%)"]) <= 12,
        float(result["Entry Close"]) > float(result["50 DMA"]) > float(result["200 DMA"]),
        low_near_level(low_price, float(result["21 EMA"]), 1.5) or low_near_level(low_price, float(result["50 DMA"]), 1.5),
        float(result["Volume"]) > float(previous["Volume"]),
        55 <= float(result["RSI(14)"]) <= 75,
    ]
    return result if all(passes) else None


def strategy_be_volume_reversal(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = latest_signal_values(symbol, history, "BE_VOLUME_REVERSAL", "Bullish Engulfing")
    if result is None or not has_bullish_engulfing(history):
        return None

    latest = history.iloc[-1]
    previous = history.iloc[-2]
    passes = [
        float(result["Volume"]) >= float(result["Average Volume(20)"]) * 1.2,
        float(previous["Close"]) < float(previous["Open"]),
        float(latest["Close"]) > float(previous["High"]),
        float(result["Entry Close"]) > float(result["200 DMA"]),
        float(result["RSI(14)"]) > 50,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    return result if all(passes) else None


def strategy_range_breakout_volume(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = latest_signal_values(symbol, history, "RANGE_BREAKOUT_VOLUME", "20D High Breakout")
    if result is None or len(history) < 22:
        return None

    latest = history.iloc[-1]
    previous_20_day_high = float(history.iloc[-21:-1]["High"].max())
    passes = [
        float(result["Entry Close"]) > previous_20_day_high,
        float(result["Volume"]) >= float(result["Average Volume(20)"]) * 1.5,
        float(result["Entry Close"]) > float(result["21 EMA"]) > float(result["50 DMA"]) > float(result["200 DMA"]),
        60 <= float(result["RSI(14)"]) <= 78,
        float(result["Distance from 21 EMA (%)"]) <= 8,
        closes_in_top_pct(latest, 0.25),
    ]
    return result if all(passes) else None


def strategy_tight_consolidation_breakout(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = latest_signal_values(symbol, history, "TIGHT_CONSOLIDATION_BREAKOUT", "5D Tight Breakout")
    if result is None or len(history) < 7:
        return None

    previous_5 = history.iloc[-6:-1]
    close_mean = float(previous_5["Close"].mean())
    if close_mean <= 0:
        return None

    close_range_pct = (float(previous_5["Close"].max()) - float(previous_5["Close"].min())) / close_mean * 100
    consolidation_high = float(previous_5["High"].max())
    passes = [
        close_range_pct <= 4,
        float(result["Entry Close"]) > consolidation_high,
        float(result["Volume"]) >= float(result["Average Volume(20)"]) * 1.2,
        float(result["Entry Close"]) > float(result["50 DMA"]) > float(result["200 DMA"]),
        float(result["Distance from 52-week High (%)"]) <= 15,
    ]
    return result if all(passes) else None


def strategy_momentum_pullback_reclaim(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = latest_signal_values(symbol, history, "MOMENTUM_PULLBACK_RECLAIM", "21 EMA Reclaim")
    if result is None or len(history) < 64:
        return None

    latest = history.iloc[-1]
    previous = history.iloc[-2]
    passes = [
        three_month_return_positive(history),
        has_recent_pullback(history),
        float(previous["Close"]) < float(previous["EMA21"]),
        float(latest["Close"]) > float(latest["EMA21"]),
        float(latest["Close"]) > float(latest["Open"]),
        float(latest["Volume"]) > float(previous["Volume"]),
        50 <= float(result["RSI(14)"]) <= 70,
    ]
    return result if all(passes) else None


def strategy_be_volume_reversal_rsi_65_68(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_be_volume_reversal(symbol, history)
    if result is None:
        return None

    passes = [
        65 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) >= 1.2,
        float(result["Distance from 52-week High (%)"]) <= 10,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    if not all(passes):
        return None

    result = dict(result)
    result["Strategy Variant"] = "BE_VOLUME_REVERSAL_RSI_65_68"
    return result


def strategy_be_volume_reversal_high_confidence(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_be_volume_reversal(symbol, history)
    if result is None:
        return None

    passes = [
        62 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) >= 1.5,
        float(result["Distance from 52-week High (%)"]) <= 5,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    if not all(passes):
        return None

    result = dict(result)
    result["Strategy Variant"] = "BE_VOLUME_REVERSAL_HIGH_CONFIDENCE"
    return result


def strategy_range_breakout_volume_rsi_65_68(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_range_breakout_volume(symbol, history)
    if result is None:
        return None

    passes = [
        65 <= float(result["RSI(14)"]) <= 68,
        float(result["Relative Volume (RVOL)"]) >= 2.0,
        float(result["Distance from 52-week High (%)"]) <= 8,
        float(result["Distance from 21 EMA (%)"]) <= 8,
    ]
    if not all(passes):
        return None

    result = dict(result)
    result["Strategy Variant"] = "RANGE_BREAKOUT_VOLUME_RSI_65_68"
    return result


def strategy_momentum_pullback_tight_ema(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_momentum_pullback_reclaim(symbol, history)
    if result is None:
        return None

    passes = [
        float(result["RSI(14)"]) >= 55,
        float(result["Relative Volume (RVOL)"]) >= 0.8,
        float(result["Distance from 52-week High (%)"]) <= 10,
        float(result["Distance from 21 EMA (%)"]) <= 1.5,
    ]
    if not all(passes):
        return None

    result = dict(result)
    result["Strategy Variant"] = "MOMENTUM_PULLBACK_TIGHT_EMA"
    return result


def strategy_be_volume_hc_balanced(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_be_volume_reversal_high_confidence(symbol, history)
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

    result = dict(result)
    result["Strategy Variant"] = "BE_VOLUME_HC_BALANCED"
    return result


def strategy_be_volume_hc_early_surge(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_be_volume_reversal_high_confidence(symbol, history)
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

    result = dict(result)
    result["Strategy Variant"] = "BE_VOLUME_HC_EARLY_SURGE"
    return result


def strategy_be_volume_hc_mid_52w(symbol: str, history: pd.DataFrame) -> dict[str, float | str] | None:
    result = strategy_be_volume_reversal_high_confidence(symbol, history)
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

    result = dict(result)
    result["Strategy Variant"] = "BE_VOLUME_HC_MID_52W"
    return result


STRATEGIES: tuple[StrategyFn, ...] = (
    strategy_be_volume_reversal_rsi_65_68,
    strategy_be_volume_reversal_high_confidence,
    strategy_range_breakout_volume_rsi_65_68,
    strategy_momentum_pullback_tight_ema,
    strategy_be_volume_hc_balanced,
    strategy_be_volume_hc_early_surge,
    strategy_be_volume_hc_mid_52w,
)


def exit_values(
    history: pd.DataFrame,
    trigger_date: pd.Timestamp,
    entry_close: float,
    config: DiscoveryConfig,
) -> dict[str, float | int | str | bool | None]:
    trigger_position = history.index.get_loc(trigger_date)
    if isinstance(trigger_position, slice) or not isinstance(trigger_position, int):
        return {}

    forward = history.iloc[trigger_position + 1 : trigger_position + config.holding_days + 1].dropna(
        subset=["High", "Low", "Close"]
    )
    values: dict[str, float | int | str | bool | None] = {
        **daily_close_values(history, trigger_position, config.holding_days),
        "Max Favorable Move 30D (%)": None,
        "Max Drawdown 30D (%)": None,
        "30D Close Return (%)": pct_return(close_at(history, trigger_position, config.holding_days), entry_close),
        "Target Hit": False,
        "Stop Hit": False,
        "Exit Reason": "Insufficient Data",
        "Exit Date": "",
        "Exit Return (%)": None,
        "Days Held": len(forward),
    }

    if not forward.empty:
        values["Max Favorable Move 30D (%)"] = pct_return(float(forward["High"].max()), entry_close)
        values["Max Drawdown 30D (%)"] = pct_return(float(forward["Low"].min()), entry_close)

    target_price = entry_close * (1 + config.target_pct / 100)
    stop_price = entry_close * (1 - config.stop_pct / 100)
    values["Target Hit"] = bool(forward["High"].ge(target_price).any()) if not forward.empty else False
    values["Stop Hit"] = bool(forward["Low"].le(stop_price).any()) if not forward.empty else False

    for index, row in forward.iterrows():
        high_price = float(row["High"])
        low_price = float(row["Low"])

        if low_price <= stop_price:
            values["Exit Reason"] = "Stop"
            values["Exit Date"] = iso_date_from_index(index)
            values["Exit Return (%)"] = -config.stop_pct
            return values

        if high_price >= target_price:
            values["Exit Reason"] = "Target"
            values["Exit Date"] = iso_date_from_index(index)
            values["Exit Return (%)"] = config.target_pct
            return values

    if len(forward) >= config.holding_days:
        final_row = forward.iloc[config.holding_days - 1]
        final_close = float(final_row["Close"])
        values["Exit Reason"] = "Time"
        values["Exit Date"] = iso_date_from_index(forward.index[config.holding_days - 1])
        values["Exit Return (%)"] = pct_return(final_close, entry_close)

    return values


def completed_history(history: pd.DataFrame) -> pd.DataFrame:
    required_columns = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required_columns).issubset(history.columns):
        return pd.DataFrame()
    cleaned = history.dropna(subset=required_columns).copy()
    return cleaned[cleaned["Volume"] > 0]


def backtest_symbol(symbol: str, history: pd.DataFrame, config: DiscoveryConfig) -> list[dict[str, float | int | str | bool | None]]:
    history = completed_history(history)
    prepared_history = prepare_history(history)
    if prepared_history is None:
        return []

    start_ts = pd.Timestamp(config.start_date)
    end_ts = pd.Timestamp(config.end_date)
    backtest_dates = [index for index in prepared_history.index if start_ts <= pd.Timestamp(index) <= end_ts]
    rows: list[dict[str, float | int | str | bool | None]] = []

    for index in backtest_dates:
        index_ts = pd.Timestamp(index)
        history_to_date = prepared_history.loc[:index_ts]
        if len(history_to_date) < 252:
            continue

        for strategy in STRATEGIES:
            signal = strategy(symbol, history_to_date)
            if signal is None:
                continue
            rows.append(
                {
                    **signal,
                    **exit_values(prepared_history, index_ts, float(signal["Entry Close"]), config),
                }
            )

    return rows


def download_histories(symbols: list[str], config: DiscoveryConfig) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    start = (parse_date(config.start_date) - timedelta(days=WARMUP_DAYS)).isoformat()
    fetch_end = min(
        parse_date(config.end_date) + timedelta(days=70),
        date.today() + timedelta(days=1),
    ).isoformat()
    total_batches = math.ceil(len(symbols) / config.batch_size)

    for index, symbol_batch in enumerate(chunks(symbols, config.batch_size), start=1):
        tickers = [yahoo_symbol(symbol) for symbol in symbol_batch]
        print(f"Downloading batch {index}/{total_batches} ({len(tickers)} stocks)...", file=sys.stderr)

        try:
            data = yf.download(
                tickers=tickers,
                start=start,
                end=fetch_end,
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
            clean_history = history.dropna(how="all").copy()
            if not clean_history.empty:
                histories[nse_symbol(ticker)] = clean_history

        if index < total_batches and config.sleep_seconds:
            time.sleep(config.sleep_seconds)

    return histories


def profit_factor(returns: pd.Series) -> float | None:
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / abs(losses)


def summarize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Strategy Variant",
        "Trades",
        "Completed Trades",
        "Open Trades",
        "Win Rate (%)",
        "Average Exit Return (%)",
        "Median Exit Return (%)",
        "Average Max Drawdown 30D (%)",
        "Average Max Favorable Move 30D (%)",
        "Profit Factor",
        "Target Hits",
        "Stop Hits",
        "Time Exits",
    ]
    if trades.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, float | int | str | None]] = []
    for strategy_variant, group in trades.groupby("Strategy Variant"):
        completed = group.dropna(subset=["Exit Return (%)"]).copy()
        returns = completed["Exit Return (%)"]
        rows.append(
            {
                "Strategy Variant": strategy_variant,
                "Trades": len(group),
                "Completed Trades": len(completed),
                "Open Trades": len(group) - len(completed),
                "Win Rate (%)": group["Target Hit"].mean() * 100,
                "Average Exit Return (%)": None if completed.empty else returns.mean(),
                "Median Exit Return (%)": None if completed.empty else returns.median(),
                "Average Max Drawdown 30D (%)": group["Max Drawdown 30D (%)"].mean(),
                "Average Max Favorable Move 30D (%)": group["Max Favorable Move 30D (%)"].mean(),
                "Profit Factor": None if completed.empty else profit_factor(returns),
                "Target Hits": int(group["Target Hit"].sum()),
                "Stop Hits": int(group["Stop Hit"].sum()),
                "Time Exits": int(group["Exit Reason"].eq("Time").sum()),
            }
        )

    return pd.DataFrame(rows, columns=columns).sort_values(
        by=[
            "Win Rate (%)",
            "Completed Trades",
            "Average Exit Return (%)",
            "Average Max Drawdown 30D (%)",
            "Profit Factor",
            "Median Exit Return (%)",
        ],
        ascending=[False, False, False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)


def trade_columns(holding_days: int) -> list[str]:
    return [
        "Strategy Variant",
        "Symbol",
        "Entry Date",
        "Recommendation",
        "Signal Pattern",
        "Entry Close",
        "21 EMA",
        "50 DMA",
        "200 DMA",
        "RSI(14)",
        "Volume",
        "Average Volume(20)",
        "Relative Volume (RVOL)",
        "Distance from 52-week High (%)",
        "Distance from 21 EMA (%)",
        "Avg Traded Value",
        *[f"Day {offset} Close" for offset in range(1, holding_days + 1)],
        "Max Favorable Move 30D (%)",
        "Max Drawdown 30D (%)",
        "30D Close Return (%)",
        "Target Hit",
        "Stop Hit",
        "Exit Reason",
        "Exit Date",
        "Exit Return (%)",
        "Days Held",
    ]


def sort_trades(rows: list[dict[str, float | int | str | bool | None]], holding_days: int) -> pd.DataFrame:
    columns = trade_columns(holding_days)
    if not rows:
        return pd.DataFrame(columns=columns)

    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return frame.loc[:, columns].sort_values(
        by=["Entry Date", "Strategy Variant", "Symbol"],
        ascending=[True, True, True],
    ).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    today = date.today().isoformat()
    parser = argparse.ArgumentParser(description="Discover and rank 1-month NSE swing strategy variants.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Optional NSE symbols to backtest, for example: RELIANCE TCS INFY.",
    )
    parser.add_argument("--start-date", type=parse_date, default=parse_date(DEFAULT_START_DATE), help=f"Default: {DEFAULT_START_DATE}.")
    parser.add_argument("--end-date", type=parse_date, default=parse_date(today), help=f"Default: {today}.")
    parser.add_argument("--batch-size", type=int, default=80, help="Yahoo Finance batch size. Default: 80.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between batches. Default: 1.")
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=DEFAULT_MAX_SYMBOLS,
        help=f"Limit sorted NSE symbols. Default: {DEFAULT_MAX_SYMBOLS}.",
    )
    parser.add_argument("--all-symbols", action="store_true", help="Ignore --max-symbols and process all fetched NSE EQ symbols.")
    parser.add_argument("--trades-output", default=DEFAULT_TRADES_OUTPUT, help=f"Default: {DEFAULT_TRADES_OUTPUT}.")
    parser.add_argument("--summary-output", default=DEFAULT_SUMMARY_OUTPUT, help=f"Default: {DEFAULT_SUMMARY_OUTPUT}.")
    parser.add_argument("--target-pct", type=float, default=TARGET_PCT, help=f"Profit target percent. Default: {TARGET_PCT:g}.")
    parser.add_argument("--stop-pct", type=float, default=STOP_PCT, help=f"Stop loss percent. Default: {STOP_PCT:g}.")
    parser.add_argument("--holding-days", type=int, default=HOLDING_DAYS, help=f"Trading-day holding window. Default: {HOLDING_DAYS}.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.end_date < args.start_date:
        print("--end-date must be on or after --start-date.", file=sys.stderr)
        return 2
    if args.holding_days <= 0:
        print("--holding-days must be greater than 0.", file=sys.stderr)
        return 2
    if args.target_pct <= 0 or args.stop_pct <= 0:
        print("--target-pct and --stop-pct must be greater than 0.", file=sys.stderr)
        return 2

    max_symbols = None if args.all_symbols else args.max_symbols
    if max_symbols is not None and max_symbols <= 0:
        print("--max-symbols must be greater than 0.", file=sys.stderr)
        return 2

    config = DiscoveryConfig(
        start_date=args.start_date.isoformat(),
        end_date=args.end_date.isoformat(),
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
        max_symbols=max_symbols,
        trades_output=args.trades_output,
        summary_output=args.summary_output,
        target_pct=args.target_pct,
        stop_pct=args.stop_pct,
        holding_days=args.holding_days,
    )

    symbols = [symbol.upper().replace(".NS", "") for symbol in args.symbols] if args.symbols else fetch_nse_symbols()
    if config.max_symbols is not None:
        symbols = symbols[: config.max_symbols]

    print(
        f"Backtesting {len(symbols)} NSE stocks from {config.start_date} to {config.end_date} "
        f"with {len(STRATEGIES)} strategy variants...",
        file=sys.stderr,
    )

    histories = download_histories(symbols, config)
    rows: list[dict[str, float | int | str | bool | None]] = []
    for index, symbol in enumerate(symbols, start=1):
        history = histories.get(symbol)
        if history is None:
            continue
        rows.extend(backtest_symbol(symbol, history, config))
        if index % 100 == 0:
            print(f"Processed {index}/{len(symbols)} stocks, found {len(rows)} trades...", file=sys.stderr)

    trades = sort_trades(rows, config.holding_days)
    summary = summarize_trades(trades)
    trades.to_csv(config.trades_output, index=False)
    summary.to_csv(config.summary_output, index=False)

    print(f"Saved {len(trades)} trades to {config.trades_output}")
    print(f"Saved {len(summary)} strategy summary rows to {config.summary_output}")
    if not summary.empty:
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
