"""
data_loader.py
==============
وحدة مساعدة (Database Helper) للتعامل مع بيانات الأسعار:
- استيراد بيانات من CSV (نتاج data_resampler.py) إلى جدول price_data في Postgres
- قراءة بيانات الأسعار من قاعدة البيانات لفريم/فترة معيّنة (تُستخدم من Backtester وRules Engine)
"""
from datetime import datetime
from typing import Optional, List

import pandas as pd
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PriceData


def import_csv_to_db(csv_path: str, symbol: str, timeframe: str, batch_size: int = 5000) -> int:
    """يستورد ملف CSV (time,open,high,low,close,volume) إلى جدول price_data."""
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    df["time"] = pd.to_datetime(df["time"])

    db: Session = SessionLocal()
    total = 0
    try:
        records = []
        for _, row in df.iterrows():
            records.append(PriceData(
                symbol=symbol,
                timeframe=timeframe,
                time=row["time"].to_pydatetime() if hasattr(row["time"], "to_pydatetime") else row["time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0) or 0),
            ))
            if len(records) >= batch_size:
                db.bulk_save_objects(records)
                db.commit()
                total += len(records)
                records = []
        if records:
            db.bulk_save_objects(records)
            db.commit()
            total += len(records)
    finally:
        db.close()

    return total


def load_price_data(
    symbol: str,
    timeframe: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """يقرأ شموع من قاعدة البيانات ويرجعها كقائمة dict متوافقة مع rules_engine.candles_to_df."""
    db: Session = SessionLocal()
    try:
        q = db.query(PriceData).filter(
            PriceData.symbol == symbol, PriceData.timeframe == timeframe
        )
        if start:
            q = q.filter(PriceData.time >= start)
        if end:
            q = q.filter(PriceData.time <= end)
        q = q.order_by(PriceData.time.asc())
        if limit:
            q = q.limit(limit)

        rows = q.all()
        return [
            {
                "time": r.time.isoformat(),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
    finally:
        db.close()


def load_price_data_csv(csv_path: str) -> List[dict]:
    """بديل سريع: قراءة شموع مباشرة من CSV بدون قاعدة بيانات (مفيد للـBacktester المحلي)."""
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    records = df.to_dict("records")
    for r in records:
        r["time"] = r["time"].isoformat()
    return records
