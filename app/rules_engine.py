"""
Rules Engine لاكتشاف هياكل السوق (Smart Money Concepts) على بيانات OHLCV:

- Swing Highs / Swing Lows (Fractals)
- BOS   (Break of Structure)      -> استمرار الاتجاه
- CHoCH (Change of Character)     -> احتمال انعكاس الاتجاه
- FVG   (Fair Value Gap)          -> فجوة سيولة بين 3 شموع
- OB    (Order Block)             -> آخر شمعة معاكسة قبل حركة اندفاعية قوية

هذا تطبيق مبسّط (Heuristic) مناسب لـMVP، ويمكن تطويره لاحقاً بخوارزميات أدق.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Literal
import pandas as pd
import numpy as np

Direction = Literal["bullish", "bearish"]


@dataclass
class Structure:
    type: str                 # "BOS" | "CHoCH" | "FVG" | "OB"
    direction: Direction
    index: int                # index الشمعة المرتبطة بالحدث
    price_level: float
    zone_high: Optional[float] = None
    zone_low: Optional[float] = None
    confidence: float = 0.5
    meta: dict = field(default_factory=dict)


def candles_to_df(candles: list) -> pd.DataFrame:
    """يحوّل قائمة Candle (pydantic أو dict) إلى DataFrame مرتب زمنياً."""
    rows = []
    for c in candles:
        if hasattr(c, "model_dump"):
            c = c.model_dump()
        rows.append(c)
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df


def find_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """
    يحدد القمم والقيعان السوينغ (Fractals) باستخدام نافذة متجاورة.
    يضيف أعمدة: swing_high (bool), swing_low (bool)
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)

    for i in range(left, n - right):
        window_high = highs[i - left: i + right + 1]
        window_low = lows[i - left: i + right + 1]
        if highs[i] == window_high.max() and np.argmax(window_high) == left:
            swing_high[i] = True
        if lows[i] == window_low.min() and np.argmin(window_low) == left:
            swing_low[i] = True

    df = df.copy()
    df["swing_high"] = swing_high
    df["swing_low"] = swing_low
    return df


def detect_bos_choch(df: pd.DataFrame) -> List[Structure]:
    """
    يكتشف BOS و CHoCH بالاعتماد على تسلسل القمم/القيعان السوينغ:
    - اتجاه صاعد مفترض إذا كانت آخر قيعان متصاعدة (Higher Lows)
    - BOS صاعد: كسر آخر قمة سوينغ أثناء اتجاه صاعد (استمرار)
    - CHoCH هابط: كسر آخر قاع سوينغ أثناء اتجاه صاعد (انعكاس محتمل)
    - والعكس للاتجاه الهابط
    """
    df = find_swings(df)
    structures: List[Structure] = []

    swing_highs = df[df["swing_high"]][["high"]].copy()
    swing_lows = df[df["swing_low"]][["low"]].copy()

    trend: Optional[Direction] = None
    last_swing_high = None
    last_swing_low = None

    for i in range(len(df)):
        close = df.loc[i, "close"]

        if df.loc[i, "swing_high"]:
            last_swing_high = df.loc[i, "high"]
        if df.loc[i, "swing_low"]:
            last_swing_low = df.loc[i, "low"]

        if last_swing_high is not None and close > last_swing_high:
            if trend == "bearish":
                structures.append(Structure(
                    type="CHoCH", direction="bullish", index=i,
                    price_level=close, confidence=0.65,
                    meta={"broken_level": last_swing_high},
                ))
                trend = "bullish"
            elif trend != "bullish":
                structures.append(Structure(
                    type="BOS", direction="bullish", index=i,
                    price_level=close, confidence=0.55,
                    meta={"broken_level": last_swing_high},
                ))
                trend = "bullish"
            else:
                structures.append(Structure(
                    type="BOS", direction="bullish", index=i,
                    price_level=close, confidence=0.5,
                    meta={"broken_level": last_swing_high},
                ))
            last_swing_high = None  # تجنّب تكرار نفس الكسر

        if last_swing_low is not None and close < last_swing_low:
            if trend == "bullish":
                structures.append(Structure(
                    type="CHoCH", direction="bearish", index=i,
                    price_level=close, confidence=0.65,
                    meta={"broken_level": last_swing_low},
                ))
                trend = "bearish"
            elif trend != "bearish":
                structures.append(Structure(
                    type="BOS", direction="bearish", index=i,
                    price_level=close, confidence=0.55,
                    meta={"broken_level": last_swing_low},
                ))
                trend = "bearish"
            else:
                structures.append(Structure(
                    type="BOS", direction="bearish", index=i,
                    price_level=close, confidence=0.5,
                    meta={"broken_level": last_swing_low},
                ))
            last_swing_low = None

    return structures


