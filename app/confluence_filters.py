"""
confluence_filters.py
=======================
فلاتر توافق (Confluence) مبنية على نصائح موثّقة من مصادر تعليمية جادة في ICT/SMC
(لا تسويقية)، هدفها رفع جودة الإشارة قبل تنفيذها، بدل الاعتماد على هيكل واحد فقط:

1. Kill Zone Filter: قبول الصفقات فقط خلال جلسات لندن/نيويورك النشطة (حيث السيولة
   والحركة المؤسسية الحقيقية أعلى، بدل التداول في ساعات هادئة بلا سبب).
2. Higher-Timeframe Trend Filter: قبول الصفقات فقط المتوافقة مع الاتجاه العام
   (EMA50/EMA200) لتجنب "محاربة" الاتجاه السائد.
3. Multi-Structure Confluence: رفع الثقة فقط عندما تتفق أكثر من إشارة (مثل
   Liquidity Sweep + OB في نفس المنطقة) بدل الاعتماد على هيكل منفرد.
"""
from datetime import datetime, time as dtime
from typing import List, Optional

import pandas as pd

from app.rules_engine import Structure

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range: مقياس تقلب فعلي بالدولار، يُستخدم لتكييف SL/TP مع حالة
    السوق الحالية بدل قيمة ثابتة (مفيد جداً عند مقارنة فترات تقلب مختلفة جداً
    مثل 2015 الهادئة و2024-2026 شديدة التقلب).
    """
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period, min_periods=1).mean()


# جلسات لندن ونيويورك (UTC) - الأكثر نشاطاً للذهب عادة
KILL_ZONES_UTC = [
    (dtime(7, 0), dtime(10, 0)),    # لندن
    (dtime(12, 30), dtime(15, 30)),  # نيويورك
]


def is_in_kill_zone(ts) -> bool:
    """يتحقق إن وقت الشمعة (UTC) يقع داخل جلسة لندن أو نيويورك النشطة."""
    if isinstance(ts, str):
        ts = pd.to_datetime(ts)
    t = ts.time()
    return any(start <= t <= end for start, end in KILL_ZONES_UTC)


def compute_trend_emas(candles: List[dict], fast: int = 50, slow: int = 200) -> pd.DataFrame:
    """يحسب EMA50/EMA200 على كل السلسلة (مرة واحدة، سريع) لاستخدامها كفلتر اتجاه."""
    df = pd.DataFrame(candles)
    df["close"] = df["close"].astype(float)
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    return df


def make_confluence_filter(
    candles: List[dict],
    use_kill_zone: bool = True,
    use_trend_filter: bool = True,
    require_multi_structure: bool = False,
    structures_by_index: Optional[dict] = None,
):
    """
    يبني دالة filter متوافقة مع CandleByCandleBacktester.set_signal_filter().
    تجمع كل الفلاتر المطلوبة في دالة واحدة.
    """
    ema_df = compute_trend_emas(candles) if use_trend_filter else None

    def _filter(structure: Structure, context: dict) -> bool:
        idx = context["index"]

        if use_kill_zone and not is_in_kill_zone(context["time"]):
            return False

        if use_trend_filter and ema_df is not None:
            fast = ema_df.loc[idx, "ema_fast"]
            slow = ema_df.loc[idx, "ema_slow"]
            uptrend = fast > slow
            if structure.direction == "bullish" and not uptrend:
                return False
            if structure.direction == "bearish" and uptrend:
                return False

        if require_multi_structure and structures_by_index is not None:
            # نتحقق: هل توجد إشارة أخرى من نوع مختلف خلال آخر 5 شموع بنفس الاتجاه؟
            window_structs = []
            for j in range(max(0, idx - 5), idx + 1):
                window_structs.extend(structures_by_index.get(j, []))
            same_direction_types = {
                s.type for s in window_structs if s.direction == structure.direction
            }
            if len(same_direction_types) < 2:
                return False

        return True

    return _filter
