"""
إرسال إشعارات عبر Telegram Bot API (بدون مكتبة خارجية إضافية - httpx فقط).
"""
import httpx
from app.config import settings


async def send_telegram_message(text: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        print("[telegram_bot] لم يتم ضبط TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID - تم تجاهل الإرسال.")
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[telegram_bot] فشل إرسال الإشعار: {e}")
        return False


def format_signal_message(alert: dict, signal: dict, llm_result: dict) -> str:
    emoji = "🟢" if signal.get("direction") == "bullish" else "🔴"
    return (
        f"{emoji} <b>إشارة جديدة - {alert.get('symbol', 'XAUUSD')}</b>\n"
        f"الفريم: <b>{signal.get('timeframe')}</b>\n"
        f"النوع: <b>{signal.get('signal_type')}</b> | الاتجاه: <b>{signal.get('direction')}</b>\n"
        f"السعر: <code>{signal.get('price_level')}</code>\n"
        f"المنطقة: {signal.get('zone_low')} - {signal.get('zone_high')}\n"
        f"الثقة: {signal.get('confidence')}\n\n"
        f"🤖 <b>تفسير LLM:</b>\n{llm_result.get('interpretation')}\n"
        f"القرار المقترح: <b>{llm_result.get('recommendation')}</b> "
        f"(ثقة: {llm_result.get('confidence')})"
    )
