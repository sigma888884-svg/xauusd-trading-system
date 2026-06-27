"""
discipline_engine.py
======================
طبقة "انضباط نفسي" برمجية للنظام، تُطبّق مبادئ معروفة في علم نفس التداول
(الأكثر شهرة في كتب مثل "Trading in the Zone" لـMark Douglas) ليس كنص يُقرأ،
بل كـقواعد سلوكية فعلية تتحكم في كيفية تفاعل النظام مع نتائج صفقاته.

المبادئ المُطبَّقة هنا (بصياغتنا، مش نقل حرفي من أي كتاب):

1. التفكير الاحتمالي (Probabilistic Thinking):
   لا نحكم على جودة نوع إشارة معيّن من 3-5 صفقات فقط؛ نحتاج عينة كافية
   (MIN_SAMPLE_SIZE) قبل اعتبار أي نمط "موثوق" أو "فاشل".

2. تقبّل المخاطرة الكامل قبل الدخول (Risk Acceptance):
   حجم كل صفقة وSL محدد ومثبت *قبل* الدخول، ولا يتغيّر بعد الدخول بناءً
   على "مشاعر" أثناء الصفقة (لا تحريك SL هربًا من الخسارة).

3. الانضباط بعد الخسارة (No Revenge Trading):
   بعد سلسلة خسائر متتالية، النظام "يبرد" تلقائيًا (Cooldown) بدل مضاعفة
   حجم الصفقة أو الدخول بعصبية لتعويض الخسارة.

4. الانضباط بعد الربح (No Overconfidence):
   سلسلة أرباح متتالية لا تزيد حجم المخاطرة تلقائيًا (تجنّب الجرأة الزائدة
   بعد نجاح مؤقت، لأن كل صفقة مستقلة احتماليًا عن التي قبلها).

5. الاتساق (Consistency):
   نفس القواعد تُطبَّق بنفس الصرامة بغض النظر عن نتيجة آخر صفقة - النظام
   لا "يشك" في قواعده فجأة بعد خسارتين، ولا "يثق بنفسه أكثر" بعد ربحين.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


MIN_SAMPLE_SIZE = 30          # أقل عدد صفقات قبل اعتبار نسبة فوز نوع إشارة "موثوقة"
MAX_CONSECUTIVE_LOSSES = 3    # بعد كم خسارة متتالية يدخل النظام بـ"تبريد"
COOLDOWN_TRADES = 2           # كم صفقة محتملة يتجاهلها النظام أثناء التبريد


@dataclass
class DisciplineState:
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    cooldown_remaining: int = 0
    total_trades_seen: int = 0
    notes: List[str] = field(default_factory=list)


class DisciplineEngine:
    """
    يُستدعى بعد كل صفقة تُغلق (من Backtester أو من تنفيذ حقيقي لاحقاً)،
    ويُستشار قبل كل صفقة جديدة عبر should_allow_trade().
    """

    def __init__(self):
        self.state = DisciplineState()

    def record_trade_result(self, result: str):
        """result: 'win' أو 'loss'. يُحدّث حالة الانضباط الداخلية."""
        self.state.total_trades_seen += 1

        if result == "win":
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0

            if self.state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self.state.cooldown_remaining = COOLDOWN_TRADES
                self.state.notes.append(
                    f"دخول تبريد بعد {self.state.consecutive_losses} خسائر متتالية "
                    f"(صفقة #{self.state.total_trades_seen}) - مبدأ: لا انتقام من السوق."
                )

    def should_allow_trade(self) -> bool:
        """يُستدعى قبل فتح صفقة جديدة. False = النظام في وضع تبريد، يتجاهل الفرصة."""
        if self.state.cooldown_remaining > 0:
            self.state.cooldown_remaining -= 1
            return False
        return True

    def position_size_multiplier(self) -> float:
        """
        مبدأ الاتساق: المضاعف ثابت دائمًا (1.0) بغض النظر عن آخر نتيجة.
        موجودة كدالة منفصلة (لا كقيمة ثابتة) لتوضيح أنها *قرار متعمّد*،
        مش نسيان لزيادتها بعد الأرباح أو تخفيضها بعد الخسائر - وهذا نفسه
        الفرق بين نظام منضبط ونظام "يتحمّس" أو "يخاف".
        """
        return 1.0

    def is_pattern_reliable(self, signal_type: str, sample_size: int) -> bool:
        """قبل الوثوق بأن نوع إشارة معيّن 'ناجح' أو 'فاشل'، يحتاج عينة كافية."""
        return sample_size >= MIN_SAMPLE_SIZE

    def summary(self) -> dict:
        return {
            "total_trades_seen": self.state.total_trades_seen,
            "consecutive_losses": self.state.consecutive_losses,
            "consecutive_wins": self.state.consecutive_wins,
            "in_cooldown": self.state.cooldown_remaining > 0,
            "notes": self.state.notes[-10:],   # آخر 10 ملاحظات فقط
        }


def compute_running_win_rate(trades: list) -> List[dict]:
    """
    يحسب نسبة الفوز التراكمية بعد كل صفقة من الصفقة الأولى (للتأكيد على
    التفكير الاحتمالي: الحكم على الأداء عبر عيّنة متراكمة، لا صفقة منفردة).
    """
    running = []
    wins = 0
    for i, t in enumerate(trades, start=1):
        if t.result == "win":
            wins += 1
        running.append({
            "trade_number": i,
            "running_win_rate": round(wins / i * 100, 2),
        })
    return running
