"""
app/routes/news.py
====================
Endpoints لعرض/تحديث الأخبار والتقويم الاقتصادي.
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NewsEvent
from app.news_module import refresh_news_from_sources, is_near_high_impact_news

router = APIRouter(prefix="/news", tags=["news"])


@router.get("")
def list_news(limit: int = 20, impact: str = None, db: Session = Depends(get_db)):
    q = db.query(NewsEvent)
    if impact:
        q = q.filter(NewsEvent.impact == impact)
    events = q.order_by(NewsEvent.event_time.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "title": e.title,
            "event_time": e.event_time,
            "impact": e.impact,
            "country": e.country,
            "source": e.source,
        }
        for e in events
    ]


@router.post("/refresh")
async def refresh_news():
    """يجلب أخبار جديدة من المصادر المفعّلة (NewsAPI) ويخزّنها. يحتاج NEWSAPI_KEY في env."""
    saved = await refresh_news_from_sources()
    return {"status": "ok", "saved": saved}


@router.get("/near-high-impact")
def near_high_impact(buffer_minutes: int = 30):
    """هل نحن داخل نافذة قريبة من خبر عالي التأثير؟ (تُستخدم كفلتر تداول)."""
    near = is_near_high_impact_news(buffer_minutes=buffer_minutes)
    return {"near_high_impact_news": near, "buffer_minutes": buffer_minutes}
