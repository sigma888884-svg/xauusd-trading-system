"""
نقطة الدخول الرئيسية لتطبيق FastAPI.

Endpoints أساسية هنا:
- POST /webhook/tradingview   : يستقبل تنبيهات TradingView
- GET  /health                : فحص صحة الخدمة

باقي الـEndpoints منظَّمة في app/routes/:
- /alerts, /signals       -> app/routes/signals.py
- /backtest/run           -> app/routes/backtest.py
- /news, /news/refresh    -> app/routes/news.py
"""
from datetime import datetime
from typing import List

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import Alert, Signal
from app.schemas import WebhookAlert
from app.config import settings
from app.rules_engine import analyze_timeframe, Structure
from app.llm_interpreter import interpret_signals
from app.telegram_bot import send_telegram_message, format_signal_message
from app.routes import signals as signals_routes
from app.routes import backtest as backtest_routes
from app.routes import news as news_routes
from app.routes import dashboard as dashboard_routes


app = FastAPI(
    title="XAUUSD Smart Trading System",
    description="نظام تداول ذكي لزوج الذهب: Webhook + Rules Engine (SMC/ICT) + ML + RL + News + Telegram + Backtester",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # MVP: مفتوح للجميع. للإنتاج الحقيقي حدد دومين الواجهة فقط.
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals_routes.router)
app.include_router(backtest_routes.router)
app.include_router(news_routes.router)
app.include_router(dashboard_routes.router)


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard():
    """يعرض لوحة التحكم المرئية مباشرة على الموقع."""
    return FileResponse("dashboard/index.html")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/webhook/tradingview")
async def tradingview_webhook(payload: WebhookAlert, db: Session = Depends(get_db)):
    """
    يستقبل تنبيه من TradingView (انظر examples/webhook_example.json للصيغة الكاملة).
    التدفق:
    1) التحقق من secret
    2) تخزين التنبيه الخام في قاعدة البيانات
    3) إن وُجدت شموع (candles) -> تشغيل Rules Engine لاكتشاف الهياكل (OB/FVG/BOS/CHoCH/SND/SNR/...)
    4) تمرير الإشارات لـLLM للتفسير + القرار
    5) تخزين الإشارات + إرسال إشعار Telegram
    """
    if payload.secret != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    alert = Alert(
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        alert_type=payload.alert_type,
        price=payload.price,
        message=payload.message,
        raw_payload=payload.model_dump(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    created_signals: List[Signal] = []
    llm_result = {"interpretation": None, "recommendation": None, "confidence": None}

    if payload.candles and len(payload.candles) >= 6:
        structures: List[Structure] = analyze_timeframe(payload.candles)

        signals_dicts = []
        for s in structures[-10:]:
            signals_dicts.append({
                "type": s.type,
                "direction": s.direction,
                "price_level": s.price_level,
                "zone_high": s.zone_high,
                "zone_low": s.zone_low,
                "confidence": s.confidence,
                "timeframe": payload.timeframe,
            })

        if signals_dicts:
            llm_result = await interpret_signals(
                signals_dicts,
                {"symbol": payload.symbol, "timeframe": payload.timeframe, "price": payload.price},
            )

        for s in structures:
            sig = Signal(
                alert_id=alert.id,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                signal_type=s.type,
                direction=s.direction,
                zone_high=s.zone_high,
                zone_low=s.zone_low,
                price_level=s.price_level,
                confidence=s.confidence,
                llm_interpretation=llm_result.get("interpretation"),
                llm_recommendation=llm_result.get("recommendation"),
            )
            db.add(sig)
            created_signals.append(sig)

        db.commit()

        if created_signals:
            last_sig = created_signals[-1]
            text = format_signal_message(
                {"symbol": payload.symbol},
                {
                    "timeframe": last_sig.timeframe,
                    "signal_type": last_sig.signal_type,
                    "direction": last_sig.direction,
                    "price_level": last_sig.price_level,
                    "zone_low": last_sig.zone_low,
                    "zone_high": last_sig.zone_high,
                    "confidence": last_sig.confidence,
                },
                llm_result,
            )
            sent = await send_telegram_message(text)
            last_sig.notified = sent
            db.commit()
    else:
        text = (
            f"📩 تنبيه جديد - {payload.symbol} ({payload.timeframe})\n"
            f"النوع: {payload.alert_type} | السعر: {payload.price}\n"
            f"الرسالة: {payload.message or '-'}"
        )
        await send_telegram_message(text)

    alert.processed = True
    db.commit()

    return {
        "status": "received",
        "alert_id": alert.id,
        "signals_created": len(created_signals),
        "llm_result": llm_result,
    }
