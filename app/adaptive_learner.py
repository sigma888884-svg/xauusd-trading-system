"""
adaptive_learner.py
=====================
نظام "يتعلم بنفسه" فعليًا: يحدّث تقييمه لكل نوع إشارة (BOS, CHoCH, OB, SND, SNR...)
× اتجاه (bullish/bearish) أونلاين، بعد كل صفقة تُغلق - بدون أي تدريب يدوي منفصل
(بعكس ml_filter.py و rl_agent.py اللي يحتاجان تشغيل تدريب صريح على دفعة بيانات).

الطريقة: تقدير بايزي بسيط (Beta-Bernoulli)، يطبّق بالضبط مبدأ "التفكير الاحتمالي"
اللي بنيناه في discipline_engine.py:

- كل (نوع إشارة × اتجاه) له توزيع Beta(alpha, beta) يمثّل تقديرنا لاحتمال نجاحه.
- نبدأ بـ Prior محايد: Beta(2, 2) (يعني تقديرنا الأولي = 50%، بدون تحيّز).
- بعد كل صفقة: alpha += 1 لو ربحت، beta += 1 لو خسرت.
- التقدير الحالي = alpha / (alpha + beta) — يتحرك تلقائيًا نحو الأداء الحقيقي،
  وبسرعة أكبر في البداية (لما العيّنة صغيرة) وأبطأ مع تجمّع الخبرة (استقرار طبيعي،
  بالضبط مثل تعلّم إنسان: يثق أكثر بالنمط كل ما تكرّر صحيحًا).

هذا "يتعلم" بمعنى حقيقي ومُختبَر: التقدير يتغيّر تلقائيًا بدون أي تدخل برمجي يدوي،
ويُستخدم مباشرة لتصفية/ترتيب الإشارات المستقبلية.
"""
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional, List
import math


PRIOR_ALPHA = 2.0   # Prior محايد: يعادل تقدير ابتدائي 50% بثقة منخفضة
PRIOR_BETA = 2.0


@dataclass
class LearnedStat:
    alpha: float = PRIOR_ALPHA
    beta: float = PRIOR_BETA
    n_observed: int = 0

    @property
    def mean_estimate(self) -> float:
        """التقدير الحالي لاحتمال النجاح (متوسط توزيع Beta)."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def credible_interval_width(self) -> float:
        """مدى عدم اليقين - يضيق مع تجمّع البيانات (دليل 'تعلّم' حقيقي، لا تخمين)."""
        a, b = self.alpha, self.beta
        variance = (a * b) / ((a + b) ** 2 * (a + b + 1))
        return round(2 * math.sqrt(variance), 4)  # تقريب لعرض فترة ثقة ~95%


class AdaptiveLearner:
    """
    self.stats: مفتاحه (signal_type, direction) -> LearnedStat
    """

    def __init__(self):
        self.stats: Dict[Tuple[str, str], LearnedStat] = {}

    def _key(self, signal_type: str, direction: str) -> Tuple[str, str]:
        return (signal_type, direction)

    def get_estimate(self, signal_type: str, direction: str) -> LearnedStat:
        key = self._key(signal_type, direction)
        if key not in self.stats:
            self.stats[key] = LearnedStat()
        return self.stats[key]

    def update(self, signal_type: str, direction: str, result: str):
        """يُستدعى بعد إغلاق كل صفقة فعلية - هنا يحدث 'التعلّم' الفعلي."""
        stat = self.get_estimate(signal_type, direction)
        if result == "win":
            stat.alpha += 1
        else:
            stat.beta += 1
        stat.n_observed += 1

    def adjusted_confidence(self, signal_type: str, direction: str, base_confidence: float, min_trust_n: int = 15) -> float:
        """
        يدمج ثقة Rules Engine الثابتة (base_confidence) مع التقدير المتعلَّم،
        بوزن يعتمد على حجم الخبرة المتجمّعة (مبدأ: لا نثق بعينة صغيرة بشكل كامل).
        """
        stat = self.get_estimate(signal_type, direction)
        trust_weight = min(stat.n_observed / min_trust_n, 1.0)  # 0..1 يكبر مع الخبرة
        return (1 - trust_weight) * base_confidence + trust_weight * stat.mean_estimate

    def should_trust_type(self, signal_type: str, direction: str, threshold: float = 0.45) -> bool:
        """يرفض نوع إشارة تعلّم النظام أنه ضعيف فعليًا (بعد عيّنة كافية)."""
        stat = self.get_estimate(signal_type, direction)
        if stat.n_observed < 10:
            return True  # عيّنة صغيرة جداً - لا نحكم بعد (تفكير احتمالي)
        return stat.mean_estimate >= threshold

    def snapshot(self) -> List[dict]:
        """لقطة لما 'تعلّمه' النظام لحد الآن - تُستخدم للعرض في لوحة التحكم."""
        rows = []
        for (sig_type, direction), stat in sorted(self.stats.items(), key=lambda x: -x[1].n_observed):
            rows.append({
                "signal_type": sig_type,
                "direction": direction,
                "n_observed": stat.n_observed,
                "learned_win_rate": round(stat.mean_estimate * 100, 1),
                "uncertainty": stat.credible_interval_width,
            })
        return rows