def detect_fvg(df: pd.DataFrame) -> List[Structure]:
    """
    Fair Value Gap عبر 3 شموع متتالية (i-2, i-1, i):
    - فجوة صاعدة:  high[i-2] < low[i]   => فجوة بين الشمعتين الطرفيتين
    - فجوة هابطة:  low[i-2]  > high[i]
    """
    structures = []
    n = len(df)
    for i in range(2, n):
        h0, l0 = df.loc[i - 2, "high"], df.loc[i - 2, "low"]
        h2, l2 = df.loc[i, "high"], df.loc[i, "low"]

        if h0 < l2:
            structures.append(Structure(
                type="FVG", direction="bullish", index=i,
                price_level=(h0 + l2) / 2,
                zone_high=l2, zone_low=h0,
                confidence=0.5,
            ))
        elif l0 > h2:
            structures.append(Structure(
                type="FVG", direction="bearish", index=i,
                price_level=(l0 + h2) / 2,
                zone_high=l0, zone_low=h2,
                confidence=0.5,
            ))
    return structures


def detect_order_blocks(df: pd.DataFrame, impulse_atr_mult: float = 1.5) -> List[Structure]:
    """
    Order Block مبسّط:
    آخر شمعة معاكسة (هابطة) قبل حركة اندفاعية صاعدة قوية = OB صاعد، والعكس صحيح.
    "قوية" تُقاس بمضاعف لـATR التقريبي (مدى الشموع الأخيرة).
    """
    structures = []
    n = len(df)
    if n < 5:
        return structures

    df = df.copy()
    df["range"] = df["high"] - df["low"]
    atr = df["range"].rolling(window=10, min_periods=3).mean()

    for i in range(1, n):
        body = abs(df.loc[i, "close"] - df.loc[i, "open"])
        is_impulsive = body >= impulse_atr_mult * (atr[i] if not np.isnan(atr[i]) else df.loc[i, "range"])
        if not is_impulsive:
            continue

        bullish_impulse = df.loc[i, "close"] > df.loc[i, "open"]
        prev = df.loc[i - 1]
        prev_is_bearish = prev["close"] < prev["open"]
        prev_is_bullish = prev["close"] > prev["open"]

        if bullish_impulse and prev_is_bearish:
            structures.append(Structure(
                type="OB", direction="bullish", index=i - 1,
                price_level=(prev["open"] + prev["close"]) / 2,
                zone_high=prev["high"], zone_low=prev["low"],
                confidence=0.6,
            ))
        elif (not bullish_impulse) and prev_is_bullish:
            structures.append(Structure(
                type="OB", direction="bearish", index=i - 1,
                price_level=(prev["open"] + prev["close"]) / 2,
                zone_high=prev["high"], zone_low=prev["low"],
                confidence=0.6,
            ))
    return structures


def analyze_timeframe(candles: list) -> List[Structure]:
    """
    نقطة الدخول الرئيسية: تحلل قائمة شموع فريم واحد وتُرجع كل الهياكل المكتشفة
    (BOS, CHoCH, FVG, OB) مرتبة بترتيب ظهورها.
    """
    if not candles or len(candles) < 6:
        return []

    df = candles_to_df(candles)

    structures: List[Structure] = []
    structures += detect_bos_choch(df)
    structures += detect_fvg(df)
    structures += detect_order_blocks(df)

    structures.sort(key=lambda s: s.index)
    return structures


def analyze_multi_timeframe(candles_by_tf: dict) -> dict:
    """
    candles_by_tf: {"1m": [...], "5m": [...], "15m": [...], "1h": [...], "4h": [...]}
    يُرجع dict من نفس المفاتيح، كل قيمة = قائمة Structure
    """
    return {tf: analyze_timeframe(c) for tf, c in candles_by_tf.items()}
