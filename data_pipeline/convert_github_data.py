"""
convert_github_data.py
========================
يحوّل ملفات XAUUSD الخام من مستودع ejtraderLabs/historical-data (نطاق نوفمبر 2012
إلى مارس 2022، حقيقية وليست تجريبية) إلى صيغة CSV القياسية المستخدمة في باقي النظام:
time, open, high, low, close, volume

ملاحظة مهمة: القيم الخام مضروبة بـ100 (صيغة نقطة سعر شائعة عند بعض المزوّدين)،
لذلك نقسمها على 100 لتصبح أسعار حقيقية (مثال: 196974.0 -> 1969.74 دولار، وهو سعر
ذهب منطقي جداً لتاريخ مارس 2022).
"""
import pandas as pd
import os

MAPPING = {
    "d1": "1d",
    "h4": "4h",
    "h1": "1h",
    "m30": "30m",
    "m15": "15m",
}

SCALE = 100.0  # القيم الخام = السعر الحقيقي × 100


def convert(raw_path: str, out_path: str):
    df = pd.read_csv(raw_path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={"date": "time", "tick_volume": "volume"})

    df["time"] = pd.to_datetime(df["time"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float) / SCALE

    df = df[["time", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("time").drop_duplicates(subset=["time"]).reset_index(drop=True)
    df.to_csv(out_path, index=False)
    return df


def main():
    os.makedirs("data", exist_ok=True)
    for raw_tf, out_tf in MAPPING.items():
        raw_path = f"data/raw_github/XAUUSD{raw_tf}.csv"
        out_path = f"data/xauusd_{out_tf}.csv"
        if not os.path.exists(raw_path):
            print(f"⚠️ غير موجود: {raw_path}")
            continue
        df = convert(raw_path, out_path)
        print(f"✅ {out_tf}: {len(df):,} شمعة حقيقية | من {df['time'].min()} إلى {df['time'].max()} "
              f"-> {out_path}")


if __name__ == "__main__":
    main()
