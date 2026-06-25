"""
نماذج قاعدة البيانات: التنبيهات الواردة من TradingView، والإشارات المستخرجة منها
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import relationship

from app.database import Base


class Alert(Base):
    """التنبيه الخام كما استُقبل من Webhook الخاص بـ TradingView."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), index=True, default="XAUUSD")
    timeframe = Column(String(10), index=True)
    alert_type = Column(String(50))  # مثال: bos, choch, custom, price_alert
    price = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    raw_payload = Column(JSON)
    processed = Column(Boolean, default=False)

    signals = relationship("Signal", back_populates="alert")


class Signal(Base):
    """إشارة تداول مستخرجة بعد تحليل Rules Engine + تفسير LLM."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    symbol = Column(String(20), index=True)
    timeframe = Column(String(10), index=True)

    signal_type = Column(String(20))   # OB, FVG, BOS, CHoCH
    direction = Column(String(10))     # bullish / bearish

    zone_high = Column(Float, nullable=True)
    zone_low = Column(Float, nullable=True)
    price_level = Column(Float, nullable=True)

    confidence = Column(Float, default=0.5)
    llm_interpretation = Column(Text, nullable=True)
    llm_recommendation = Column(String(20), nullable=True)  # buy/sell/wait

    notified = Column(Boolean, default=False)

    alert = relationship("Alert", back_populates="signals")
