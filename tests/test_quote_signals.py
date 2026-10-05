from radar_market import quote_cross_signals, cluster_candidates
from test_market import bars


def test_oil_etf_is_not_misreported_as_energy_stock_breadth():
    uso=bars('USO',[0.0]*30+[0.1]*10)
    candidates=cluster_candidates({'USO':uso})
    assert len(candidates)==1
    assert candidates[0]['cluster']=='oil_proxy'
    assert candidates[0]['sampled_breadth']['denominator']==0



def test_quote_cross_signals_use_vix_points_and_treasury_basis_points_materiality():
    changes = {
        '^VIX': {'change_points': 1.1, 'elapsed_seconds': 600},
        '^TNX': {'change_basis_points': -3.2, 'elapsed_seconds': 600},
    }
    signals = quote_cross_signals(changes)
    assert [(s['instrument'], s['change']) for s in signals] == [('VIX', 1.1), ('US10Y', -3.2)]
    assert all(s['confidence'].startswith('reduced') and s['threshold'] for s in signals)


def test_quote_cross_signals_skip_subthreshold_or_malformed_observations():
    assert quote_cross_signals({'^VIX': {'change_points': .9}, '^TNX': {'change_basis_points': 'bad'}}) == []

from datetime import datetime, timedelta, timezone
from radar_market import sample_market_quotes


def make_quote(symbol, price, when):
    return {'symbol':symbol,'instrument':symbol,'price':price,'source_time':when.isoformat(),
            'received_at':when.isoformat(),'source':'test quote provider',
            'unit':'percent' if symbol=='^TNX' else 'index_points'}


def test_sampling_persists_warmup_then_returns_only_valid_observed_pairs(tmp_path):
    start=datetime(2026,10,2,14,0,tzinfo=timezone.utc)
    values={'^VIX':15.0,'^TNX':5.2}
    def fetch(symbol):return make_quote(symbol,values[symbol],start)
    db=tmp_path/'quotes.sqlite'
    first,changes=sample_market_quotes(db,fetch,now=start)
    assert not changes and {v['status'] for v in first.values()}=={'warmup'}
    now=start+timedelta(minutes=10)
    values.update({'^VIX':16.2,'^TNX':5.24})
    def fetch_next(symbol):return make_quote(symbol,values[symbol],now)
    second,changes=sample_market_quotes(db,fetch_next,now=now)
    assert {v['status'] for v in second.values()}=={'observed'}
    assert changes['^VIX']['change_points']==1.2
    assert changes['^TNX']['change_basis_points']==4.0


def test_diagnostic_sampling_does_not_seed_production_baseline(tmp_path):
    start=datetime(2026,10,2,14,0,tzinfo=timezone.utc)
    db=tmp_path/'quotes.sqlite'
    sample_market_quotes(db,lambda s:make_quote(s,15 if s=='^VIX' else 5.2,start),diagnostic=True,now=start)
    observations,changes=sample_market_quotes(db,lambda s:make_quote(s,16 if s=='^VIX' else 5.3,start+timedelta(minutes=10)),now=start+timedelta(minutes=10))
    assert not changes
    assert {v['status'] for v in observations.values()}=={'warmup'}
