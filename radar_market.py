from __future__ import annotations
"""Read-only, time-aligned ETF anomaly evidence; no news or trading APIs."""
from collections import deque
from datetime import datetime, timedelta
import math
from statistics import median
import time
from zoneinfo import ZoneInfo
from pathlib import Path

ET=ZoneInfo('America/New_York')
TICKERS='SPY QQQ IWM DIA XLK XLF XLE XLV XLY XLP XLI XLB XLU XLRE XLC SOXX SMH IGV XBI IBB KRE XOP OIH ITA ARKK IBIT GLD TLT USO'.split()
BROAD={'SPY','QQQ','IWM','DIA'}
CLUSTERS={
 'broad_market':['SPY','IWM','DIA'],'semiconductors':['SOXX','SMH'],
 'energy':['XLE','XOP','OIH'],'oil_proxy':['USO'],'biotechnology':['XBI','IBB'],
 'growth_risk':['QQQ','ARKK'],'technology':['XLK'],'software':['IGV'],
 'financials':['XLF','KRE'],'healthcare':['XLV'],'consumer_discretionary':['XLY'],
 'consumer_staples':['XLP'],'industrials':['XLI'],'materials':['XLB'],
 'utilities':['XLU'],'real_estate':['XLRE'],'communication_services':['XLC'],
 'aerospace_defense':['ITA'],'crypto':['IBIT'],'gold':['GLD'],'duration':['TLT']}
CONSTITUENTS={
 'broad_market':['AAPL','JPM','CAT','WMT'],
 'semiconductors':['NVDA','AMD','AVGO','TSM'],'energy':['XOM','CVX','COP','SLB'],
 'biotechnology':['AMGN','GILD','REGN','VRTX'],'growth_risk':['AAPL','MSFT','AMZN','META'],
 'technology':['AAPL','MSFT','NVDA'],'software':['CRM','NOW','SNOW'],
 'financials':['JPM','BAC','GS'],'healthcare':['LLY','UNH','JNJ'],
 'consumer_discretionary':['AMZN','TSLA','HD'],'consumer_staples':['WMT','COST','PG'],
 'industrials':['GE','CAT','RTX'],'materials':['LIN','FCX','NEM'],
 'utilities':['NEE','SO','DUK'],'real_estate':['PLD','AMT','EQIX'],
 'communication_services':['META','GOOGL','NFLX'],'aerospace_defense':['RTX','LMT','NOC']}
UNSUPPORTED=['VIX（quote sampling未提供有效資料）','美國公債殖利率（quote sampling未提供有效資料）','美元指數','原油現貨／期貨','Bitcoin現貨','選擇權活動']


def _as_et(value):
 if value.tzinfo is None:raise ValueError('window_end must be timezone-aware')
 return value.astimezone(ET).replace(second=0,microsecond=0)


def _time(row):
 value=row.get('time',row.get('time_key'))
 if isinstance(value,datetime):return value.replace(tzinfo=ET) if value.tzinfo is None else value.astimezone(ET)
 parsed=datetime.fromisoformat(str(value))
 return parsed.replace(tzinfo=ET) if parsed.tzinfo is None else parsed.astimezone(ET)


def _num(value):
 try:
  x=float(value); return x if math.isfinite(x) else None
 except (TypeError,ValueError):return None


