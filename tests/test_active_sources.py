from datetime import timedelta
import json
from types import SimpleNamespace
import futu
import pytest
import radar
import radar_market as market
from test_market import END
from test_market_integration import raw_bars


def test_collect_drops_retired_polling_and_static_gaps(monkeypatch):
    class FakeContext:
        def request_history_kline(self,code,**kwargs):
            import pandas as pd
            return futu.RET_OK,pd.DataFrame(raw_bars()),None
        def close(self):pass
    monkeypatch.setattr(futu,'OpenQuoteContext',lambda **kwargs:FakeContext())
    monkeypatch.setattr(market,'sample_market_quotes',lambda *a,**kw:pytest.fail('retired Yahoo polling executed'))
    # BTC collection is tested separately; no real provider calls here.
    monkeypatch.setattr(market,'collect_btc',lambda *a,**kw:{'status':'ok'},raising=False)
    result=market.collect(END,{})
    assert result.get('quotes',{})=={}
    assert result['gaps']==[]
    assert result['coverage']['requested_count']==29


def test_collect_keeps_btc_separate_from_etf_coverage(monkeypatch):
    import pandas as pd
    class FakeContext:
        closed=False
        def request_history_kline(self,code,**kwargs):
            return futu.RET_OK,pd.DataFrame(raw_bars()),None
        def close(self):self.closed=True
    ctx=FakeContext()
    monkeypatch.setattr(futu,'OpenQuoteContext',lambda **kwargs:ctx)
    calls=[]
    def crypto(context,end,budget):
        assert not context.closed
        calls.append(context)
        return {'status':'ok','return_10m_pct':.7,'volume_10m':2,'traded_minutes':10,'completed_bars':10,'fresh':True}
    monkeypatch.setattr(market,'collect_btc',crypto,raising=False)
    result=market.collect(END,{})
    assert calls==[ctx] and ctx.closed
    assert result['btc']['return_10m_pct']==.7
    assert result['coverage']['requested_count']==29
    assert 'CC.BTCUSD' not in result['rows']
    assert any(s['instrument']=='BTC/USD' for s in result['cross_signals'])


def test_btc_epoch_unpack_ignores_naive_display_timezone(monkeypatch):
    import importlib.util
    assert importlib.util.find_spec('radar_crypto') is not None, 'BTC source adapter missing'
    from radar_crypto import epoch_unpack
    from futu.quote.quote_query import RequestHistoryKlineQuery
    from datetime import datetime,timezone
    stamp=datetime(2026,12,1,15,0,tzinfo=timezone.utc).timestamp()
    raw=SimpleNamespace(time='2026-12-01 10:00:00',timestamp=stamp,isBlank=False,HasField=lambda k:True)
    pb=SimpleNamespace(s2c=SimpleNamespace(klList=[raw]))
    monkeypatch.setattr(RequestHistoryKlineQuery,'unpack_rsp',lambda pb:(0,'',([{'time_key':raw.time,'close':100}],False,None)))
    ret,msg,(rows,_,_)=epoch_unpack(pb)
    assert rows[0]['time_key']=='2026-12-01T15:00:00+00:00'
    assert rows[0]['source_time_basis']=='unix_epoch'


def test_report_shows_btc_units_without_inflating_etf_table():
    from radar_explain import threshold_details
    btc={'status':'ok','return_10m_pct':.12,'volume_10m':2.5,'volume_ratio_10m':1.2,
         'last_completed_bar':END.isoformat(),'completed_bars':10,'traded_minutes':10}
    text=threshold_details({'rows':{},'btc':btc})
    assert 'BTC/USD' in text and '2.50000 BTC' in text
    assert '非IBIT' in text and 'unix epoch' in text
    assert '|CC.BTCUSD|' not in text


def test_quiet_report_only_warns_about_active_failures():
    result={'status':'partial','errors':[{'ticker':'SPY','error':'permission denied'}],
            'gaps':['SPY分鐘線不足'],'rows':{},'btc':{'status':'error','reason':'permission denied'}}
    text=radar.render_quiet_report({'slot':END.isoformat()},result)
    assert 'SPY分鐘線不足' in text and 'permission denied' in text
    assert 'VIX/US10Y' not in text
    assert 'Yahoo' not in text
    assert '資料不足' in text
