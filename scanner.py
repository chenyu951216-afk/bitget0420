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
        self.worker: threading.Thread | None = None

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

    def _log(self, msg: str) -> None:
        print(f"[scanner] {msg}", flush=True)

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

    def _strong_threshold(self) -> int:
        return max(1, int(config.MIN_REVERSAL_SCORE))

    def _prealert_threshold(self) -> int:
        strong = self._strong_threshold()
        return max(1, strong - 1)

    def fetch_top_gainers(self) -> List[Dict[str, Any]]:
        self._log("loading markets and tickers...")
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

        self._log(
            f"top gainers filtered: total_match={len(rows)} selected_top_n={len(top_rows)} "
            f"min_change={config.MIN_24H_CHANGE_PCT}% top_n={config.TOP_N}"
        )
        return top_rows

    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def analyze_symbol(self, row: Dict[str, Any]) -> Dict[str, Any]:
        symbol = row["symbol"]

        self._log(
            f"analyzing {symbol} rank={row.get('rank')} change={row.get('change_pct', 0):.2f}%"
        )

        fast_df = prepare_dataframe(
            self._fetch_ohlcv(symbol, config.FAST_TIMEFRAME, config.OHLCV_LIMIT_FAST)
        )
        slow_df = prepare_dataframe(
            self._fetch_ohlcv(symbol, config.SLOW_TIMEFRAME, config.OHLCV_LIMIT_SLOW)
        )

        reversal = analyze_reversal(
            symbol=symbol,
            fast_df=fast_df,
            slow_df=slow_df,
            rsi_overbought=config.RSI_OVERBOUGHT,
            rsi_exit=config.RSI_EXIT,
            min_wick_body_ratio=config.MIN_WICK_BODY_RATIO,
            near_high_lookback=config.NEAR_HIGH_LOOKBACK,
            near_high_atr_ratio=config.NEAR_HIGH_ATR_RATIO,
            min_score=self._strong_threshold(),
        )

        strong_threshold = self._strong_threshold()
        prealert_threshold = self._prealert_threshold()
        score = int(reversal.score)

        is_strong = score >= strong_threshold
        is_prealert = (score >= prealert_threshold) and not is_strong

        if is_strong:
            alert_level = "strong"
            status_text = "強信號"
        elif is_prealert:
            alert_level = "prealert"
            status_text = "預警"
        else:
            alert_level = "watch"
            status_text = "觀察中"

        result = {
            "score": score,
            "triggered": is_strong,
            "prealert": is_prealert,
            "reasons": reversal.reasons,
            "payload": reversal.payload,
            "alert_level": alert_level,
            "status_text": status_text,
            "strong_threshold": strong_threshold,
            "prealert_threshold": prealert_threshold,
        }

        self._log(
            f"{symbol} analyzed -> score={result['score']} level={result['alert_level']} "
            f"triggered={result['triggered']} prealert={result['prealert']}"
        )
        return result

    def _cooldown_key(self, symbol: str, level: str) -> str:
        return f"{symbol}::{level}"

    def _can_alert(self, symbol: str, level: str) -> bool:
        now = time.time()
        last = self.cooldowns.get(self._cooldown_key(symbol, level), 0)
        return now - last >= config.ALERT_COOLDOWN_SEC

    def _mark_alerted(self, symbol: str, level: str) -> None:
        self.cooldowns[self._cooldown_key(symbol, level)] = time.time()

    def _should_send_alert(self, result: Dict[str, Any]) -> tuple[bool, str]:
        if result.get("triggered"):
            return True, "strong"
        if result.get("prealert"):
            return True, "prealert"
        return False, "watch"

    def _build_alert_payload(self, result: Dict[str, Any], level: str) -> Dict[str, Any]:
        send_result = dict(result)
        send_result["alert_level"] = level
        send_result["notify_title"] = "🚨 強信號" if level == "strong" else "⚠️ 預警"
        send_result["notify_text"] = "已達正式反轉條件" if level == "strong" else "接近正式反轉條件，先觀察"
        send_result["status_text"] = "強信號" if level == "strong" else "預警"
        return send_result

    def scan_once(self) -> Dict[str, Any]:
        self._log("scanning top gainers...")

        rows = self.fetch_top_gainers()
        self._log(f"found {len(rows)} gainers to inspect")

        analyzed_rows = []
        alerts_sent = []

        for row in rows:
            self._log(
                f"candidate #{row.get('rank')} {row['symbol']} change={row['change_pct']:.2f}% "
                f"quote_vol={row.get('quote_volume', 0):,.2f}"
            )

            result = self.analyze_symbol(row)
            row["reversal"] = result
            analyzed_rows.append(row)

            should_send, level = self._should_send_alert(result)
            if should_send:
                self._log(
                    f"{level} detected on {row['symbol']} score={result['score']} "
                    f"cooldown_ok={self._can_alert(row['symbol'], level)}"
                )

            if should_send and self._can_alert(row["symbol"], level):
                try:
                    send_result = self._build_alert_payload(result, level)
                    sent = self.notifier.send_reversal_alert(row, send_result)
                    if sent:
                        self._mark_alerted(row["symbol"], level)
                        alert_item = {
                            "symbol": row["symbol"],
                            "change_pct": row["change_pct"],
                            "score": result["score"],
                            "level": level,
                            "time": self._now_str(),
                        }
                        alerts_sent.append(alert_item)
                        self._log(
                            f"discord alert sent: level={level} {row['symbol']} "
                            f"change={row['change_pct']:.2f}% score={result['score']}"
                        )
                    else:
                        self._log(f"discord alert skipped/failed silently: level={level} {row['symbol']}")
                except Exception as exc:
                    error_item = {
                        "symbol": row["symbol"],
                        "change_pct": row["change_pct"],
                        "score": result["score"],
                        "level": level,
                        "time": self._now_str(),
                        "error": str(exc),
                    }
                    alerts_sent.append(error_item)
                    self._log(f"discord alert error for {row['symbol']} level={level}: {exc}")

        with self.lock:
            self.state["last_scan_at"] = self._now_str()
            self.state["scan_count"] += 1
            self.state["market_rows"] = analyzed_rows
            self.state["alerts_sent"] = alerts_sent[:30]
            self.state["last_error"] = ""

            scan_count = self.state["scan_count"]

            self._log(
                f"scan #{scan_count} done | rows={len(analyzed_rows)} alerts={len(alerts_sent)}"
            )

            return dict(self.state)

    def loop_forever(self) -> None:
        with self.lock:
            self.state["running"] = True

        self._log(
            f"loop started | interval={config.SCAN_INTERVAL_SEC}s "
            f"| market_type={config.MARKET_TYPE} | quote={config.QUOTE} "
            f"| min_change={config.MIN_24H_CHANGE_PCT}% | top_n={config.TOP_N} "
            f"| prealert={self._prealert_threshold()} | strong={self._strong_threshold()}"
        )

        while True:
            try:
                self.scan_once()
            except Exception as exc:
                with self.lock:
                    self.state["last_error"] = f"{type(exc).__name__}: {exc}"
                    self.state["last_scan_at"] = self._now_str()

                self._log(f"scan error: {type(exc).__name__}: {exc}")

            time.sleep(config.SCAN_INTERVAL_SEC)

    def start_background(self) -> None:
        if self.worker and self.worker.is_alive():
            self._log("background worker already running")
            return

        self.worker = threading.Thread(
            target=self.loop_forever,
            daemon=True,
            name="bitget-reversal-scanner",
        )
        self.worker.start()
        self._log("background worker thread created")

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.state)