def analyze_ticker(ticker,candles,window_end):
 end=_as_et(window_end); unique={}
 for original in candles:
  try:
   stamp=_time(original)
   if not end-timedelta(minutes=43)<=stamp<end:continue
   close=_num(original.get('close')); op=_num(original.get('open'))
   volume=_num(original.get('volume')); high=_num(original.get('high')); low=_num(original.get('low'))
   if close is None or close<=0 or volume is None or volume<0:continue
   unique[stamp]={'t':stamp,'close':close,'open':op if op and op>0 else close,
                  'volume':volume,'high':high if high and high>0 else close,
                  'low':low if low and low>0 else close}
  except (ValueError,TypeError,OverflowError):continue
 rows=sorted(unique.values(),key=lambda r:r['t'])
 def segment(finish):
  begin=finish-timedelta(minutes=10)
  block=[r for r in rows if begin<=r['t']<finish]
  trades=[r for r in block if r['volume']>0]
  prior=[r for r in rows if begin-timedelta(minutes=2)<=r['t']<begin]
  base=prior[-1]['close'] if prior else (block[0]['open'] if block else None)
  ret=(trades[-1]['close']/base-1)*100 if trades and base else None
  span=(max(r['high'] for r in trades)-min(r['low'] for r in trades))/trades[-1]['close']*100 if trades else None
  return block,trades,ret,span,'preceding_close' if prior else ('open' if block else None)
 block,trades,ret,span,base_source=segment(end)
 previous=[]
 for minutes in (30,20,10):
  pb,pt,pr,ps,_=segment(end-timedelta(minutes=minutes))
  previous.append(pr if len(pb)>=9 and len(pt)>=3 else None)
 prior_rows=[r for r in rows if end-timedelta(minutes=40)<=r['t']<end-timedelta(minutes=10)]
 prior_volume=sum(r['volume'] for r in prior_rows)
 vol=sum(r['volume'] for r in trades)
 ratio=vol/(prior_volume/3) if len(prior_rows)>=27 and prior_volume>0 else None
 latest=trades[-1]['t'] if trades else None
 fresh=latest is not None and (end-latest).total_seconds()<=120
 valid=len(block)>=9 and len(trades)>=3 and fresh
 def rounded(x):return round(x,5) if x is not None else None
 return {'ticker':ticker,'status':'ok' if valid else 'insufficient',
  'completed_bars':len(block),'traded_minutes':len(trades),'volume_10m':vol,
  'baseline_source':base_source,'return_10m_pct':rounded(ret),
  'previous_10m_pct':rounded(previous[-1]),'acceleration_pp':rounded(ret-previous[-1]) if ret is not None and previous[-1] is not None else None,
  'previous_3_10m_returns_pct':[rounded(x) for x in previous],
  'volume_ratio_10m':rounded(ratio),'baseline_volume_per_10m':prior_volume/3 if len(prior_rows)>=27 else None,
  'range_10m_pct':rounded(span),'previous_range_10m_pct':rounded(segment(end-timedelta(minutes=10))[3]),
  'last_trade_time':latest.isoformat() if latest else None,
  'last_completed_bar':block[-1]['t'].isoformat() if block else None,
  'source_time_zone':'America/New_York','fresh':fresh}


def _valid(row):
 return bool(row and row.get('status')=='ok' and row.get('return_10m_pct') is not None)


def selection_conditions(row, name, floor=None):
 """Single source of truth for the unchanged per-row anomaly gates."""
 if floor is None:floor=.25 if row['ticker'] in BROAD else (.6 if name=='crypto' else .4)
 history=[abs(x) for x in row.get('previous_3_10m_returns_pct',[]) if x is not None]
 threshold=max(floor,2.5*median(history)) if history else floor
 active=row.get('volume_10m',0)>=(10000 if row['ticker'] in BROAD else 5000) and row.get('traded_minutes',0)>=6
 confirmed=((row.get('volume_ratio_10m') or 0)>=1.8 or abs(row.get('relative_spy_pp') or 0)>=.2 or abs(row.get('acceleration_pp') or 0)>=.25)
 return {'threshold':threshold,'price_pass':abs(row['return_10m_pct'])>=threshold,
         'active':active,'confirmed':confirmed}


