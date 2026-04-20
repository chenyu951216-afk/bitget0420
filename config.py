import os


def env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


APP_HOST = env_str("APP_HOST", "0.0.0.0")
APP_PORT = env_int("PORT", 8080)
DEBUG = env_str("DEBUG", "false").lower() == "true"

# Bitget market selection
MARKET_TYPE = env_str("MARKET_TYPE", "swap")  # swap / spot
QUOTE = env_str("QUOTE", "USDT")
TOP_N = env_int("TOP_N", 10)
MIN_24H_CHANGE_PCT = env_float("MIN_24H_CHANGE_PCT", 30.0)
SCAN_INTERVAL_SEC = max(env_int("SCAN_INTERVAL_SEC", 60), 20)
ALERT_COOLDOWN_SEC = max(env_int("ALERT_COOLDOWN_SEC", 1800), 300)

# Reversal model
FAST_TIMEFRAME = env_str("FAST_TIMEFRAME", "5m")
SLOW_TIMEFRAME = env_str("SLOW_TIMEFRAME", "15m")
OHLCV_LIMIT_FAST = max(env_int("OHLCV_LIMIT_FAST", 180), 80)
OHLCV_LIMIT_SLOW = max(env_int("OHLCV_LIMIT_SLOW", 180), 80)
RSI_OVERBOUGHT = env_float("RSI_OVERBOUGHT", 78.0)
RSI_EXIT = env_float("RSI_EXIT", 70.0)
MIN_WICK_BODY_RATIO = env_float("MIN_WICK_BODY_RATIO", 1.2)
NEAR_HIGH_LOOKBACK = max(env_int("NEAR_HIGH_LOOKBACK", 20), 10)
NEAR_HIGH_ATR_RATIO = env_float("NEAR_HIGH_ATR_RATIO", 0.8)
MIN_REVERSAL_SCORE = env_int("MIN_REVERSAL_SCORE", 4)

DISCORD_WEBHOOK_URL = env_str("DISCORD_WEBHOOK_URL", "")
DISCORD_USERNAME = env_str("DISCORD_USERNAME", "Bitget Reversal Bot")
DISCORD_AVATAR_URL = env_str("DISCORD_AVATAR_URL", "")

TZ_NAME = env_str("TZ_NAME", "Asia/Taipei")
