"""
app/routes/signals.py
======================
Endpoints متعلقة بالتنبيهات والإشارات (منقولة من main.py لتنظيم أوضح).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Signal
from app.schemas import SignalOut

router = APIRouter(tags=["signals"])


@router.get("/alerts")
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


@router.get("/signals", response_model=List[SignalOut])
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
