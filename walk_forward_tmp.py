from app.backtester import load_strategy, load_csv
from app.strategy_optimizer import WalkForwardOptimizer
import json

strategy = load_strategy('strategies/xauusd_smc.yaml')
df = load_csv('data/xauusd_1h.csv')
candles = df.to_dict('records')
for c in candles:
    c['time'] = c['time'].isoformat()

optimizer = WalkForwardOptimizer(
    strategy=strategy, sl_usd=5.0, tp_usd=15.0, fixed_risk_usd=100.0,
    use_kill_zone=True, use_trend_filter=True, require_multi_structure=True,
)
report = optimizer.run(candles, window_months=12)

with open('/tmp/walk_forward_result.txt', 'w', encoding='utf-8') as f:
    f.write(report.summary())

print("DONE")
