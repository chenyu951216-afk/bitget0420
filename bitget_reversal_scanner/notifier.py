from __future__ import annotations

from typing import Any, Dict

import requests


class DiscordNotifier:
    def __init__(self, webhook_url: str, username: str = "Bitget Reversal Bot", avatar_url: str = "") -> None:
        self.webhook_url = webhook_url.strip()
        self.username = username.strip() or "Bitget Reversal Bot"
        self.avatar_url = avatar_url.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send_reversal_alert(self, market_row: Dict[str, Any], result: Dict[str, Any]) -> bool:
        if not self.enabled:
            return False

        reasons = result.get("reasons", [])
        reason_text = "\n".join([f"• {item}" for item in reasons]) or "• 觸發綜合反轉條件"
        payload = result.get("payload", {})

        embed = {
            "title": f"⚠️ Bitget 漲幅榜反轉警報：{market_row.get('symbol', '-')}",
            "description": (
                f"24h 漲幅：**{market_row.get('change_pct', 0):.2f}%**\n"
                f"目前排名：**#{market_row.get('rank', '-')}**\n"
                f"反轉分數：**{result.get('score', 0)}**"
            ),
            "fields": [
                {"name": "現價", "value": f"{market_row.get('last', 0):.6f}", "inline": True},
                {"name": "5m RSI", "value": f"{payload.get('rsi14', 0):.2f}", "inline": True},
                {"name": "距離近期高點", "value": f"{payload.get('distance_from_high', 0):.6f}", "inline": True},
                {"name": "條件說明", "value": reason_text[:1000], "inline": False},
                {
                    "name": "技術摘要",
                    "value": (
                        f"EMA9: {payload.get('ema9', 0):.6f}\n"
                        f"EMA21: {payload.get('ema21', 0):.6f}\n"
                        f"15m EMA20: {payload.get('slow_ema20', 0):.6f}\n"
                        f"15m EMA50: {payload.get('slow_ema50', 0):.6f}\n"
                        f"EMA50 乖離: {payload.get('extension_vs_ema50_pct', 0):.2f}%"
                    )[:1000],
                    "inline": False,
                },
            ],
        }

        body = {
            "username": self.username,
            "content": "偵測到高漲幅標的出現疑似反轉，請人工確認。",
            "embeds": [embed],
        }
        if self.avatar_url:
            body["avatar_url"] = self.avatar_url

        response = requests.post(self.webhook_url, json=body, timeout=12)
        response.raise_for_status()
        return True