def cluster_candidates(rows,extra=None):
 extra=extra or {}; candidates=[]
 for name,members in CLUSTERS.items():
  valid=[rows[t] for t in members if _valid(rows.get(t))]
  if not valid:continue
  floor=.25 if any(r['ticker'] in BROAD for r in valid) else (.6 if name=='crypto' else .4)
  triggered=[]
  for row in valid:
   gates=selection_conditions(row,name,floor)
   if gates['price_pass'] and gates['active'] and gates['confirmed']:triggered.append(row)
  if not triggered:continue
  positive=any(r['return_10m_pct']>=floor for r in valid)
  negative=any(r['return_10m_pct']<=-floor for r in valid)
  move=median(r['return_10m_pct'] for r in valid)
  direction='mixed' if positive and negative else ('bullish' if move>0 else 'bearish')
  names=CONSTITUENTS.get(name,[])
  sample=[extra[t] for t in names if _valid(extra.get(t))]
  agrees=sum(r['return_10m_pct']*move>0 for r in sample)
  disagrees=sum(r['return_10m_pct']*move<0 for r in sample)
  if direction!='mixed' and len(sample)>=2 and disagrees/len(sample)>.5:continue
  order=sorted(sample,key=lambda r:r['return_10m_pct'],reverse=direction!='bearish')
  leaders=[r['ticker'] for r in order[:min(2,len(order))]]
  laggards=[r['ticker'] for r in order[-2:] if r['ticker'] not in leaders]
  rel=[r['relative_spy_pp'] for r in valid if r.get('relative_spy_pp') is not None]
  qrel=[r['relative_qqq_pp'] for r in valid if r.get('relative_qqq_pp') is not None]
  volume=[r['volume_ratio_10m'] for r in valid if r.get('volume_ratio_10m') is not None]
  score=35+min(25,max(abs(r['return_10m_pct']) for r in triggered)/floor*8)
  score+=min(15,abs(median(rel))/.2*5) if rel else 0
  score+=min(10,median(volume)/1.8*5) if volume else 0
  score+=10*agrees/len(names) if names else 0
  provisional=bool(names and (len(sample)<2 or agrees/max(1,len(sample))<.5))
  if provisional:score=min(score-10,45)
  if not volume:score-=5
  if any(r.get('baseline_source')!='preceding_close' for r in valid):score-=5
  if round(score)<40:continue
  candidates.append({'cluster':name,'direction':direction,'score':round(max(0,min(100,score))),
   'members':[r['ticker'] for r in valid],'triggered_members':[r['ticker'] for r in triggered],
   'return_10m_pct':round(move,5),'relative_spy_pp':round(median(rel),5) if rel else None,
   'relative_qqq_pp':round(median(qrel),5) if qrel else None,
   'volume_ratio_10m':round(median(volume),5) if volume else None,
   'sampled_breadth':{'valid':len(sample),'denominator':len(names),
     'advancers':sum(r['return_10m_pct']>0 for r in sample),'decliners':sum(r['return_10m_pct']<0 for r in sample),
     'matching_direction':agrees,'valid_fraction':round(len(sample)/len(names),3) if names else 0},
   'leaders':leaders,'laggards':laggards,'representative_returns':{r['ticker']:r['return_10m_pct'] for r in sample},
   'provisional':provisional,'score_method':'啟發式價格／相對強弱／量比／樣本確認；缺資料降分，不預測報酬',
   'evidence':valid})
 return sorted(candidates,key=lambda r:r['score'],reverse=True)[:10]


def cross_signals(rows):
 signals=[]
 def meaningful(t):
  r=rows.get(t,{})
  return _valid(r) and r.get('volume_10m',0)>=(5000 if t in BROAD else 2000)
 for a,b,floor,label in [('QQQ','SPY',.2,'index_divergence'),('IWM','SPY',.3,'small_caps_vs_spy'),('QQQ','DIA',.3,'growth_vs_value_proxies')]:
  if meaningful(a) and meaningful(b):
   difference=rows[a]['return_10m_pct']-rows[b]['return_10m_pct']
   if abs(difference)>=floor:signals.append({'type':label,'tickers':[a,b],'difference_pp':round(difference,5),'proxy_only':True})
 for t,floor in [('TLT',.4),('GLD',.4),('IBIT',.6)]:
  if meaningful('SPY') and meaningful(t) and abs(rows['SPY']['return_10m_pct'])>=.15:
   stock=rows['SPY']['return_10m_pct']; other=rows[t]['return_10m_pct']
   if abs(other)>=floor:signals.append({'type':'cross_asset_divergence' if stock*other<0 else 'cross_asset_co_move','ticker':t,'equity_proxy':'SPY','equity_return_pct':stock,'return_10m_pct':other,'proxy_only':True})
 cyc=[rows[t]['return_10m_pct'] for t in ['XLY','XLI','XLB','XLE','XLF'] if meaningful(t)]
 defense=[rows[t]['return_10m_pct'] for t in ['XLP','XLU','XLV'] if meaningful(t)]
 if len(cyc)>=3 and len(defense)>=2 and abs(median(cyc)-median(defense))>=.3:
  signals.append({'type':'cyclical_vs_defensive','difference_pp':round(median(cyc)-median(defense),5),'cyclical_sample':len(cyc),'defensive_sample':len(defense)})
 return signals,[f'{t}未取得同窗口資料，未納入判斷' for t in UNSUPPORTED]


