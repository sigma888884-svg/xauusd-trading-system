"""
data_downloader.py
====================
يحمّل بيانات تاريخية لزوج XAUUSD (1 دقيقة) من Dukascopy (مصدر مجاني).

⚠️ مهم جدًا: هذا السكربت يحتاج اتصال إنترنت كامل بدون قيود، لذلك يجب تشغيله
على جهازك الشخصي (لابتوب/سيرفر VPS) — لن يعمل داخل بيئة Sandbox مقيّدة الشبكة.

طريقة عمل Dukascopy:
- بيانات الـTick/1m تُخزَّن في ملفات .bi5 مقسّمة بالساعة، على شكل:
  https://datafeed.dukascopy.com/datafeed/XAUUSD/{year}/{month}/{day}/{hour}h_ticks.bi5
- نتحقق كل ساعة على مدى السنوات المطلوبة، ونحمّل ونفك الضغط (LZMA) ونحوّل لـCSV.

الاستخدام:
    pip install -r requirements.txt
    python data_downloader.py --years 10 --out data/xauusd_1m_raw.csv

يولّد ملف CSV بالأعمدة: time, bid, ask, bid_volume, ask_volume
(نحولها بعدين لـOHLCV عبر data_resampler.py)
"""
import argparse
import struct
import lzma
import io
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd

BASE_URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
# نقطة السعر لـXAUUSD في صيغة Dukascopy = 1/100 (point value)؛ راجع توثيق الأداة لو تغيّر
POINT_VALUE = 0.001


def fetch_hour(dt: datetime) -> pd.DataFrame:
    """يحمّل ساعة واحدة من بيانات التِك (.bi5) ويرجعها كـDataFrame، أو DataFrame فاضي لو الساعة بدون بيانات."""
    url = f"{BASE_URL}/{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200 or len(resp.content) == 0:
            return pd.DataFrame()
        raw = lzma.decompress(resp.content)
    except Exception:
        return pd.DataFrame()

    rows = []
    record_size = 20  # كل تِك = 20 بايت: (ms_offset, ask, bid, ask_vol, bid_vol) كأعداد big-endian
    n_records = len(raw) // record_size
    for i in range(n_records):
        chunk = raw[i * record_size:(i + 1) * record_size]
        ms_offset, ask, bid, ask_vol, bid_vol = struct.unpack(">IIIff", chunk)
        tick_time = dt + timedelta(milliseconds=ms_offset)
        rows.append({
            "time": tick_time,
            "bid": bid * POINT_VALUE,
            "ask": ask * POINT_VALUE,
            "bid_volume": bid_vol,
            "ask_volume": ask_vol,
        })
    return pd.DataFrame(rows)


def download_range(start: datetime, end: datetime, out_path: str):
    """يمر ساعة بساعة بين start وend، ويكتب كل ساعة في CSV تراكمي (append) لتقليل استهلاك الذاكرة."""
    current = start
    first_write = True
    total_ticks = 0

    while current < end:
        df = fetch_hour(current)
        if not df.empty:
            df.to_csv(out_path, mode="a", header=first_write, index=False)
            first_write = False
            total_ticks += len(df)
            print(f"[{current.isoformat()}] +{len(df)} ticks (إجمالي: {total_ticks})")
        current += timedelta(hours=1)

    print(f"\n✅ انتهى التحميل. إجمالي التِكّات: {total_ticks}. الملف: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="تحميل بيانات XAUUSD التاريخية من Dukascopy")
    parser.add_argument("--years", type=int, default=10, help="عدد السنوات المطلوبة للخلف")
    parser.add_argument("--out", type=str, default="data/xauusd_ticks_raw.csv", help="مسار ملف الخروج")
    args = parser.parse_args()

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=365 * args.years)

    print(f"بدء التحميل من {start.isoformat()} إلى {end.isoformat()}")
    print("⚠️ هذا قد يأخذ ساعات حسب سرعة الإنترنت (عدة آلاف من الطلبات لكل ساعة في 10 سنوات).")
    download_range(start, end, args.out)


if __name__ == "__main__":
    main()
