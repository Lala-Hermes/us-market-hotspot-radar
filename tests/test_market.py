from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from radar_market import analyze_ticker, cluster_candidates, cross_signals

ET = ZoneInfo('America/New_York')
END = datetime(2026, 10, 5, 10, 0, tzinfo=ET)

def bars(ticker, returns=None, volume=10000, start=END-timedelta(minutes=40), baseline=100):
    returns = returns or [0.0] * 40
    out=[]; price=baseline
    for i, r in enumerate(returns):
        op=price; price=price*(1+r/100)
        out.append({'time': (start+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'), 'open':op,'close':price,'high':max(op,price)*1.001,'low':min(op,price)*.999,'volume':volume})
    return analyze_ticker(ticker,out,END)

def test_excludes_unfinished_candle_and_reports_real_trade_counts():
    data=[{'time':(END-timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S'),'open':100,'close':101,'volume':10}, {'time':(END-timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S'),'open':101,'close':102,'volume':10}]
    row=analyze_ticker('SPY',data,END)
    assert row['completed_bars']==2 and row['traded_minutes']==2

def test_baseline_uses_preceding_close_and_falls_back_to_open():
    seq = [0.0] * 40
    seq[-10:] = [0.1] * 10
    row = bars('SPY', seq)
    assert row['baseline_source'] == 'preceding_close'
    assert row['return_10m_pct'] > 1.0
    raw = [{'time': (END-timedelta(minutes=10-i)).strftime('%Y-%m-%d %H:%M:%S'), 'open':100+i,'close':101+i,'volume':100} for i in range(10)]
    fallback = analyze_ticker('QQQ', raw, END)
    assert fallback['baseline_source'] == 'open'

def test_zero_volume_means_unknown_not_flat_and_insufficient():
    row = bars('SPY', volume=0)
    assert row['traded_minutes'] == 0 and row['return_10m_pct'] is None
    assert row['status'] == 'insufficient'

def test_relative_strength_and_activity_stats_are_percent_points():
    a = bars('SPY', [0.0]*30 + [0.1]*10)
    b = bars('QQQ', [0.0]*30 + [0.2]*10)
    assert round((b['return_10m_pct'] - a['return_10m_pct']) - 1.0, 2) == 0.01
    assert b['volume_ratio_10m'] == 1.0
    assert b['previous_10m_pct'] == 0.0

def test_candidate_requires_materiality_activity_and_adaptive_threshold():
    quiet = [0.03 if i % 2 else -0.03 for i in range(40)]
    row = bars('XLF', quiet)
    rows = {row['ticker']: row}
    assert cluster_candidates(rows) == []
    active = [0.0]*30 + [0.06]*10
    row = bars('XLK', active)
    assert len(cluster_candidates({row['ticker']: row})) == 1
    assert cluster_candidates({'SPY': bars('SPY', [0.0]*30+[0.03]*10)}) == []

def test_semiconductor_cluster_produces_directional_candidate():
    up = [0.0]*30 + [0.1]*10
    rows = {t: bars(t, up) for t in ('SOXX','SMH')}
    found = cluster_candidates(rows)
    assert len(found) == 1 and found[0]['cluster'] == 'semiconductors'
    assert found[0]['direction'] == 'bullish'
    down = {t: bars(t, [0.0]*30+[-0.1]*10) for t in ('SOXX','SMH')}
    assert cluster_candidates(down)[0]['direction'] == 'bearish'

def test_constituent_sampled_breadth_uses_valid_names_only():
    broad = bars('SPY', [0.0]*30+[0.1]*10)
    rows = {'SPY': broad, 'QQQ': bars('QQQ', [0.0]*30+[-0.1]*10)}
    extra = {'AAPL': bars('AAPL', [0.0]*30+[0.2]*10), 'MSFT': {'ticker':'MSFT','status':'insufficient','return_10m_pct':None}}
    found = cluster_candidates(rows, extra)
    assert found[0]['sampled_breadth']['valid'] == 1
    assert found[0]['sampled_breadth']['denominator'] == 4

def test_cross_signals_require_valid_fresh_rows_and_note_unsupported_gaps():
    rows = {'SPY': bars('SPY', [0.0]*30+[0.05]*10), 'QQQ': bars('QQQ', [0.0]*30+[0.30]*10), 'IWM': bars('IWM', [0.0]*30+[0.4]*10), 'TLT': bars('TLT', [0.0]*30+[-0.3]*10), 'GLD': bars('GLD', [0.0]*30+[0.2]*10), 'IBIT': bars('IBIT', [0.0]*30+[-0.7]*10)}
    sig, gaps = cross_signals(rows)
    assert any(s['type'] == 'index_divergence' for s in sig)
    assert any('VIX' in g for g in gaps)
    rows['QQQ']['status'] = 'insufficient'
    sig, _ = cross_signals(rows)
    assert not any(s.get('ticker') == 'QQQ' for s in sig)


def test_uso_is_scanned_as_an_energy_etf_proxy():
    from radar_market import CLUSTERS, TICKERS
    assert 'USO' in TICKERS
    assert 'USO' in CLUSTERS['oil_proxy']
