"""
مخططات Pydantic للتحقق من بيانات الـWebhook والاستجابات
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Candle(BaseModel):
    """شمعة OHLCV واحدة."""
    time: str                 # ISO timestamp
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = 0.0


class WebhookAlert(BaseModel):
    """
    صيغة JSON المتوقعة القادمة من TradingView Alert.
    تُرسل عادة عبر "Webhook URL" في إعدادات التنبيه، والـmessage
    يُولّد من قالب Pine Script (انظر مثال JSON في examples/webhook_example.json)
    """
    secret: str = Field(..., description="مفتاح سري للتحقق من مصدر التنبيه")
    symbol: str = "XAUUSD"
    timeframe: str                       # "1m" | "5m" | "15m" | "1h" | "4h"
    alert_type: str                      # bos | choch | ob | fvg | custom
    price: float
    time: Optional[str] = None
    message: Optional[str] = None
    candles: Optional[List[Candle]] = None   # آخر N شمعة لتحليل OB/FVG (اختياري)
    extra: Optional[Dict[str, Any]] = None


class SignalOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    signal_type: str
    direction: Optional[str]
    zone_high: Optional[float]
    zone_low: Optional[float]
    price_level: Optional[float]
    confidence: float
    llm_interpretation: Optional[str]
    llm_recommendation: Optional[str]

    class Config:
        from_attributes = True


class BacktestRequest(BaseModel):
    strategy_file: str = "strategies/xauusd_smc.yaml"
    csv_file: str       # مسار ملف CSV يحتوي بيانات OHLCV تاريخية
    initial_balance: float = 10000.0
    risk_per_trade_pct: float = 1.0
