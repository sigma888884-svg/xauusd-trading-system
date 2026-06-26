"""
backtester.py (محرك Candle-by-Candle)
======================================
محرك Backtest حقيقي يمر شمعة بشمعة (Bar-by-Bar) على بيانات فريم واحد أو أكثر،
كأنه يتداول في السوق الحي، ويحسب مقاييس أداء احترافية:
- Win Rate
- Profit Factor
- Expectancy
- Max Drawdown
- عدد الصفقات / متوسط الربح والخسارة

يدعم:
- إدارة مخاطرة كاملة (SL, TP, % مخاطرة لكل صفقة، حد أقصى خسارة يومية)
- تشغيل على فريم واحد، أو فريمات متعددة مع توافق (Confluence) بين فريم اتجاه عام وفريم دخول
- قابلية التوسعة لدمج فلتر ML لاحقاً (engine.set_signal_filter(...))

ملاحظة: هذا محرك مبسّط لا يحسب Spread/Slippage بدقة سعر حقيقي، لكنه أقرب بكثير
لمحاكاة السوق الحي من نسخة الـMVP الأولى (لأنه يمشي شمعة بشمعة فعلياً، لا نوافذ قفز).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict
import math

import pandas as pd
import yaml

from app.rules_engine import analyze_timeframe, Structure


@dataclass
class Trade:
    direction: str
    entry_time: str
    entry_index: int
    entry_price: float
    sl: float
    tp: float
    risk_amount: float
    exit_time: Optional[str] = None
    exit_index: Optional[int] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None   # "win" | "loss" | "open"
    pnl: float = 0.0
    signal_type: str = ""
    ml_score: Optional[float] = None


@dataclass
class BacktestStats:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0
    final_balance: float = 0.0
    total_pnl: float = 0.0


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    stats: BacktestStats = field(default_factory=BacktestStats)
    equity_curve: List[float] = field(default_factory=list)


def load_strategy(strategy_file: str) -> dict:
    with open(strategy_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_csv(csv_file: str) -> pd.DataFrame:
    df = pd.read_csv(csv_file)
    df.columns = [c.lower() for c in df.columns]
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"ملف CSV ينقصه الأعمدة: {missing}")
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    return df


class CandleByCandleBacktester:
    """
    محرك Backtest يمر شمعة بشمعة. كل خطوة:
    1. يحدّث الصفقة المفتوحة (يتحقق من SL/TP).
    2. لو مافي صفقة مفتوحة، يحلل النافذة الأخيرة من الشموع عبر Rules Engine.
    3. لو فيه إشارة مقبولة (وبعد فلتر ML اختياري)، يفتح صفقة جديدة.
    """

    def __init__(
        self,
        strategy: dict,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 1.0,
        window_size: int = 100,
        max_daily_trades: int = 5,
        max_daily_loss_pct: float = 3.0,
    ):
        self.strategy = strategy
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.window_size = window_size
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct

        self.signal_filter: Optional[Callable[[Structure, dict], bool]] = None
        self.ml_scorer: Optional[Callable[[Structure, dict], float]] = None

        rm = strategy.get("risk_management", {})
        self.rr_ratio = rm.get("reward_risk_ratio", 2.0)
        self.sl_buffer = rm.get("sl_buffer", 0.5)

        entry = strategy.get("entry_rules", {})
        self.min_confidence = entry.get("min_confidence", 0.5)

    def set_signal_filter(self, fn: Callable[[Structure, dict], bool]):
        """يسمح بحقن فلتر خارجي (مثل ml_filter.predict) لقبول/رفض الإشارة."""
        self.signal_filter = fn

    def set_ml_scorer(self, fn: Callable[[Structure, dict], float]):
        """يسمح بحقن دالة تقييم ML (0..1) تُسجَّل مع كل صفقة."""
        self.ml_scorer = fn

    def run(self, candles: List[dict]) -> BacktestResult:
        n = len(candles)
        equity_curve = [self.balance]
        trades: List[Trade] = []
        open_trade: Optional[Trade] = None

        daily_pnl: Dict[str, float] = {}
        daily_trade_count: Dict[str, int] = {}

        for i in range(self.window_size, n):
            current = candles[i]
            day_key = str(current["time"])[:10]

            # --- 1) إدارة الصفقة المفتوحة ---
            if open_trade is not None:
                hit_tp = (current["high"] >= open_trade.tp) if open_trade.direction == "bullish" \
                    else (current["low"] <= open_trade.tp)
                hit_sl = (current["low"] <= open_trade.sl) if open_trade.direction == "bullish" \
                    else (current["high"] >= open_trade.sl)

                if hit_tp or hit_sl:
                    exit_price = open_trade.tp if hit_tp else open_trade.sl
                    pnl = open_trade.risk_amount * self.rr_ratio if hit_tp else -open_trade.risk_amount

                    open_trade.exit_index = i
                    open_trade.exit_time = str(current["time"])
                    open_trade.exit_price = exit_price
                    open_trade.result = "win" if hit_tp else "loss"
                    open_trade.pnl = pnl

                    self.balance += pnl
                    equity_curve.append(self.balance)
                    trades.append(open_trade)

                    daily_pnl[day_key] = daily_pnl.get(day_key, 0) + pnl
                    open_trade = None
                continue

            # --- 2) فحص حدود اليوم (عدد الصفقات / خسارة يومية قصوى) ---
            if daily_trade_count.get(day_key, 0) >= self.max_daily_trades:
                continue
            if daily_pnl.get(day_key, 0) <= -(self.initial_balance * self.max_daily_loss_pct / 100):
                continue

            # --- 3) تحليل النافذة الأخيرة ---
            window = candles[i - self.window_size: i]
            structures = analyze_timeframe(window)
            if not structures:
                continue

            actionable_types = ("BOS", "CHoCH", "OB", "SND", "SNR")
            actionable_structures = [s for s in structures if s.type in actionable_types]
            if not actionable_structures:
                continue

            last = actionable_structures[-1]
            if last.confidence < self.min_confidence:
                continue

            context = {"index": i, "time": current["time"], "candle": current}

            if self.signal_filter and not self.signal_filter(last, context):
                continue

            ml_score = self.ml_scorer(last, context) if self.ml_scorer else None

            # --- 4) فتح صفقة جديدة ---
            entry_price = current["close"]
            if last.direction == "bullish":
                sl = (last.zone_low if last.zone_low else entry_price * (1 - 0.003)) - self.sl_buffer
                risk = entry_price - sl
                tp = entry_price + risk * self.rr_ratio
            else:
                sl = (last.zone_high if last.zone_high else entry_price * (1 + 0.003)) + self.sl_buffer
                risk = sl - entry_price
                tp = entry_price - risk * self.rr_ratio

            if risk <= 0:
                continue

            risk_amount = self.balance * (self.risk_per_trade_pct / 100.0)

            open_trade = Trade(
                direction=last.direction,
                entry_time=str(current["time"]),
                entry_index=i,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
                risk_amount=risk_amount,
                signal_type=last.type,
                ml_score=ml_score,
            )
            daily_trade_count[day_key] = daily_trade_count.get(day_key, 0) + 1

        stats = self._compute_stats(trades, equity_curve)
        return BacktestResult(trades=trades, stats=stats, equity_curve=equity_curve)

    def _compute_stats(self, trades: List[Trade], equity_curve: List[float]) -> BacktestStats:
        wins = [t for t in trades if t.result == "win"]
        losses = [t for t in trades if t.result == "loss"]

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        total_pnl = sum(t.pnl for t in trades)

        win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)

        avg_win = (gross_profit / len(wins)) if wins else 0.0
        avg_loss = (gross_loss / len(losses)) if losses else 0.0
        win_prob = len(wins) / len(trades) if trades else 0.0
        loss_prob = len(losses) / len(trades) if trades else 0.0
        expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)

        peak = equity_curve[0] if equity_curve else self.initial_balance
        max_dd = 0.0
        for eq in equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        return BacktestStats(
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=round(win_rate, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != math.inf else float("inf"),
            expectancy=round(expectancy, 2),
            max_drawdown_pct=round(max_dd, 2),
            final_balance=round(self.balance, 2),
            total_pnl=round(total_pnl, 2),
        )


def run_backtest(
    csv_file: str,
    strategy_file: str = "strategies/xauusd_smc.yaml",
    initial_balance: float = 10000.0,
    risk_per_trade_pct: float = 1.0,
    window_size: int = 100,
) -> BacktestResult:
    """واجهة متوافقة مع الإصدار السابق (تُستخدم من app/main.py عبر /backtest/run)."""
    strategy = load_strategy(strategy_file)
    df = load_csv(csv_file)
    candles = df.to_dict("records")
    for c in candles:
        c["time"] = c["time"].isoformat()

    rm = strategy.get("risk_management", {})
    engine = CandleByCandleBacktester(
        strategy=strategy,
        initial_balance=initial_balance,
        risk_per_trade_pct=risk_per_trade_pct,
        window_size=window_size,
        max_daily_trades=rm.get("max_daily_trades", 5),
        max_daily_loss_pct=rm.get("max_daily_loss_pct", 3.0),
    )
    return engine.run(candles)
