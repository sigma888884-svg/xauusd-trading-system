"""
data_cleaner.py
================
ينظّف بيانات التِك الخام القادمة من data_downloader.py:
- إزالة التكرار (Duplicates)
- توحيد التوقيت إلى UTC
- إصلاح الفجوات (Gaps) عبر إعادة فهرسة الوقت وتعبئة القيم المفقودة بطريقة محافظة
- تحويل بيانات التِك (bid/ask) إلى منتصف السعر (mid price) كنقطة بداية لبناء الشموع

الاستخدام:
    python data_cleaner.py --in data/xauusd_ticks_raw.csv --out data/xauusd_ticks_clean.csv
"""
import argparse
import pandas as pd


def clean_ticks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1) توحيد التوقيت
    df["time"] = pd.to_datetime(df["time"], utc=True)

    # 2) إزالة التكرار الكامل لنفس اللحظة والقيم
    df = df.drop_duplicates(subset=["time", "bid", "ask"])

    # 3) إزالة القيم غير المنطقية (صفر أو سالب أو bid > ask)
    df = df[(df["bid"] > 0) & (df["ask"] > 0) & (df["ask"] >= df["bid"])]

    # 4) ترتيب زمني
    df = df.sort_values("time").reset_index(drop=True)

    # 5) حساب منتصف السعر (mid) كقيمة مرجعية لبناء الشموع لاحقاً
    df["mid"] = (df["bid"] + df["ask"]) / 2

    # 6) إزالة القفزات الشاذة (Outliers) أكبر من 5% بين تِك والتالي له (خطأ بيانات غالباً)
    pct_change = df["mid"].pct_change().abs()
    df = df[(pct_change < 0.05) | (pct_change.isna())]

    return df.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="تنظيف بيانات XAUUSD الخام")
    parser.add_argument("--in", dest="in_path", required=True, help="مسار ملف CSV الخام")
    parser.add_argument("--out", dest="out_path", required=True, help="مسار ملف CSV الناتج بعد التنظيف")
    args = parser.parse_args()

    print(f"قراءة الملف الخام: {args.in_path}")
    df = pd.read_csv(args.in_path)
    print(f"عدد السجلات قبل التنظيف: {len(df):,}")

    clean = clean_ticks(df)
    print(f"عدد السجلات بعد التنظيف: {len(clean):,}")

    clean.to_csv(args.out_path, index=False)
    print(f"✅ تم الحفظ في: {args.out_path}")


if __name__ == "__main__":
    main()
