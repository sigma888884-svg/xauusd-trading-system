"""
database_setup.py
==================
سكربت مستقل لتهيئة قاعدة بيانات Postgres وإنشاء كل الجداول المطلوبة:
price_data, signals, alerts, trades, news_events

الاستخدام:
    python database_setup.py
(يعتمد على متغير البيئة DATABASE_URL، نفس المستخدم في app/config.py)
"""
from app.database import init_db, engine
from app import models  # noqa: F401  (يضمن تسجيل كل النماذج قبل create_all)


def main():
    print(f"الاتصال بقاعدة البيانات: {engine.url}")
    init_db()
    print("✅ تم إنشاء/تحديث كل الجداول بنجاح:")
    for table in models.Base.metadata.tables.keys():
        print(f"  - {table}")


if __name__ == "__main__":
    main()
