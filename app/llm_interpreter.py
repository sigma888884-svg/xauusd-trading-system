"""
وحدة التفسير عبر LLM (Placeholder قابل للتوصيل المباشر).

الهدف: إعطاء LLM سياق الإشارات المكتشفة (OB/FVG/BOS/CHoCH) عبر عدة فريمات،
وطلب تفسير نصي + قرار مقترح (buy / sell / wait) مع درجة ثقة.

استبدل دالة _call_llm_api() بالاستدعاء الحقيقي لمزود الـLLM (Anthropic / OpenAI ...).
"""
import json
from typing import List, Dict, Any
import httpx

from app.config import settings


SYSTEM_PROMPT = """أنت محلل أسواق متخصص في مفاهيم السيولة الذكية (Smart Money Concepts)
لزوج الذهب XAUUSD. ستستلم قائمة إشارات تقنية مكتشفة آلياً (BOS, CHoCH, FVG, OB)
عبر عدة فريمات زمنية. مهمتك:
1. تحديد التوافق (Confluence) بين الفريمات.
2. إعطاء تفسير مختصر بالعربية لما يحدث في السوق.
3. اقتراح قرار: buy / sell / wait مع نسبة ثقة من 0 إلى 1.
أجب بصيغة JSON فقط بالشكل:
{"interpretation": "...", "recommendation": "buy|sell|wait", "confidence": 0.0}
"""


def _build_user_prompt(signals: List[Dict[str, Any]], alert: Dict[str, Any]) -> str:
    return json.dumps({
        "alert": alert,
        "detected_signals": signals,
    }, ensure_ascii=False, default=str)


async def _call_llm_api(system_prompt: str, user_prompt: str) -> dict:
    """
    Placeholder لاستدعاء API الخاص بـLLM (مثال: Anthropic Messages API).
    عدّل الرابط/الهيدرز بحسب المزوّد الذي تستخدمه (LLM_PROVIDER في .env).
    """
    if not settings.LLM_API_KEY:
        # لا يوجد مفتاح API مهيأ -> نعيد قراراً افتراضياً محايداً (Fallback)
        return {
            "interpretation": "لم يتم تفعيل تحليل LLM (LLM_API_KEY غير موجود). "
                               "هذا تفسير افتراضي بناءً على الإشارات الخام فقط.",
            "recommendation": "wait",
            "confidence": 0.3,
        }

    if settings.LLM_PROVIDER == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": settings.LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text"
            )
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"interpretation": text, "recommendation": "wait", "confidence": 0.4}

    # TODO: أضف هنا مزودين آخرين (OpenAI, local model, ...)
    return {
        "interpretation": f"مزود LLM غير مدعوم: {settings.LLM_PROVIDER}",
        "recommendation": "wait",
        "confidence": 0.0,
    }


async def interpret_signals(signals: List[Dict[str, Any]], alert: Dict[str, Any]) -> dict:
    """نقطة الدخول العامة لتفسير الإشارات. تُستدعى من main.py بعد Rules Engine."""
    user_prompt = _build_user_prompt(signals, alert)
    try:
        result = await _call_llm_api(SYSTEM_PROMPT, user_prompt)
    except Exception as e:  # نتجنب كسر التدفق الرئيسي عند فشل LLM
        result = {
            "interpretation": f"تعذّر استدعاء LLM: {e}",
            "recommendation": "wait",
            "confidence": 0.0,
        }
    return result
