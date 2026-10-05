from datetime import datetime,timedelta
import pandas as pd
import pytest
import futu
import radar_market as market
from test_market import END,bars


def raw_bars(end=END,move=.0,vol=10000):
    result=[]; p=100
    for i in range(41):
        t=end-timedelta(minutes=41-i)
        op=p
        p=p*(1+(move/10)/100) if i>=31 else p
        result.append({'time_key':t.strftime('%Y-%m-%d %H:%M:%S'),'open':op,'close':p,'high':max(op,p),'low':min(op,p),'volume':vol})
    return result


def test_source_trade_staleness_cannot_be_valid():
    data=raw_bars()
    for row in data[-7:]:row['volume']=0
    result=market.analyze_ticker('SPY',data,END)
    assert result['status']=='insufficient'
    assert result['last_trade_time'].endswith('09:52:00-04:00')


def test_previous_return_uses_same_ten_minute_boundary_as_current():
    data=raw_bars()
    p=100
    for row in data:
        row['open']=p; p*=1.001; row['close']=p
    result=market.analyze_ticker('SPY',data,END)
    assert abs(result['previous_10m_pct']-result['return_10m_pct'])<.00001
    assert abs(result['acceleration_pp'])<.00001


def test_source_baseline_cannot_use_yesterday_close():
    recent=raw_bars()[-10:]
    old={'time_key':(END-timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),'open':1,'close':1,'high':1,'low':1,'volume':10}
    result=market.analyze_ticker('SPY',[old]+recent,END)
    assert result['baseline_source']=='open'
    assert result['return_10m_pct']==0


def test_broad_market_and_software_can_be_detected_separately():
    spy=bars('SPY',[0.0]*30+[0.08]*10)
    assert any(c['cluster']=='broad_market' for c in market.cluster_candidates({'SPY':spy}))
    igv=bars('IGV',[0.0]*30+[-0.08]*10)
    assert any(c['cluster']=='software' for c in market.cluster_candidates({'IGV':igv}))


def test_different_sector_members_do_not_fake_synchronized_direction():
    up=bars('SOXX',[0.0]*30+[0.08]*10)
    down=bars('SMH',[0.0]*30+[-0.07]*10)
    candidates=market.cluster_candidates({'SOXX':up,'SMH':down})
    assert not candidates or candidates[0]['direction']=='mixed'


def test_market_collect_keeps_context_open_through_constituents(monkeypatch):
    calls=[]
    class FakeContext:
        closed=False
        def request_history_kline(self,code,**kwargs):
            if self.closed:raise AssertionError('quote context already closed')
            calls.append(code)
            return futu.RET_OK,pd.DataFrame(raw_bars(move=.8 if code.endswith(('SOXX','SMH')) else 0)),None
        def close(self):self.closed=True
    ctx=FakeContext()
    monkeypatch.setattr(futu,'OpenQuoteContext',lambda **kwargs:ctx)
    result=market.collect(END,{'slot':END.isoformat()})
    assert ctx.closed
    assert 'US.NVDA' in calls
    semis=[c for c in result['candidates'] if c['cluster']=='semiconductors'][0]
    assert semis['sampled_breadth']['valid']==4
    assert result['rows']['SOXX']['relative_spy_pp'] is not None


def test_history_pagination_reaches_recent_data():
    class Fake:
        calls=[]
        def request_history_kline(self,code,**kwargs):
            self.calls.append(kwargs.get('page_req_key'))
            if kwargs.get('page_req_key') is None:
                return futu.RET_OK,pd.DataFrame(raw_bars(END-timedelta(hours=8))),b'next'
            return futu.RET_OK,pd.DataFrame(raw_bars()),None
    ctx=Fake()
    records=market.fetch_records(ctx,'SPY',END)
    assert ctx.calls==[None,b'next']
    assert market.analyze_ticker('SPY',records,END)['status']=='ok'


def test_opposite_constituent_majority_rejects_sectorwide_claim():
    up=bars('SOXX',[0.0]*30+[0.1]*10)
    extra={name:bars(name,[0.0]*30+[-0.1]*10) for name in ['NVDA','AMD','AVGO','TSM']}
    assert market.cluster_candidates({'SOXX':up},extra)==[]