def quote_cross_signals(changes):
 signals=[]
 for symbol,label,key,threshold,unit in (
  ('^VIX','VIX','change_points',1.0,'index points'),
  ('^TNX','US10Y','change_basis_points',3.0,'basis points')):
  row=changes.get(symbol,{})
  try: value=float(row.get(key))
  except (TypeError,ValueError): continue
  if not math.isfinite(value) or abs(value)<threshold:continue
  signals.append({'type':'observed_quote_change','instrument':label,'change':value,'unit':unit,
   'threshold':f'|change| >= {threshold} {unit} in observed ~10-minute pair',
   'elapsed_seconds':row.get('elapsed_seconds'),'source':row.get('source'),
   'source_time':row.get('source_time'),'previous_source_time':row.get('previous_source_time'),
   'confidence':row.get('confidence','reduced; price-only observed quote change, not a forecast')})
 return signals


def sample_market_quotes(book, fetcher=None, diagnostic=False, now=None):
 from radar_quotes import QuoteBook, fetch_yahoo_quote
 fetcher=fetcher or fetch_yahoo_quote
 book=book if isinstance(book,QuoteBook) else QuoteBook(book)
 observations={}; changes={}
 for symbol in ('^VIX','^TNX'):
  try:
   quote=fetcher(symbol)
   if quote is None:
    observations[symbol]={'status':'invalid','reason':'provider returned no verified snapshot metadata'}
    continue
   outcome=book.observe(quote,diagnostic=diagnostic,now=now)
   status=outcome.get('status') if isinstance(outcome,dict) and outcome.get('status') in ('invalid','stale') else ('warmup' if outcome is None else 'observed')
   observations[symbol]={'status':status,'quote':quote}
   if isinstance(outcome,dict) and status=='observed':changes[symbol]=outcome
  except Exception as exc:
   observations[symbol]={'status':'error','reason':f'{type(exc).__name__}: {exc}'}
 return observations,changes


class RequestBudget:
 """At most 50 quote-history requests in a rolling 30-second window."""
 def __init__(self):self.calls=deque()
 def request(self,ctx,*args,**kwargs):
  stamp=time.monotonic()
  while self.calls and stamp-self.calls[0]>=30:self.calls.popleft()
  if len(self.calls)>=50:
   time.sleep(max(0,30-(stamp-self.calls[0]))+.1)
   stamp=time.monotonic()
   while self.calls and stamp-self.calls[0]>=30:self.calls.popleft()
  self.calls.append(stamp)
  return ctx.request_history_kline(*args,**kwargs)


def fetch_records(ctx,ticker,end,budget=None):
 from futu import RET_OK,KLType,AuType,Session
 end=_as_et(end); records=[]; key=None
 for page in range(3):
  kwargs={'start':end.date().isoformat(),'end':end.date().isoformat(),'ktype':KLType.K_1M,
          'autype':AuType.NONE,'session':Session.ALL,'max_count':1000,'page_req_key':key}
  ret,data,key=budget.request(ctx,'US.'+ticker,**kwargs) if budget else ctx.request_history_kline('US.'+ticker,**kwargs)
  if ret!=RET_OK:raise RuntimeError(str(data))
  batch=data.to_dict('records') if hasattr(data,'to_dict') else list(data or [])
  records.extend(batch)
  if key is None or (batch and max(_time(r) for r in batch)>=end-timedelta(minutes=1)):return records
 raise RuntimeError('history pagination truncated before target window; data is unknown')


