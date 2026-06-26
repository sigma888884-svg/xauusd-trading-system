# XAUUSD Smart Trading System

> 🔄 **تحديث (المرحلة 2):** تمت إضافة محرك Backtest حقيقي (Candle-by-Candle)،
> Rules Engine موسّع (Liquidity Sweep, Premium/Discount, SND/SNR)، طبقة ML Filter،
> طبقة RL Agent، وحدة أخبار (News + Economic Calendar)، وسكربتات بيانات تاريخية
> كاملة (Dukascopy). راجع قسم "بنية المشروع الكاملة" أسفل الصفحة.


نظام تداول ذكي (MVP) لزوج الذهب XAUUSD يتكوّن من:

1. **Webhook** يستقبل تنبيهات TradingView (JSON).
2. **Rules Engine** يكتشف OB / FVG / BOS / CHoCH على فريمات 1m, 5m, 15m, 1h, 4h.
3. **LLM Interpreter** (placeholder قابل للتوصيل المباشر بـ Anthropic API أو أي مزوّد آخر).
4. **Telegram Bot** لإرسال الإشعارات.
5. **PostgreSQL** لتخزين التنبيهات والإشارات.
6. **Backtester** بسيط لتشغيل الاستراتيجية على بيانات تاريخية (CSV).

> ⚠️ هذا نظام MVP للتعلّم والتجربة، وليس نصيحة مالية. اختبره جيداً (Paper Trading)
> قبل أي استخدام بأموال حقيقية، وراجع قسم "حدود النظام" أدناه.

---

## 1) هيكل المشروع

```
trading_system/
├── app/
│   ├── main.py              # FastAPI app + كل الـEndpoints
│   ├── config.py            # إعدادات (env vars)
│   ├── database.py          # اتصال Postgres + SQLAlchemy
│   ├── models.py            # جداول Alert و Signal
│   ├── schemas.py           # Pydantic schemas (Webhook, Signal, Backtest)
│   ├── rules_engine.py      # اكتشاف OB/FVG/BOS/CHoCH
│   ├── llm_interpreter.py   # استدعاء LLM (placeholder)
│   ├── telegram_bot.py      # إرسال إشعارات Telegram
│   └── backtester.py        # محرك الـBacktest
├── strategies/
│   └── xauusd_smc.yaml      # قالب استراتيجية SMC
├── examples/
│   └── webhook_example.json # مثال تنبيه TradingView
├── data/
│   └── xauusd_1h_sample.csv # بيانات تجريبية للباك تستر
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## 2) التشغيل عبر Docker (الطريقة الموصى بها)

```bash
# 1. انسخ ملف الإعدادات وعدّل القيم (توكن Telegram، مفتاح LLM، السر الخاص بالـWebhook)
cp .env.example .env
nano .env

# 2. بناء وتشغيل الخدمات (FastAPI + Postgres)
docker compose up --build -d

# 3. تأكد أن الخدمة تعمل
curl http://localhost:8000/health
```

التوثيق التفاعلي لـFastAPI (Swagger) متاح على:
`http://localhost:8000/docs`

---

## 3) إعداد التنبيه في TradingView

في إعدادات الـAlert داخل TradingView:

- **Webhook URL**: `http://YOUR_SERVER_IP:8000/webhook/tradingview`
- **Message** (قالب JSON): انظر `examples/webhook_example.json`

مثال مبسّط (Pine Script alert message)، استخدم `{{...}}` لقيم TradingView الديناميكية:

```json
{
  "secret": "changeme",
  "symbol": "XAUUSD",
  "timeframe": "15m",
  "alert_type": "bos",
  "price": {{close}},
  "time": "{{time}}",
  "message": "BOS detected"
}
```

> الحقل `candles` اختياري: إن أرسلت آخر 6 شموع أو أكثر (OHLCV) لكل تنبيه، سيقوم
> Rules Engine بتحليلها مباشرة لاكتشاف OB/FVG/BOS/CHoCH. بدون `candles`، يُسجَّل
> التنبيه ويُرسل إشعار مباشر فقط (تنبيه سعري بسيط بدون تحليل هيكلي).
>
> لتحليل متعدد الفريمات بدقة كاملة، يُفضّل تشغيل مهمة دورية (Cron / APScheduler)
> تجلب الشموع من مزود بيانات (Broker API / Data Feed) لكل فريم وتستدعي
> `app.rules_engine.analyze_multi_timeframe()` مباشرة بدل الاعتماد فقط على الـWebhook.

---

## 4) اختبار الـWebhook يدوياً

```bash
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d @examples/webhook_example.json
```

