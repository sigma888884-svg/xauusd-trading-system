"""
rl_agent.py
============
طبقة Reinforcement Learning بسيطة (كما طُلب: "بسيطة في البداية").

الفكرة المبسّطة (Multi-Armed Bandit بدل Deep RL كامل، لأنه:
1. أسهل تفسيراً وتدقيقاً (Explainable) — مهم جداً في التداول.
2. لا يحتاج بيانات ضخمة ليتعلم بشكل معقول.
3. قابل للترقية لاحقاً إلى Q-Learning كامل أو PPO بدون تغيير الواجهة الخارجية).

الوكيل (Agent) يجرّب مجموعة من "الاستراتيجيات المرشَّحة" (مثلاً: تركيبات مختلفة من
reward_risk_ratio وmin_confidence)، ويشغّل Backtester على كل واحدة، ثم يستخدم
خوارزمية Epsilon-Greedy لاختيار وتفضيل الإستراتيجية الأفضل أداءً تدريجياً.

الاستخدام:
    agent = RLAgent(candidate_configs=[...])
    best = agent.optimize(candles, n_iterations=50)
    print(best.config, best.avg_reward)
"""
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional
import random
import copy

from app.backtester import CandleByCandleBacktester, BacktestStats


@dataclass
class Arm:
    """استراتيجية مرشّحة واحدة (تركيبة معاملات) مع سجل أدائها التراكمي."""
    config: Dict
    n_pulls: int = 0
    total_reward: float = 0.0

    @property
    def avg_reward(self) -> float:
        return self.total_reward / self.n_pulls if self.n_pulls > 0 else 0.0


@dataclass
class RLResult:
    config: Dict
    avg_reward: float
    n_pulls: int
    history: List[Dict] = field(default_factory=list)


def _reward_from_stats(stats: BacktestStats) -> float:
    """
    دالة المكافأة (Reward Function): توازن بين الربحية والمخاطرة.
    نستخدم Expectancy مخصوماً منه عقوبة على الـDrawdown المرتفع، حتى لا يفضّل
    الوكيل استراتيجيات "مقامرة" بعائد عالي ومخاطرة مدمّرة.
    """
    if stats.total_trades == 0:
        return -1.0  # عقوبة لعدم التداول أصلاً (إشارة على شروط دخول صعبة جداً)

    drawdown_penalty = stats.max_drawdown_pct / 100.0
    return stats.expectancy - (drawdown_penalty * 50)  # معامل العقوبة قابل للتعديل


class RLAgent:
    """
    وكيل Epsilon-Greedy بسيط لاختيار أفضل تركيبة معاملات للاستراتيجية
    (مثل reward_risk_ratio, min_confidence, sl_buffer) عبر تجربتها فعلياً على Backtester.
    """

    def __init__(
        self,
        base_strategy: dict,
        candidate_overrides: List[Dict],
        epsilon: float = 0.2,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 1.0,
        window_size: int = 100,
    ):
        """
        base_strategy: قاموس الاستراتيجية الأساسي (من xauusd_smc.yaml)
        candidate_overrides: قائمة قواميس جزئية، كل واحدة تُدمج فوق base_strategy لتكوّن "Arm"
            مثال: [{"risk_management": {"reward_risk_ratio": 1.5}},
                    {"risk_management": {"reward_risk_ratio": 3.0}}, ...]
        """
        self.base_strategy = base_strategy
        self.epsilon = epsilon
        self.initial_balance = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.window_size = window_size

        self.arms: List[Arm] = [
            Arm(config=self._merge(base_strategy, override))
            for override in candidate_overrides
        ]

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        merged = copy.deepcopy(base)
        for section, values in override.items():
            if section in merged and isinstance(merged[section], dict):
                merged[section].update(values)
            else:
                merged[section] = values
        return merged

    def _pull_arm(self, arm: Arm, candles: List[dict]) -> float:
        rm = arm.config.get("risk_management", {})
        engine = CandleByCandleBacktester(
            strategy=arm.config,
            initial_balance=self.initial_balance,
            risk_per_trade_pct=self.risk_per_trade_pct,
            window_size=self.window_size,
            max_daily_trades=rm.get("max_daily_trades", 5),
            max_daily_loss_pct=rm.get("max_daily_loss_pct", 3.0),
        )
        result = engine.run(candles)
        reward = _reward_from_stats(result.stats)

        arm.n_pulls += 1
        arm.total_reward += reward
        return reward

    def optimize(self, candles: List[dict], n_iterations: int = 30) -> RLResult:
        """يشغّل n_iterations جولة Epsilon-Greedy على بيانات candles ويرجع أفضل Arm."""
        history = []

        for it in range(n_iterations):
            if random.random() < self.epsilon or all(a.n_pulls == 0 for a in self.arms):
                arm = random.choice(self.arms)   # استكشاف (Exploration)
            else:
                arm = max(self.arms, key=lambda a: a.avg_reward)  # استغلال (Exploitation)

            reward = self._pull_arm(arm, candles)
            history.append({
                "iteration": it,
                "config_summary": arm.config.get("risk_management", {}),
                "reward": round(reward, 4),
            })

        best_arm = max(self.arms, key=lambda a: a.avg_reward)
        return RLResult(
            config=best_arm.config,
            avg_reward=round(best_arm.avg_reward, 4),
            n_pulls=best_arm.n_pulls,
            history=history,
        )


def default_candidate_overrides() -> List[Dict]:
    """مجموعة افتراضية معقولة من التركيبات لتجربتها (RR ratio × min_confidence)."""
    candidates = []
    for rr in (1.5, 2.0, 3.0):
        for min_conf in (0.45, 0.55, 0.65):
            candidates.append({
                "risk_management": {"reward_risk_ratio": rr},
                "entry_rules": {"min_confidence": min_conf},
            })
    return candidates