def collect(window_end,info):
 from futu import OpenQuoteContext
 end=_as_et(window_end)
 report={'status':'ok','universe':list(TICKERS),'rows':{},'candidates':[],
         'cross_signals':[],'errors':[],'gaps':[],'coverage':{},'constituents':{},
         'source':{'name':'Futu OpenD','host':'127.0.0.1:11111','window_end_et':end.isoformat()}}
 ctx=None; budget=RequestBudget()
 try:
  ctx=OpenQuoteContext(host='127.0.0.1',port=11111)
  for ticker in TICKERS:
   try:
    row=analyze_ticker(ticker,fetch_records(ctx,ticker,end,budget),end)
    report['rows'][ticker]=row
    if not _valid(row):report['errors'].append({'ticker':ticker,'error':'完整分鐘／實際成交／來源時效不足','completed_bars':row['completed_bars'],'traded_minutes':row['traded_minutes'],'last_trade_time':row['last_trade_time']})
   except Exception as exc:
    report['rows'][ticker]={'ticker':ticker,'status':'error','return_10m_pct':None}
    report['errors'].append({'ticker':ticker,'error':f'{type(exc).__name__}: {exc}'})
  # Relative strength must be set BEFORE selecting which clusters to confirm.
  for row in report['rows'].values():
   if _valid(row):
    for benchmark,key in [('SPY','relative_spy_pp'),('QQQ','relative_qqq_pp')]:
     base=report['rows'].get(benchmark)
     row[key]=round(row['return_10m_pct']-base['return_10m_pct'],5) if _valid(base) else None
  initial=cluster_candidates(report['rows'])
  names=list(dict.fromkeys(t for candidate in initial for t in CONSTITUENTS.get(candidate['cluster'],[])))[:30]
  for ticker in names:
   try:report['constituents'][ticker]=analyze_ticker(ticker,fetch_records(ctx,ticker,end,budget),end)
   except Exception as exc:
    report['constituents'][ticker]={'ticker':ticker,'status':'error','return_10m_pct':None}
    report['gaps'].append(f'代表股{ticker}取樣失敗：{type(exc).__name__}: {exc}')
  report['candidates']=cluster_candidates(report['rows'],report['constituents'])
  report['cross_signals'],unsupported=cross_signals(report['rows']); report['gaps'].extend(unsupported)
  report['gaps'].append('成分股廣度是最多30檔代表股取樣，並非完整ETF成分股；未確認異常前不調查新聞。')
  report['coverage']={'requested_count':len(TICKERS),'returned_count':len(report['rows']),
    'usable_count':sum(_valid(r) for r in report['rows'].values()),
    'major_valid_count':sum(_valid(report['rows'].get(t)) for t in BROAD),
    'meaningful_trade_count':sum(_valid(r) and r.get('volume_10m',0)>=(10000 if t in BROAD else 5000) for t,r in report['rows'].items())}
  if report['errors']:report['status']='partial'
 except Exception as exc:
  report['status']='blocked'; report['errors'].append({'error':f'Futu/OpenD unavailable: {type(exc).__name__}: {exc}'})
 finally:
  if ctx is not None:ctx.close()
 observations,changes=sample_market_quotes(Path(__file__).resolve().parent/'.state'/'quotes.sqlite',
  diagnostic=bool(info.get('diagnostic')))
 report['quotes']=observations
 report['quote_changes']=changes
 if '^VIX' in changes:
  report['gaps']=[g for g in report['gaps'] if 'VIX' not in g]
 if '^TNX' in changes:
  report['gaps']=[g for g in report['gaps'] if '公債殖利率' not in g]
 report['cross_signals'].extend(quote_cross_signals(changes))
 for symbol,item in observations.items():
  if item.get('status')!='observed':
   label='VIX' if symbol=='^VIX' else '美國10年期公債殖利率'
   report['gaps'].append(f'{label}報價狀態：{item.get("status")}；{item.get("reason", "需等待兩筆有效且同源觀察") }')
 return report
