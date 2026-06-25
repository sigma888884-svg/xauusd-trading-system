"""
Backtester بسيط (MVP):
- يقرأ بيانات OHLCV تاريخية من CSV (أعمدة: time, open, high, low, close, volume)
- يقرأ إعدادات الاستراتيجية من ملف YAML (strategies/xauusd_smc.yaml)
- يمر على البيانات بنافذة متدرجة (Rolling Window)، يكتشف الهياكل عبر rules_engine،
  ويفتح صفقات افتراضية بناءً على قواعد دخول/خروج مبسطة.
- يحسب نتائج أساسية: عدد الصفقات، نسبة الفوز، الربح/الخسارة الإجمالي، أقصى تراجع (Max Drawdown)

هذا مُحاكي مبسّط وليس بديلاً عن منصة Backtesting متقدمة (لا يحسب Slippage/Spread بدقة).
"""
import pandas as pd
import yaml
from dataclasses import dataclass, field
from typing import List, Optional

from app.rules_engine import analyze_timeframe, Structure


@dataclass
class Trade:
    direction: str
    entry_index: int
    entry_price: float
    sl: float
    tp: float
    exit_index: Optional[int] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None   # "win" | "loss" | "open"
    pnl: float = 0.0


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    final_balance: float = 0.0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0


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


def run_backtest(
    csv_file: str,
    strategy_file: str = "strategies/xauusd_smc.yaml",
    initial_balance: float = 10000.0,
    risk_per_trade_pct: float = 1.0,
    window_size: int = 100,
) -> BacktestResult:

    strategy = load_strategy(strategy_file)
    rr_ratio = strategy.get("risk_management", {}).get("reward_risk_ratio", 2.0)
    min_confidence = strategy.get("entry_rules", {}).get("min_confidence", 0.5)
    sl_buffer_pips = strategy.get("risk_management", {}).get("sl_buffer", 0.5)

    df = load_csv(csv_file)
    candles = df.to_dict("records")
    for c in candles:
        c["time"] = c["time"].isoformat()

    balance = initial_balance
    equity_curve = [balance]
    trades: List[Trade] = []
    open_trade: Optional[Trade] = None

    n = len(candles)
    for i in range(window_size, n):
        window = candles[i - window_size: i]
        current = df.iloc[i]

        # --- إدارة الصفقة المفتوحة أولاً ---
        if open_trade is not None:
            hit_tp = (current["high"] >= open_trade.tp) if open_trade.direction == "bullish" \
                else (current["low"] <= open_trade.tp)
            hit_sl = (current["low"] <= open_trade.sl) if open_trade.direction == "bullish" \
                else (current["high"] >= open_trade.sl)

            if hit_tp or hit_sl:
                exit_price = open_trade.tp if hit_tp else open_trade.sl
                risk_amount = balance * (risk_per_trade_pct / 100.0)
                pnl = risk_amount * rr_ratio if hit_tp else -risk_amount

                open_trade.exit_index = i
                open_trade.exit_price = exit_price
                open_trade.result = "win" if hit_tp else "loss"
                open_trade.pnl = pnl

                balance += pnl
                equity_curve.append(balance)
                trades.append(open_trade)
                open_trade = None
            continue  # لا نفتح صفقة جديدة وصفقة قائمة لم تُغلق بعد

        # --- البحث عن فرصة دخول جديدة ---
        structures: List[Structure] = analyze_timeframe(window)
        if not structures:
            continue

        last = structures[-1]
        is_actionable = last.type in ("BOS", "CHoCH", "OB") and last.confidence >= min_confidence
        if not is_actionable:
            continue

        entry_price = current["close"]
        if last.direction == "bullish":
            sl = (last.zone_low if last.zone_low else entry_price * (1 - 0.003)) - sl_buffer_pips
            risk = entry_price - sl
            tp = entry_price + risk * rr_ratio
        else:
            sl = (last.zone_high if last.zone_high else entry_price * (1 + 0.003)) + sl_buffer_pips
            risk = sl - entry_price
            tp = entry_price - risk * rr_ratio

        if risk <= 0:
            continue

        open_trade = Trade(
            direction=last.direction,
            entry_index=i,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
        )

    wins = [t for t in trades if t.result == "win"]
    total_pnl = sum(t.pnl for t in trades)
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return BacktestResult(
        trades=trades,
        final_balance=balance,
        win_rate=round(win_rate, 2),
        total_pnl=round(total_pnl, 2),
        max_drawdown=round(max_dd, 2),
    )
