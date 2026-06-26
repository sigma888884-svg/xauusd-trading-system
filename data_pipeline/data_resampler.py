"""
data_resampler.py
==================
يبني شموع OHLCV من بيانات التِك المنظّفة (mid price)، لفريمات متعددة:
1m, 5m, 15m, 1h, 4h

الاستخدام:
    python data_resampler.py --in data/xauusd_ticks_clean.csv --outdir data/

يولّد:
    data/xauusd_1m.csv
    data/xauusd_5m.csv
    data/xauusd_15m.csv
    data/xauusd_1h.csv
    data/xauusd_4h.csv
"""
import argparse
import os
import pandas as pd

TIMEFRAMES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
}


def build_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df = df.set_index("time")
    ohlc = df["mid"].resample(rule).ohlc()
    volume = (df.get("bid_volume", 0) + df.get("ask_volume", 0)).resample(rule).sum() \
        if "bid_volume" in df.columns else pd.Series(0, index=ohlc.index)

    out = ohlc.copy()
    out["volume"] = volume
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out.reset_index()
    return out


def main():
    parser = argparse.ArgumentParser(description="بناء فريمات OHLCV من بيانات التِك")
    parser.add_argument("--in", dest="in_path", required=True, help="مسار ملف التِك المنظّف")
    parser.add_argument("--outdir", dest="outdir", default="data/", help="مجلد حفظ ملفات الفريمات")
    args = parser.parse_args()

    print(f"قراءة بيانات التِك: {args.in_path}")
    df = pd.read_csv(args.in_path)
    df["time"] = pd.to_datetime(df["time"], utc=True)

    os.makedirs(args.outdir, exist_ok=True)

    for tf_name, rule in TIMEFRAMES.items():
        print(f"بناء فريم {tf_name} ...")
        ohlcv = build_ohlcv(df, rule)
        out_path = os.path.join(args.outdir, f"xauusd_{tf_name}.csv")
        ohlcv.to_csv(out_path, index=False)
        print(f"  -> {len(ohlcv):,} شمعة، حُفظ في {out_path}")

    print("\n✅ انتهى بناء جميع الفريمات.")


if __name__ == "__main__":
    main()
