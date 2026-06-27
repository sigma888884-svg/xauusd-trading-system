"""
app/routes/dashboard.py
=========================
يقدّم بيانات لوحة التحكم: ملخص أداء حقيقي (محسوب مسبقاً من Backtest على بيانات
حقيقية)، بيانات الشارت الأخيرة + الهياكل المكتشفة، لرسم لوحة تحكم مرئية.
"""
import json
import os

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

SUMMARY_PATH = os.path.join("data", "dashboard_summary.json")


@router.get("/summary")
def dashboard_summary():
    """
    ملخص أداء حقيقي محسوب من Backtest على بيانات XAUUSD حقيقية (2022-2026، فريم 15m)
    باستخدام الاستراتيجية المُختبرة (SMC + Kill Zone + Trend Filter + ATR-adaptive SL/TP).
    هذه ليست بيانات Live من السوق، بل نتيجة اختبار تاريخي حقيقي - الفرق مهم ومُعلَن بصدق.
    """
    if not os.path.exists(SUMMARY_PATH):
        raise HTTPException(status_code=404, detail="لم يتم حساب ملخص لوحة التحكم بعد")
    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
