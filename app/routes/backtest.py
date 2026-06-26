"""
app/routes/backtest.py
========================
Endpoint تشغيل الـBacktester (محرك Candle-by-Candle الجديد)، مع خيار تفعيل فلتر ML.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backtester import run_backtest
from app.schemas import BacktestRequest

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestResponse(BaseModel):
    final_balance: float
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    profit_factor: float
    expectancy: float
    total_pnl: float
    max_drawdown_pct: float


@router.post("/run", response_model=BacktestResponse)
def backtest_run(req: BacktestRequest):
    """
    يشغّل الـBacktester على ملف CSV تاريخي (أعمدة: time,open,high,low,close,volume).
    مثال: POST /backtest/run
    {"strategy_file": "strategies/xauusd_smc.yaml", "csv_file": "data/xauusd_1h.csv"}
    """
    try:
        result = run_backtest(
            csv_file=req.csv_file,
            strategy_file=req.strategy_file,
            initial_balance=req.initial_balance,
            risk_per_trade_pct=req.risk_per_trade_pct,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    s = result.stats
    return BacktestResponse(
        final_balance=s.final_balance,
        total_trades=s.total_trades,
        wins=s.wins,
        losses=s.losses,
        win_rate_pct=s.win_rate,
        profit_factor=(s.profit_factor if s.profit_factor != float("inf") else 999999.0),
        expectancy=s.expectancy,
        total_pnl=s.total_pnl,
        max_drawdown_pct=s.max_drawdown_pct,
    )
