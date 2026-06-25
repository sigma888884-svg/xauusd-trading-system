"""
نقطة الدخول الرئيسية لتطبيق FastAPI.

Endpoints:
- POST /webhook/tradingview   : يستقبل تنبيهات TradingView
- GET  /alerts                : عرض آخر التنبيهات المخزنة
- GET  /signals                : عرض آخر الإشارات المكتشفة
- POST /backtest/run          : تشغيل Backtest على بيانات تاريخية (CSV)
- GET  /health                : فحص صحة الخدمة
"""
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import Alert, Signal
from app.schemas import WebhookAlert, SignalOut, BacktestRequest
from app.config import settings
from app.rules_engine import analyze_timeframe, Structure
from app.llm_interpreter import interpret_signals
from app.telegram_bot import send_telegram_message, format_signal_message
from app.backtester import run_backtest


app = FastAPI(
    title="XAUUSD Smart Trading System (MVP)",
    description="نظام تداول ذكي MVP لزوج الذهب: Webhook + Rules Engine + LLM + Telegram + Backtester",
    version="0.1.0",
)


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
    3) إن وُجدت شموع (candles) -> تشغيل Rules Engine لاكتشاف OB/FVG/BOS/CHoCH
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
        for s in structures[-10:]:  # نأخذ آخر 10 هياكل لتفسير مركّز
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

        # إرسال إشعار Telegram لآخر إشارة فقط (الأهم) لتجنب الإسبام
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
        # تنبيه بدون شموع: مجرد تسجيل + إشعار مبسط (مثلاً تنبيه سعري من Pine Script)
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


@app.get("/alerts")
def list_alerts(limit: int = 20, db: Session = Depends(get_db)):
    alerts = db.query(Alert).order_by(Alert.received_at.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "received_at": a.received_at,
            "symbol": a.symbol,
            "timeframe": a.timeframe,
            "alert_type": a.alert_type,
            "price": a.price,
            "processed": a.processed,
        }
        for a in alerts
    ]


@app.get("/signals", response_model=List[SignalOut])
def list_signals(
    limit: int = 20,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Signal)
    if symbol:
        q = q.filter(Signal.symbol == symbol)
    if timeframe:
        q = q.filter(Signal.timeframe == timeframe)
    return q.order_by(Signal.created_at.desc()).limit(limit).all()


@app.post("/backtest/run")
def backtest_run(req: BacktestRequest):
    """
    يشغّل الـBacktester على ملف CSV تاريخي (أعمدة: time,open,high,low,close,volume).
    مثال: POST /backtest/run
    {"strategy_file": "strategies/xauusd_smc.yaml", "csv_file": "data/xauusd_1h.csv"}
    """
    try:
        result = run_backtest(
            csv_file=req.csv_file,
            strategy_file=req.strategy_file,
            initial_balance=req.initial_balance,
            risk_per_trade_pct=req.risk_per_trade_pct,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "final_balance": result.final_balance,
        "total_trades": len(result.trades),
        "win_rate_pct": result.win_rate,
        "total_pnl": result.total_pnl,
        "max_drawdown_pct": result.max_drawdown,
    }
