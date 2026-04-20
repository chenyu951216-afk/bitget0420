from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

import ccxt

import config
from indicators import prepare_dataframe, analyze_reversal
from notifier import DiscordNotifier


class BitgetReversalScanner:
    def __init__(self) -> None:
        options = {"defaultType": config.MARKET_TYPE}
        self.exchange = ccxt.bitget({"enableRateLimit": True, "options": options})
        self.exchange.timeout = 15000
        self.notifier = DiscordNotifier(
            webhook_url=config.DISCORD_WEBHOOK_URL,
            username=config.DISCORD_USERNAME,
            avatar_url=config.DISCORD_AVATAR_URL,
        )
        self.lock = threading.RLock()
        self.cooldowns: Dict[str, float] = {}
        self.state: Dict[str, Any] = {
            "running": False,
            "last_scan_at": None,
            "last_error": "",
            "scan_count": 0,
            "market_rows": [],
            "alerts_sent": [],
        }

    def _now_str(self) -> str:
        return datetime.now(ZoneInfo(config.TZ_NAME)).strftime("%Y-%m-%d %H:%M:%S")

    def _quote_ok(self, symbol: str) -> bool:
        return f"/{config.QUOTE}" in symbol or symbol.endswith(config.QUOTE)

    def _market_ok(self, market: Dict[str, Any]) -> bool:
        if config.MARKET_TYPE == "swap" and not market.get("swap"):
            return False
        if config.MARKET_TYPE == "spot" and not market.get("spot"):
            return False
        if not self._quote_ok(market.get("symbol", "")):
            return False
        return market.get("active", True)

    def fetch_top_gainers(self) -> List[Dict[str, Any]]:
        markets = self.exchange.load_markets()
        tickers = self.exchange.fetch_tickers()
        rows: list[Dict[str, Any]] = []

        for symbol, ticker in tickers.items():
            market = markets.get(symbol)
            if not market or not self._market_ok(market):
                continue
            pct = ticker.get("percentage")
            last = ticker.get("last")
            if pct is None or last in (None, 0):
                continue
            try:
                pct = float(pct)
                last = float(last)
            except Exception:
                continue
            if pct < config.MIN_24H_CHANGE_PCT:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "change_pct": pct,
                    "last": last,
                    "base_volume": float(ticker.get("baseVolume") or 0),
                    "quote_volume": float(ticker.get("quoteVolume") or 0),
                }
            )

        rows.sort(key=lambda x: (x["change_pct"], x["quote_volume"]), reverse=True)
        top_rows = rows[: config.TOP_N]
        for idx, row in enumerate(top_rows, start=1):
            row["rank"] = idx
        return top_rows

    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def analyze_symbol(self, row: Dict[str, Any]) -> Dict[str, Any]:
        symbol = row["symbol"]
        fast_df = prepare_dataframe(self._fetch_ohlcv(symbol, config.FAST_TIMEFRAME, config.OHLCV_LIMIT_FAST))
        slow_df = prepare_dataframe(self._fetch_ohlcv(symbol, config.SLOW_TIMEFRAME, config.OHLCV_LIMIT_SLOW))
        reversal = analyze_reversal(
            symbol=symbol,
            fast_df=fast_df,
            slow_df=slow_df,
            rsi_overbought=config.RSI_OVERBOUGHT,
            rsi_exit=config.RSI_EXIT,
            min_wick_body_ratio=config.MIN_WICK_BODY_RATIO,
            near_high_lookback=config.NEAR_HIGH_LOOKBACK,
            near_high_atr_ratio=config.NEAR_HIGH_ATR_RATIO,
            min_score=config.MIN_REVERSAL_SCORE,
        )
        result = {
            "score": reversal.score,
            "triggered": reversal.triggered,
            "reasons": reversal.reasons,
            "payload": reversal.payload,
        }
        return result

    def _can_alert(self, symbol: str) -> bool:
        now = time.time()
        last = self.cooldowns.get(symbol, 0)
        return now - last >= config.ALERT_COOLDOWN_SEC

    def _mark_alerted(self, symbol: str) -> None:
        self.cooldowns[symbol] = time.time()

    def scan_once(self) -> Dict[str, Any]:
        rows = self.fetch_top_gainers()
        analyzed_rows = []
        alerts_sent = []

        for row in rows:
            result = self.analyze_symbol(row)
            row["reversal"] = result
            analyzed_rows.append(row)
            if result["triggered"] and self._can_alert(row["symbol"]):
                try:
                    sent = self.notifier.send_reversal_alert(row, result)
                    if sent:
                        self._mark_alerted(row["symbol"])
                        alerts_sent.append(
                            {
                                "symbol": row["symbol"],
                                "change_pct": row["change_pct"],
                                "score": result["score"],
                                "time": self._now_str(),
                            }
                        )
                except Exception as exc:
                    alerts_sent.append(
                        {
                            "symbol": row["symbol"],
                            "change_pct": row["change_pct"],
                            "score": result["score"],
                            "time": self._now_str(),
                            "error": str(exc),
                        }
                    )

        with self.lock:
            self.state["last_scan_at"] = self._now_str()
            self.state["scan_count"] += 1
            self.state["market_rows"] = analyzed_rows
            self.state["alerts_sent"] = alerts_sent[:30]
            self.state["last_error"] = ""
            return dict(self.state)

    def loop_forever(self) -> None:
        with self.lock:
            self.state["running"] = True
        while True:
            try:
                self.scan_once()
            except Exception as exc:
                with self.lock:
                    self.state["last_error"] = f"{type(exc).__name__}: {exc}"
                    self.state["last_scan_at"] = self._now_str()
            time.sleep(config.SCAN_INTERVAL_SEC)

    def start_background(self) -> None:
        worker = threading.Thread(target=self.loop_forever, daemon=True, name="bitget-reversal-scanner")
        worker.start()

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.state)
