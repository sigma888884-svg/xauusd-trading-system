"""
إعدادات التطبيق - تُقرأ من متغيرات البيئة (Environment Variables)
"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://trader:traderpass@localhost:5432/xauusd_trading",
    )

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")

    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "changeme")

    SYMBOL: str = "XAUUSD"
    TIMEFRAMES: list = ["1m", "5m", "15m", "1h", "4h"]

    class Config:
        env_file = ".env"


settings = Settings()
