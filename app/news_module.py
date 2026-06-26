"""
news_module.py
================
يربط النظام بمصادر أخبار اقتصادية (NewsAPI) وتقويم اقتصادي، ويسجّلها في قاعدة البيانات،
ويوفّر دالة فلترة بسيطة: "هل نحن قريبون من خبر عالي التأثير الآن؟" تُستخدم لإيقاف/تقليل
التداول قبل وبعد الأخبار القوية.

⚠️ ملاحظتان مهمتان بخصوص هذا الملف:
1. يحتاج مفاتيح API حقيقية (NEWSAPI_KEY) ليعمل فعلياً. بدون مفتاح، يعمل في وضع
   "Fallback" يرجع قائمة فاضية (لا يكسر باقي النظام، فقط لا يعطي تنبيهات أخبار).
2. تكامل Twitter/X API الآن مكلف نسبياً (خطط مدفوعة منذ تغييرات 2023)، فتم وضعه هنا
   كـ placeholder موسّع المهيكلة وقابل للتفعيل لاحقاً بمجرد توفر مفتاح Bearer Token.
"""
import os
from datetime import datetime, timedelta
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import NewsEvent

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
TRADING_ECONOMICS_KEY = os.getenv("TRADING_ECONOMICS_KEY", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

HIGH_IMPACT_KEYWORDS = [
    "fed", "federal reserve", "fomc", "interest rate", "cpi", "inflation",
    "nonfarm payroll", "nfp", "jerome powell", "rate hike", "rate cut",
    "gold", "xauusd", "dollar index", "dxy",
]


async def fetch_newsapi_articles(query: str = "gold OR federal reserve OR inflation", page_size: int = 20) -> List[dict]:
    """يجلب أخبار حديثة من NewsAPI.org (يحتاج NEWSAPI_KEY)."""
    if not NEWSAPI_KEY:
        print("[news_module] NEWSAPI_KEY غير موجود - تخطّي جلب الأخبار (Fallback فاضي).")
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": NEWSAPI_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("articles", [])
    except Exception as e:
        print(f"[news_module] فشل جلب أخبار NewsAPI: {e}")
        return []


async def fetch_economic_calendar(country: str = "united states") -> List[dict]:
    """
    يجلب التقويم الاقتصادي من TradingEconomics (يحتاج TRADING_ECONOMICS_KEY).
    التوثيق الرسمي: https://docs.tradingeconomics.com/economic_calendar/
    """
    if not TRADING_ECONOMICS_KEY:
        print("[news_module] TRADING_ECONOMICS_KEY غير موجود - تخطّي جلب التقويم (Fallback فاضي).")
        return []

    url = f"https://api.tradingeconomics.com/calendar/country/{country}"
    params = {"c": TRADING_ECONOMICS_KEY, "f": "json"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[news_module] فشل جلب التقويم الاقتصادي: {e}")
        return []


async def fetch_twitter_mentions(query: str = "(gold OR XAUUSD OR Fed) lang:en -is:retweet") -> List[dict]:
    """
    Placeholder لمتابعة الأخبار الفورية عبر X (تويتر). يحتاج TWITTER_BEARER_TOKEN
    (خطة Basic/Pro من X API v2 - مدفوعة). بدون مفتاح، يرجع قائمة فاضية.
    """
    if not TWITTER_BEARER_TOKEN:
        print("[news_module] TWITTER_BEARER_TOKEN غير موجود - تخطّي متابعة X (Fallback فاضي).")
        return []

    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    params = {"query": query, "max_results": 20}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json().get("data", [])
    except Exception as e:
        print(f"[news_module] فشل جلب تغريدات X: {e}")
        return []


def classify_impact(title: str) -> str:
    """تصنيف بسيط لأهمية الخبر بناءً على الكلمات المفتاحية في العنوان."""
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["fed", "fomc", "rate hike", "rate cut", "nonfarm payroll", "nfp"]):
        return "high"
    if any(kw in title_lower for kw in HIGH_IMPACT_KEYWORDS):
        return "medium"
    return "low"


def save_news_event(
    title: str,
    event_time: datetime,
    impact: str = "medium",
    country: Optional[str] = None,
    source: str = "newsapi",
    raw_payload: Optional[dict] = None,
) -> NewsEvent:
    db: Session = SessionLocal()
    try:
        event = NewsEvent(
            title=title,
            event_time=event_time,
            impact=impact,
            country=country,
            source=source,
            raw_payload=raw_payload,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    finally:
        db.close()


def is_near_high_impact_news(now: Optional[datetime] = None, buffer_minutes: int = 30) -> bool:
    """
    يتحقق: هل نحن داخل نافذة زمنية قريبة (قبل/بعد) من خبر "high impact" مسجّل في قاعدة البيانات؟
    تُستخدم هذه الدالة كفلتر داخل Rules Engine / Backtester لإيقاف أو تقليل حجم التداول.
    """
    now = now or datetime.utcnow()
    window_start = now - timedelta(minutes=buffer_minutes)
    window_end = now + timedelta(minutes=buffer_minutes)

    db: Session = SessionLocal()
    try:
        count = db.query(NewsEvent).filter(
            NewsEvent.impact == "high",
            NewsEvent.event_time >= window_start,
            NewsEvent.event_time <= window_end,
        ).count()
        return count > 0
    finally:
        db.close()


async def refresh_news_from_sources():
    """دالة تجميعية: تجلب من كل المصادر المفعّلة وتخزّن في قاعدة البيانات. تُستدعى من Cron/Scheduler."""
    articles = await fetch_newsapi_articles()
    saved = 0
    for article in articles:
        title = article.get("title", "")
        published_at = article.get("publishedAt")
        if not title or not published_at:
            continue
        event_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        impact = classify_impact(title)
        save_news_event(title=title, event_time=event_time, impact=impact, source="newsapi", raw_payload=article)
        saved += 1

    print(f"[news_module] تم حفظ {saved} خبر جديد من NewsAPI.")
    return saved
