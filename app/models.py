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


class PriceData(Base):
    """شموع OHLCV التاريخية لكل فريم (تُعبّأ من data_pipeline أو من السوق الحي)."""
    __tablename__ = "price_data"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, default="XAUUSD")
    timeframe = Column(String(10), index=True)
    time = Column(DateTime, index=True)

    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float, default=0.0)

    __table_args__ = (
        # فهرس مركّب لتسريع الاستعلامات الشائعة (رمز + فريم + وقت)
        # SQLAlchemy ينشئه تلقائياً عبر Index في حال الحاجة لاحقاً
    )


class Trade(Base):
    """الصفقات المنفّذة (حقيقية أو من Backtester)."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)

    symbol = Column(String(20), index=True, default="XAUUSD")
    timeframe = Column(String(10))
    direction = Column(String(10))          # bullish / bearish

    entry_time = Column(DateTime, index=True)
    entry_price = Column(Float)
    sl = Column(Float)
    tp = Column(Float)

    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    result = Column(String(10), nullable=True)   # win / loss / open
    pnl = Column(Float, default=0.0)

    source = Column(String(20), default="backtest")  # backtest / live
    ml_score = Column(Float, nullable=True)           # تقييم ML للإشارة وقت الدخول
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsEvent(Base):
    """أخبار/أحداث اقتصادية مهمة، تُستخدم كفلتر في Rules Engine وBacktester."""
    __tablename__ = "news_events"

    id = Column(Integer, primary_key=True, index=True)
    event_time = Column(DateTime, index=True)
    title = Column(String(255))
    country = Column(String(10), nullable=True)
    impact = Column(String(10), default="medium")   # low / medium / high
    actual = Column(String(50), nullable=True)
    forecast = Column(String(50), nullable=True)
    previous = Column(String(50), nullable=True)
    source = Column(String(50), default="manual")   # newsapi / trading_economics / manual
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
