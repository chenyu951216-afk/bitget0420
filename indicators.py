from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any

import numpy as np
import pandas as pd


@dataclass
class ReversalResult:
    symbol: str
    score: int
    triggered: bool
    reasons: list[str]
    payload: Dict[str, Any]


def prepare_dataframe(ohlcv: list[list[float]]) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.dropna().reset_index(drop=True)


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def macd_hist(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    a = df["high"] - df["low"]
    b = (df["high"] - prev_close).abs()
    c = (df["low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def upper_wick_ratio(candle: pd.Series) -> float:
    body = abs(float(candle["close"]) - float(candle["open"]))
    upper = float(candle["high"]) - max(float(candle["open"]), float(candle["close"]))
    if body <= 1e-9:
        return upper / max(float(candle["high"]) - float(candle["low"]), 1e-9)
    return upper / body


def detect_bearish_engulfing(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    prev_candle = df.iloc[-2]
    candle = df.iloc[-1]
    prev_bull = prev_candle["close"] > prev_candle["open"]
    curr_bear = candle["close"] < candle["open"]
    engulf = candle["open"] >= prev_candle["close"] and candle["close"] <= prev_candle["open"]
    return bool(prev_bull and curr_bear and engulf)


def analyze_reversal(
    symbol: str,
    fast_df: pd.DataFrame,
    slow_df: pd.DataFrame,
    rsi_overbought: float,
    rsi_exit: float,
    min_wick_body_ratio: float,
    near_high_lookback: int,
    near_high_atr_ratio: float,
    min_score: int,
) -> ReversalResult:
    if fast_df.empty or slow_df.empty or len(fast_df) < 50 or len(slow_df) < 50:
        return ReversalResult(symbol, 0, False, ["K線資料不足"], {})

    fast = fast_df.copy()
    slow = slow_df.copy()

    fast["ema9"] = ema(fast["close"], 9)
    fast["ema21"] = ema(fast["close"], 21)
    fast["rsi14"] = rsi(fast["close"], 14)
    fast["macd_hist"] = macd_hist(fast["close"])
    fast["atr14"] = atr(fast, 14)

    slow["ema20"] = ema(slow["close"], 20)
    slow["ema50"] = ema(slow["close"], 50)
    slow["atr14"] = atr(slow, 14)

    curr = fast.iloc[-1]
    prev = fast.iloc[-2]
    slow_curr = slow.iloc[-1]

    score = 0
    reasons: list[str] = []

    recent_high = float(fast["high"].tail(near_high_lookback).max())
    distance_from_high = recent_high - float(curr["close"])
    near_high = distance_from_high <= max(float(curr["atr14"]) * near_high_atr_ratio, 1e-9)
    if near_high:
        score += 1
        reasons.append("價格仍在近期高檔附近")

    rsi_drop = float(prev["rsi14"]) >= rsi_overbought and float(curr["rsi14"]) <= rsi_exit
    if rsi_drop:
        score += 2
        reasons.append(f"RSI 從過熱區回落（{prev['rsi14']:.1f} → {curr['rsi14']:.1f}）")

    lost_ema9 = float(curr["close"]) < float(curr["ema9"])
    if lost_ema9:
        score += 1
        reasons.append("收盤跌回 EMA9 下方")

    macd_turn = float(curr["macd_hist"]) < float(prev["macd_hist"])
    if macd_turn:
        score += 1
        reasons.append("MACD 動能柱轉弱")

    wick_ratio = upper_wick_ratio(curr)
    bearish_wick = wick_ratio >= min_wick_body_ratio and float(curr["close"]) < float(curr["open"])
    if bearish_wick:
        score += 1
        reasons.append(f"5m 出現長上影轉弱 K（上影/實體={wick_ratio:.2f}）")

    slow_rejection = (
        float(slow_curr["close"]) < float(slow_curr["open"])
        and float(slow_curr["close"]) < float(slow_curr["ema20"])
    )
    if slow_rejection:
        score += 1
        reasons.append("15m 也開始轉弱")

    engulfing = detect_bearish_engulfing(fast.tail(2))
    if engulfing:
        score += 1
        reasons.append("5m 出現吞噬型反轉")

    extension_pct = ((float(curr["close"]) / max(float(slow_curr["ema50"]), 1e-9)) - 1.0) * 100
    payload = {
        "symbol": symbol,
        "last_price": float(curr["close"]),
        "ema9": float(curr["ema9"]),
        "ema21": float(curr["ema21"]),
        "rsi14": float(curr["rsi14"]),
        "macd_hist": float(curr["macd_hist"]),
        "recent_high": recent_high,
        "distance_from_high": distance_from_high,
        "near_high": near_high,
        "upper_wick_ratio": wick_ratio,
        "slow_ema20": float(slow_curr["ema20"]),
        "slow_ema50": float(slow_curr["ema50"]),
        "extension_vs_ema50_pct": extension_pct,
        "slow_bearish": slow_rejection,
        "bearish_engulfing": engulfing,
    }

    return ReversalResult(symbol, score, score >= min_score, reasons, payload)
