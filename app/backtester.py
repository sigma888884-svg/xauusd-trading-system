"""
backtester.py (محرك سريع: تحليل مرة واحدة + محاكاة Bar-by-Bar)
================================================================
محرك Backtest يحلل البيانات بـRules Engine مرة واحدة فقط (سريع: O(n) بدل O(n²))،
ثم يمر شمعة بشمعة على الإشارات المكتشفة مسبقاً لمحاكاة الدخول/الخروج، كأنه يتداول
في السوق الحي - بدون أي معرفة بالمستقبل (كل إشارة تُستخدم فقط من نقطة ظهورها فصاعداً).

يحسب مقاييس أداء احترافية:
- Win Rate, Profit Factor, Expectancy, Max Drawdown

يدعم وضعين لتحديد SL/TP:
- نسبي (افتراضي، يعتمد على عرض منطقة OB/FVG × reward_risk_ratio)
- ثابت بالدولار (sl_usd, tp_usd) - مناسب لمضاربة يومية بأهداف ثابتة صغيرة
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
    avg_trades_per_day: float = 0.0


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
    محرك Backtest محسَّن للسرعة:
    1. يحلل كل الشموع دفعة واحدة عبر Rules Engine (مرة واحدة، ليس لكل شمعة).
    2. يبني فهرس: عند كل index، أي هياكل جديدة ظهرت هناك (بدون أي معرفة مستقبلية،
       لأن كل هيكل أصلاً مرتبط بنقطة ظهوره التاريخية الحقيقية).
    3. يمر شمعة بشمعة، يدير الصفقة المفتوحة، ويفتح صفقة جديدة عند ظهور إشارة مقبولة.
    """

    def __init__(
        self,
        strategy: dict,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 1.0,
        min_history: int = 60,
        max_daily_trades: int = 4,
        max_daily_loss_pct: float = 3.0,
        sl_usd: Optional[float] = None,
        tp_usd: Optional[float] = None,
        fixed_risk_usd: Optional[float] = None,
    ):
        self.strategy = strategy
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.min_history = min_history
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        self.sl_usd = sl_usd
        self.tp_usd = tp_usd
        self.fixed_risk_usd = fixed_risk_usd

        self.signal_filter: Optional[Callable[[Structure, dict], bool]] = None
        self.ml_scorer: Optional[Callable[[Structure, dict], float]] = None

        rm = strategy.get("risk_management", {})
        self.rr_ratio = rm.get("reward_risk_ratio", 2.0)
        self.sl_buffer = rm.get("sl_buffer", 0.5)

        entry = strategy.get("entry_rules", {})
        self.min_confidence = entry.get("min_confidence", 0.5)
        self.actionable_types = set(entry.get(
            "required_structures",
            ["BOS", "CHoCH", "OB", "SND", "SNR", "REVERSAL_PINBAR", "REVERSAL_ENGULFING"],
        ))

    def set_signal_filter(self, fn: Callable[[Structure, dict], bool]):
        self.signal_filter = fn

    def set_ml_scorer(self, fn: Callable[[Structure, dict], float]):
        self.ml_scorer = fn

    def run(self, candles: List[dict]) -> BacktestResult:
        n = len(candles)
        if n < self.min_history + 5:
            return BacktestResult()

        # --- 1) تحليل دفعة واحدة (أهم تحسين أداء) ---
        all_structures = analyze_timeframe(candles)
        structures_by_index: Dict[int, List[Structure]] = {}
        for s in all_structures:
            structures_by_index.setdefault(s.index, []).append(s)

        equity_curve = [self.balance]
        trades: List[Trade] = []
        open_trade: Optional[Trade] = None

        daily_pnl: Dict[str, float] = {}
        daily_trade_count: Dict[str, int] = {}

        for i in range(self.min_history, n):
            current = candles[i]
            day_key = str(current["time"])[:10]

            # --- 2) إدارة الصفقة المفتوحة ---
            if open_trade is not None:
                hit_tp = (current["high"] >= open_trade.tp) if open_trade.direction == "bullish" \
                    else (current["low"] <= open_trade.tp)
                hit_sl = (current["low"] <= open_trade.sl) if open_trade.direction == "bullish" \
                    else (current["high"] >= open_trade.sl)

                if hit_tp or hit_sl:
                    exit_price = open_trade.tp if hit_tp else open_trade.sl
                    # النسبة الفعلية المُحقَّقة: TP/SL الحقيقي للصفقة، لا الإعداد العام الافتراضي
                    actual_rr = abs(open_trade.tp - open_trade.entry_price) / abs(open_trade.entry_price - open_trade.sl)
                    pnl = open_trade.risk_amount * actual_rr if hit_tp else -open_trade.risk_amount

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

            # --- 3) حدود اليوم ---
            if daily_trade_count.get(day_key, 0) >= self.max_daily_trades:
                continue
            if daily_pnl.get(day_key, 0) <= -(self.initial_balance * self.max_daily_loss_pct / 100):
                continue

            # --- 4) هل ظهرت إشارة جديدة عند هذا الـindex بالضبط؟ ---
            new_structures = structures_by_index.get(i)
            if not new_structures:
                continue

            actionable = [s for s in new_structures if s.type in self.actionable_types and s.confidence >= self.min_confidence]
            if not actionable:
                continue
            last = actionable[-1]

            context = {"index": i, "time": current["time"], "candle": current}
            if self.signal_filter and not self.signal_filter(last, context):
                continue

            ml_score = self.ml_scorer(last, context) if self.ml_scorer else None

            # --- 5) فتح صفقة جديدة ---
            entry_price = current["close"]
            if self.sl_usd is not None and self.tp_usd is not None:
                # SL/TP ثابت بالدولار (مناسب لمضاربة يومية بأهداف صغيرة)
                if last.direction == "bullish":
                    sl = entry_price - self.sl_usd
                    tp = entry_price + self.tp_usd
                else:
                    sl = entry_price + self.sl_usd
                    tp = entry_price - self.tp_usd
                risk = self.sl_usd
            else:
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

            risk_amount = self.fixed_risk_usd if self.fixed_risk_usd is not None \
                else self.balance * (self.risk_per_trade_pct / 100.0)

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

        stats = self._compute_stats(trades, equity_curve, candles)
        return BacktestResult(trades=trades, stats=stats, equity_curve=equity_curve)

    def _compute_stats(self, trades: List[Trade], equity_curve: List[float], candles: List[dict]) -> BacktestStats:
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

        n_days = 1
        if candles:
            try:
                t0 = pd.to_datetime(candles[0]["time"])
                t1 = pd.to_datetime(candles[-1]["time"])
                n_days = max(1, (t1 - t0).days)
            except Exception:
                pass

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
            avg_trades_per_day=round(len(trades) / n_days, 3),
        )


def run_backtest(
    csv_file: str,
    strategy_file: str = "strategies/xauusd_smc.yaml",
    initial_balance: float = 10000.0,
    risk_per_trade_pct: float = 1.0,
    window_size: int = 100,
    sl_usd: Optional[float] = None,
    tp_usd: Optional[float] = None,
) -> BacktestResult:
    """واجهة متوافقة مع main.py عبر /backtest/run. window_size محتفظ به للتوافق فقط (غير مستخدم الآن)."""
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
        max_daily_trades=rm.get("max_daily_trades", 4),
        max_daily_loss_pct=rm.get("max_daily_loss_pct", 3.0),
        sl_usd=sl_usd if sl_usd is not None else rm.get("sl_usd"),
        tp_usd=tp_usd if tp_usd is not None else rm.get("tp_usd"),
    )
    return engine.run(candles)
