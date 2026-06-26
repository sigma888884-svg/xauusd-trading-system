"""
strategy_optimizer.py
========================
محرك Walk-Forward Validation: يقسّم البيانات التاريخية لنوافذ زمنية متتالية
غير متراكبة (Train -> Validate -> Test)، ويختبر الاستراتيجية على كل نافذة
بشكل مستقل، بدل اختبارها مرة واحدة على كل البيانات (اللي يؤدي لـ"تسريب"/Overfitting
كما ذكرت).

الفكرة:
- نقسم 9 سنوات مثلاً إلى نوافذ سنة بسنة (configurable).
- كل نافذة تُختبر بمعزل عن الأخرى (مافي تدريب على المستقبل ثم اختبار على الماضي).
- استراتيجية "ناجحة فعليًا" (not leaked) = نتائجها مستقرة ومربحة عبر أغلب النوافذ،
  لا مجرد نافذة واحدة محظوظة وسط نوافذ خاسرة.

الاستخدام:
    optimizer = WalkForwardOptimizer(strategy, sl_usd=5, tp_usd=15, fixed_risk_usd=100)
    report = optimizer.run(candles, window_months=12)
    print(report.summary())
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

import pandas as pd

from app.backtester import CandleByCandleBacktester, BacktestStats
from app.confluence_filters import make_confluence_filter
from app.rules_engine import analyze_timeframe


@dataclass
class WindowResult:
    window_label: str
    start: str
    end: str
    stats: BacktestStats


@dataclass
class WalkForwardReport:
    windows: List[WindowResult] = field(default_factory=list)

    @property
    def profitable_windows(self) -> int:
        return sum(1 for w in self.windows if w.stats.total_pnl > 0)

    @property
    def total_windows(self) -> int:
        return len(self.windows)

    @property
    def consistency_pct(self) -> float:
        """نسبة النوافذ المربحة من إجمالي النوافذ - المقياس الأهم لتفادي 'التسريب'."""
        return round(self.profitable_windows / self.total_windows * 100, 1) if self.windows else 0.0

    @property
    def avg_win_rate(self) -> float:
        wins = [w.stats.win_rate for w in self.windows if w.stats.total_trades > 0]
        return round(sum(wins) / len(wins), 2) if wins else 0.0

    @property
    def worst_window(self) -> Optional[WindowResult]:
        valid = [w for w in self.windows if w.stats.total_trades > 0]
        return min(valid, key=lambda w: w.stats.total_pnl) if valid else None

    def summary(self) -> str:
        lines = [
            f"عدد النوافذ المختبرة: {self.total_windows}",
            f"النوافذ المربحة: {self.profitable_windows}/{self.total_windows} "
            f"({self.consistency_pct}%) <- المقياس الأهم لمصداقية الاستراتيجية",
            f"متوسط نسبة الفوز عبر كل النوافذ: {self.avg_win_rate}%",
        ]
        if self.worst_window:
            w = self.worst_window
            lines.append(
                f"أسوأ نافذة: {w.window_label} ({w.start} -> {w.end}) | "
                f"PnL={w.stats.total_pnl}, DD={w.stats.max_drawdown_pct}%"
            )
        lines.append("\nتفاصيل كل نافذة:")
        for w in self.windows:
            lines.append(
                f"  {w.window_label} ({w.start[:10]} -> {w.end[:10]}): "
                f"trades={w.stats.total_trades}, win_rate={w.stats.win_rate}%, "
                f"PF={w.stats.profit_factor}, PnL={w.stats.total_pnl}, DD={w.stats.max_drawdown_pct}%"
            )
        return "\n".join(lines)


class WalkForwardOptimizer:
    def __init__(
        self,
        strategy: dict,
        sl_usd: float = 5.0,
        tp_usd: float = 15.0,
        fixed_risk_usd: float = 100.0,
        max_daily_trades: int = 4,
        max_daily_loss_pct: float = 3.0,
        use_kill_zone: bool = True,
        use_trend_filter: bool = True,
        require_multi_structure: bool = False,
    ):
        self.strategy = strategy
        self.sl_usd = sl_usd
        self.tp_usd = tp_usd
        self.fixed_risk_usd = fixed_risk_usd
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        self.use_kill_zone = use_kill_zone
        self.use_trend_filter = use_trend_filter
        self.require_multi_structure = require_multi_structure

    def _split_windows(self, candles: List[dict], window_months: int) -> List[List[dict]]:
        df = pd.DataFrame(candles)
        df["time"] = pd.to_datetime(df["time"])
        df["window_key"] = df["time"].dt.to_period(f"{window_months}M")

        windows = []
        for _, group in df.groupby("window_key"):
            window_candles = group.drop(columns=["window_key"]).to_dict("records")
            for c in window_candles:
                c["time"] = c["time"].isoformat()
            windows.append(window_candles)
        return windows

    def run(self, candles: List[dict], window_months: int = 12) -> WalkForwardReport:
        windows = self._split_windows(candles, window_months)
        report = WalkForwardReport()

        for i, window_candles in enumerate(windows):
            if len(window_candles) < 100:
                continue  # نافذة قصيرة جداً لا تُعطي نتيجة موثوقة

            structures_by_index = None
            if self.require_multi_structure:
                all_structs = analyze_timeframe(window_candles)
                structures_by_index = {}
                for s in all_structs:
                    structures_by_index.setdefault(s.index, []).append(s)

            engine = CandleByCandleBacktester(
                strategy=self.strategy,
                initial_balance=10000,
                max_daily_trades=self.max_daily_trades,
                max_daily_loss_pct=self.max_daily_loss_pct,
                sl_usd=self.sl_usd, tp_usd=self.tp_usd,
                fixed_risk_usd=self.fixed_risk_usd,
            )
            if self.use_kill_zone or self.use_trend_filter or self.require_multi_structure:
                engine.set_signal_filter(make_confluence_filter(
                    window_candles,
                    use_kill_zone=self.use_kill_zone,
                    use_trend_filter=self.use_trend_filter,
                    require_multi_structure=self.require_multi_structure,
                    structures_by_index=structures_by_index,
                ))

            result = engine.run(window_candles)
            report.windows.append(WindowResult(
                window_label=f"W{i+1}",
                start=window_candles[0]["time"],
                end=window_candles[-1]["time"],
                stats=result.stats,
            ))

        return report
