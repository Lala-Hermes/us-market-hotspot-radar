"""Read-only BTC/USD minute evidence, separate from ETF share coverage.

The installed SDK drops protobuf KLine.timestamp. Preserve that verified epoch
through an instance-local decoder so crypto display time never implies a zone.
Fail closed when epochs or the installed decoder contract are unavailable.
"""
from datetime import datetime, timedelta, timezone
import math

CODE='CC.BTCUSD'


def epoch_unpack(response):
    from futu import RET_OK
    from futu.quote.quote_query import RequestHistoryKlineQuery
    ret,msg,content=RequestHistoryKlineQuery.unpack_rsp(response)
    if ret!=RET_OK:return ret,msg,content
    raw=[r for r in response.s2c.klList if not r.isBlank]
    rows,more,key=content
    if len(raw)!=len(rows):raise ValueError('BTC source epoch/row count mismatch')
    for original,row in zip(raw,rows):
        if not original.HasField('timestamp') or not math.isfinite(original.timestamp) or original.timestamp<=0:
            raise ValueError('BTC source epoch is missing or invalid')
        row['time_key']=datetime.fromtimestamp(original.timestamp,timezone.utc).isoformat()
        row['source_time_basis']='unix_epoch'
    return ret,msg,(rows,more,key)


def fetch_btc_records(ctx,end,budget):
    from futu import RET_OK,KLType,AuType
    from futu.quote.quote_query import RequestHistoryKlineQuery
    original=ctx._get_sync_query_processor
    decoded=[]
    def processor(pack,unpack):
        if getattr(unpack,'__self__',None) is RequestHistoryKlineQuery:
            def capture(response):
                result=epoch_unpack(response)
                if result[0]==RET_OK:decoded.extend(result[2][0])
                return result
            return original(pack,capture)
        return original(pack,unpack)
    ctx._get_sync_query_processor=processor
    try:
        key=None
        # Read both adjacent calendar dates if the completed window crosses midnight.
        start=(end-timedelta(minutes=43)).date().isoformat()
        for _ in range(3):
            ret,data,key=budget.request(ctx,CODE,start=start,end=end.date().isoformat(),
                ktype=KLType.K_1M,autype=AuType.NONE,max_count=1000,page_req_key=key)
            if ret!=RET_OK:raise RuntimeError(str(data))
            if key is None or (decoded and max(datetime.fromisoformat(r['time_key']) for r in decoded)>=end-timedelta(minutes=1)):
                return decoded
        raise RuntimeError('BTC pagination did not reach target window')
    finally:
        ctx._get_sync_query_processor=original


def collect_btc(ctx,end,budget):
    from radar_market import analyze_ticker
    meta={'instrument':'BTC/USD','source_code':CODE,'source':'Futu OpenD BTC/USD spot pair',
          'volume_unit':'BTC','source_time_basis':'unix_epoch','window_end_et':end.isoformat(),
          'scope':'provider spot pair only; not global Bitcoin volume or IBIT ETF',
          'provider_delay':'not independently verified'}
    try:
        rows=fetch_btc_records(ctx,end,budget)
        result=analyze_ticker(CODE,rows,end)
        result.update(meta)
        if (result['status']!='ok' or result['completed_bars']!=10
                or result['traded_minutes']<6 or result['baseline_source']!='preceding_close'):
            result.update(status='insufficient',reason='BTC/USD同窗口完整分鐘／實際成交／來源時效或前窗邊界不足')
        return result
    except Exception as exc:
        return dict(meta,status='error',reason=f'{type(exc).__name__}: {exc}')


def btc_cross_signals(row):
    value=row.get('return_10m_pct')
    if (row.get('status')!='ok' or value is None or not math.isfinite(value)
            or abs(value)<.6):return []
    return [{'type':'observed_spot_pair_change','instrument':'BTC/USD','source_code':CODE,
             'return_10m_pct':value,'volume_10m':row.get('volume_10m'),'volume_unit':'BTC',
             'source_time':row.get('last_completed_bar'),'window_end_et':row.get('window_end_et'),
             'threshold':'|completed 10-minute return| >= 0.6%',
             'confidence':'observed provider spot-pair change; not a forecast or global breadth',
             'summary':f'BTC/USD現貨幣對10分鐘 {value:+.3f}%（Futu來源，非IBIT）'}]