استعراض النتائج:
```bash
curl http://localhost:8000/alerts
curl http://localhost:8000/signals
```

---

## 5) إعداد بوت Telegram

1. أنشئ بوت عبر [@BotFido](https://t.me/BotFather) واحصل على `TELEGRAM_BOT_TOKEN`.
2. احصل على `chat_id` (راسل البوت ثم زر:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. ضع القيمتين في ملف `.env`.

---

## 6) ربط LLM (Anthropic API كمثال)

في `app/llm_interpreter.py`، الدالة `_call_llm_api()` مهيأة مسبقاً للعمل مع
Anthropic Messages API. كل ما تحتاجه:

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-xxxxxxxx
```

لإضافة مزوّد آخر (OpenAI، نموذج محلي...) عدّل الدالة وأضف فرعاً جديداً بحسب
`settings.LLM_PROVIDER`.

---

## 7) تشغيل الـ Backtester

يحتاج ملف CSV بالأعمدة: `time, open, high, low, close, volume`
(مثال جاهز موجود في `data/xauusd_1h_sample.csv`).

عبر API:
```bash
curl -X POST http://localhost:8000/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_file": "strategies/xauusd_smc.yaml",
    "csv_file": "data/xauusd_1h_sample.csv",
    "initial_balance": 10000,
    "risk_per_trade_pct": 1.0
  }'
```

أو مباشرة في بايثون:
```python
from app.backtester import run_backtest
result = run_backtest(csv_file="data/xauusd_1h_sample.csv")
print(result.win_rate, result.total_pnl, result.max_drawdown)
```

---

## 8) التشغيل المحلي بدون Docker (اختياري، للتطوير)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# يحتاج Postgres محلي أو SQLite للتجربة السريعة:
export DATABASE_URL="sqlite:///./dev.db"
export WEBHOOK_SECRET="changeme"

uvicorn app.main:app --reload
```

---

## 9) قالب الاستراتيجية (YAML)

ملف `strategies/xauusd_smc.yaml` يحدد:
- الفريمات المستخدمة لكل دور (اتجاه عام / تكوين إشارة / دخول دقيق)
- شروط الدخول (نوع الهياكل المطلوبة، الحد الأدنى للثقة)
- إدارة المخاطر (RR ratio، % المخاطرة لكل صفقة، حد أقصى للصفقات اليومية)
- جلسات التداول المفضلة (لندن/نيويورك)
- إعدادات الإشعارات وLLM

يمكنك إنشاء استراتيجيات بديلة بنفس البنية ووضعها في `strategies/` واستخدامها
عبر `strategy_file` في طلب الـBacktest.

---

## 10) حدود النظام (مهم)

- **Rules Engine** هنا تطبيق Heuristic مبسّط لـSMC (Fractals + ATR تقريبي)، وليس
  تطبيقاً معتمداً من مصدر أكاديمي واحد — يحتاج تدقيقاً وتعديلاً حسب أسلوبك.
- **Backtester** لا يحسب Spread/Slippage/Commission بدقة، ويفرض RR ثابت لكل صفقة
  (تبسيط لأغراض الـMVP).
- التحليل متعدد الفريمات (Multi-Timeframe) في الـWebhook يعتمد على إرسال TradingView
  للشموع ضمن كل تنبيه؛ للحصول على تحليل متزامن حقيقي عبر 5 فريمات، الأفضل ربط
  مزود بيانات مباشر (Broker API) بدل الاعتماد الكامل على تنبيهات Pine Script.
- لا تستخدم هذا النظام لتداول حقيقي دون اختبار موسّع (Forward Testing / Paper Trading)
  ومراجعة من شخص مختص بإدارة المخاطر.

---

## بنية المشروع الكاملة (المرحلة 2)

```
trading_system/
├── data_pipeline/
│   ├── data_downloader.py    # تحميل 10 سنوات تِك من Dukascopy (شغّله محليًا، يحتاج إنترنت كامل)
│   ├── data_cleaner.py       # تنظيف التِك (تكرار، توقيت، قفزات شاذة)
│   └── data_resampler.py     # بناء شموع 1m/5m/15m/1h/4h من التِك
├── database_setup.py          # تهيئة كل جداول Postgres دفعة واحدة
├── app/
│   ├── data_loader.py         # استيراد CSV لقاعدة البيانات + قراءة شموع منها
│   ├── rules_engine.py        # BOS/CHoCH/FVG/OB + SND/SNR + Liquidity Sweep + Premium/Discount
│   ├── backtester.py          # محرك Candle-by-Candle: Win Rate, Profit Factor, Expectancy, Max DD
│   ├── ml_filter.py           # تصنيف الإشارات (strong/medium/weak) + تدريب من تاريخ الصفقات
│   ├── rl_agent.py            # Epsilon-Greedy Bandit لتحسين معاملات الاستراتيجية تلقائياً
│   ├── news_module.py         # NewsAPI + Economic Calendar + X (Twitter) placeholder
│   ├── telegram_bot.py        # إشعارات إشارات/صفقات/أخبار/ملخص يومي
│   ├── llm_interpreter.py     # تفسير الإشارات عبر LLM
│   ├── main.py                # FastAPI app + /webhook/tradingview + /health
│   └── routes/
│       ├── signals.py         # /alerts , /signals
│       ├── backtest.py        # /backtest/run
│       └── news.py            # /news , /news/refresh , /news/near-high-impact
```

## خطوات تشغيل المرحلة الجديدة محليًا

### 1) تحميل وتحضير البيانات التاريخية (على جهازك، ليس على سيرفر مقيّد الشبكة)
```bash
pip install -r requirements.txt requests
python data_pipeline/data_downloader.py --years 10 --out data/xauusd_ticks_raw.csv
python data_pipeline/data_cleaner.py --in data/xauusd_ticks_raw.csv --out data/xauusd_ticks_clean.csv
python data_pipeline/data_resampler.py --in data/xauusd_ticks_clean.csv --outdir data/
```
ينتج: `data/xauusd_1m.csv`, `xauusd_5m.csv`, `xauusd_15m.csv`, `xauusd_1h.csv`, `xauusd_4h.csv`

### 2) تهيئة قاعدة البيانات واستيراد البيانات
```bash
python database_setup.py
python -c "from app.data_loader import import_csv_to_db; print(import_csv_to_db('data/xauusd_1h.csv', 'XAUUSD', '1h'))"
```

### 3) تشغيل Backtest الحقيقي
```bash
curl -X POST http://localhost:8000/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"strategy_file": "strategies/xauusd_smc.yaml", "csv_file": "data/xauusd_1h.csv"}'
```
الاستجابة تشمل الآن: `win_rate_pct`, `profit_factor`, `expectancy`, `max_drawdown_pct` (مقاييس حقيقية، لا أرقام مفترضة).

### 4) تحسين المعاملات عبر RL Agent (اختياري)
```python
from app.rl_agent import RLAgent, default_candidate_overrides
from app.backtester import load_strategy, load_csv

strategy = load_strategy("strategies/xauusd_smc.yaml")
candles = load_csv("data/xauusd_1h.csv").to_dict("records")
agent = RLAgent(strategy, default_candidate_overrides())
best = agent.optimize(candles, n_iterations=50)
print(best.config, best.avg_reward)
```

### 5) تدريب ML Filter من تاريخ صفقات حقيقي
```python
from app.ml_filter import MLFilter
ml = MLFilter()
ml.train_from_structures_and_outcomes(structures_list, outcomes_list)  # outcomes: 1=فوز, 0=خسارة
```

### 6) تفعيل الأخبار (اختياري، يحتاج مفاتيح API)
أضف في `.env`:
```
NEWSAPI_KEY=...           # من newsapi.org (خطة مجانية محدودة متاحة)
TRADING_ECONOMICS_KEY=... # من tradingeconomics.com (مدفوع غالباً)
TWITTER_BEARER_TOKEN=...  # من X API (مدفوع منذ 2023)
```
ثم: `POST /news/refresh` لجلب آخر الأخبار وتخزينها.

## ملاحظات صادقة عن هذه المرحلة

- **لا يوجد ضمان نسبة نجاح معيّنة** (89% أو غيرها) — الأرقام الحقيقية تخرج فقط من
  تشغيل Backtester على بيانات حقيقية كافية (10 سنوات)، وهذا يحتاج منك تشغيل
  `data_downloader.py` على جهازك الشخصي أولاً (بيئة الت طوير المقيّدة لا تصل لمصادر
  بيانات مالية خارجية).
- **Twitter/X API** أصبح مدفوعاً منذ 2023، فالكود جاهز للتفعيل لكن يحتاج اشتراك.
- **RL Agent** هنا تصميمه Multi-Armed Bandit بسيط ومُفسَّر (Explainable)، وليس
  Deep RL كامل — قرار متعمّد لتفادي "صندوق أسود" غير موثوق في قرارات مالية.
- **ML Filter** يحتاج 50 صفقة فعلية كحد أدنى للتدريب الجدّي؛ قبل ذلك يعمل بقاعدة
  احتياطية (Fallback) مبنية على درجة ثقة Rules Engine فقط.
