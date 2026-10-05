from __future__ import annotations
import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time as clock
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import exchange_calendars as xcals

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'.state'
ET=ZoneInfo('America/New_York')
TAIPEI=ZoneInfo('Asia/Taipei')
CAL=xcals.get_calendar('XNYS')
TICKERS='SPY QQQ IWM DIA XLK XLF XLE XLV XLY XLP XLI XLB XLU XLRE XLC SOXX SMH IGV XBI IBB KRE XOP OIH ITA ARKK IBIT GLD TLT'.split()
EXPECTED_REMOTE='https://github.com/Lala-Hermes/us-market-hotspot-radar.git'


def _session(d: date):
    try:
        return CAL.date_to_session(d.isoformat(),direction='none')
    except (ValueError,xcals.errors.DateOutOfBounds,xcals.errors.NotSessionError):
        return None


def gate(now: datetime|None=None):
    now=now or datetime.now(TAIPEI)
    if now.tzinfo is None:
        raise ValueError('clock must include an explicit time zone')
    local=now.astimezone(TAIPEI)
    slot=local.replace(minute=(local.minute//10)*10,second=0,microsecond=0)
    if (local-slot).total_seconds()>300:
        return 'IDLE'
    for trade_date in (local.date(),local.date()-timedelta(days=1)):
        session=_session(trade_date)
        if session is None:
            continue
        start=datetime.combine(trade_date,time(21,20),TAIPEI)
        close=CAL.session_close(session).to_pydatetime().astimezone(TAIPEI)
        if start<=slot<=close:
            end_et=slot.astimezone(ET)
            open_et=CAL.session_open(session).to_pydatetime().astimezone(ET)
            state='收盤窗口' if slot==close else ('盤前' if end_et<open_et else '正常盤')
            return {'active':True,'slot':slot.isoformat(),'trading_date':trade_date.isoformat(),
                    'window_start':(slot-timedelta(minutes=10)).isoformat(),'window_end':slot.isoformat(),
                    'time_et':end_et.isoformat(),'time_taipei':slot.isoformat(),
                    'market_state':state,'scheduled_close':close.isoformat()}
    return 'IDLE'


def completed_window(candles,window_end: datetime):
    end=window_end.astimezone(ET).replace(second=0,microsecond=0)
    rows=[]
    for raw in candles:
        t=datetime.fromisoformat(str(raw.get('time',raw.get('time_key')))[:19]).replace(tzinfo=ET)
        if t+timedelta(minutes=1)<=end:
            row=dict(raw); row['_parsed_time']=t; rows.append(row)
    return sorted(rows,key=lambda r:r['_parsed_time'])


def append_slot(content: str,slot: str,entry: str)->str:
    marker=f'<!-- radar-slot:{slot} -->'
    if marker in content:
        return content
    return content.rstrip()+f'\n\n{marker}\n{entry.rstrip()}\n'


def _slot_key(slot):
    parsed=datetime.fromisoformat(slot)
    if parsed.tzinfo is None or parsed.astimezone(TAIPEI).isoformat()!=slot:
        raise ValueError('slot must be a canonical Taipei timestamp')
    return slot.replace(':','').replace('-','')


def _atomic_bytes(path: Path,data: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_json(path: Path,obj):
    _atomic_bytes(path,json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8'))


@contextlib.contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:
            handle.write(b'0'); handle.flush()
        deadline=clock.monotonic()+15
        while True:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if clock.monotonic()>=deadline:
                    raise TimeoutError('publication/scan lock is busy')
                clock.sleep(.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def scan(info,diagnostic=False,collector=None):
    slot=info['slot']; key=_slot_key(slot)
    if not diagnostic:
        valid=gate(datetime.fromisoformat(slot))
        if valid=='IDLE' or valid['trading_date']!=info['trading_date']:
            raise ValueError('not an eligible production slot')
    path=STATE/('diagnostics' if diagnostic else 'scans')/(key+'.json')
    with _file_lock(STATE/('scan-'+key+'.lock')):
        if not diagnostic and path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        if collector is None:
            from radar_market import collect
            collector=collect
        end=datetime.fromisoformat(slot).astimezone(ET)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result=collector(end,info)
        except Exception as exc:
            result={'status':'blocked','candidates':[],'rows':[],'cross_signals':[],
                    'errors':[{'error':f'{type(exc).__name__}: {exc}'}],'gaps':['market collection failed']}
        result.update({'production':not diagnostic,'diagnostic':diagnostic,'slot':slot,
                       'trading_date':info.get('trading_date',end.date().isoformat()),
                       'window_start':(end-timedelta(minutes=10)).isoformat(),'window_end':slot,
                       'scan_timestamp':datetime.now(TAIPEI).isoformat(),
                       'market_state':info.get('market_state','診斷窗口'),'snapshot_path':str(path.resolve())})
        _atomic_json(path,result)
        return result


def _git(*args):
    result=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,timeout=60)
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode('utf-8',errors='replace').strip()}")
    return result.stdout


def publish(slot: str,report_path: Path):
    key=_slot_key(slot)
    report_path=Path(report_path).resolve()
    if not report_path.is_relative_to(STATE.resolve()):
        raise ValueError('report must be inside private state directory')
    snapshot=json.loads((STATE/'scans'/(key+'.json')).read_text(encoding='utf-8'))
    valid=gate(datetime.fromisoformat(slot))
    if (snapshot.get('production') is not True or snapshot.get('diagnostic') is not False
        or snapshot.get('slot')!=slot or snapshot.get('window_end')!=slot or valid=='IDLE'
        or snapshot.get('trading_date')!=valid['trading_date']):
        raise ValueError('saved production snapshot does not match exact eligible slot')
    entry=report_path.read_text(encoding='utf-8')
    if not entry.strip() or len(entry)>200_000 or '<!-- radar-slot:' in entry:
        raise ValueError('invalid or empty report entry')
    trade_date=snapshot['trading_date']; target=ROOT/'reports'/(trade_date+'.md')
    relative=target.relative_to(ROOT).as_posix()
    with _file_lock(STATE/'publish.lock'):
        if _git('remote','get-url','origin').decode().strip()!=EXPECTED_REMOTE:
            raise ValueError('origin does not match authorized radar repository')
        if _git('symbolic-ref','--short','HEAD').decode().strip()!='main':
            raise ValueError('publisher requires the main branch')
        current=target.read_text(encoding='utf-8') if target.exists() else f'# {trade_date} 美股10分鐘熱點雷達\n'
        updated=append_slot(current,slot,entry)
        if updated!=current:
            _atomic_bytes(target,updated.encode('utf-8'))
        _git('add','--',relative)
        if _git('diff','--cached','--name-only','--',relative).strip():
            _git('commit','--only','-m',f'Radar {trade_date} {slot}','--',relative)
        _git('push','origin','HEAD:refs/heads/main')
        _git('fetch','origin','refs/heads/main')
        commit=_git('rev-parse','FETCH_HEAD').decode().strip()
        remote=_git('show',f'{commit}:{relative}')
        if remote.replace(b'\r\n',b'\n')!=target.read_bytes().replace(b'\r\n',b'\n'):
            raise RuntimeError('exact remote report verification mismatch')
        return {'verified':True,'slot':slot,'path':relative,'commit':commit}


def render_quiet_report(info,result):
    end=datetime.fromisoformat(info['slot']).astimezone(ET); start=end-timedelta(minutes=10)
    lines=['🚨 10 分鐘市場熱點雷達',f"資料時間：{end.astimezone(TAIPEI):%Y-%m-%d %H:%M} 台北時間",
           f'美東時間：{end:%Y-%m-%d %H:%M} ET',f'觀察窗口：{start:%H:%M}～{end:%H:%M} ET（完整分鐘線）',
           f"市場狀態：{info.get('market_state','未確認')}",'',
           '最近 10 分鐘沒有發現具有足夠可信度的市場熱點。','',
           f"掃描範圍：{len(result.get('universe',TICKERS))} 檔 ETF；沒有通過綜合異常篩選的聚類。",
           '此結論限於可用資料，不代表全市場完全平靜。','','Cross-Market Signals：']
    signals=result.get('cross_signals',[])
    lines.extend('- '+json.dumps(item,ensure_ascii=False) for item in signals)
    if not signals:
        lines.append('已取得資料未形成通過門檻的明顯跨市場訊號。')
    rows=result.get('rows',[])
    if isinstance(rows,dict):
        rows=list(rows.values())
    for row in rows:
        ticker=row.get('ticker',row.get('symbol','?')); ret=row.get('return_10m_pct')
        if ret is not None and ticker in ('SPY','QQQ','IWM','DIA'):
            lines.append(f"- {ticker}：10分鐘 {ret:+.3f}%；窗口量 {row.get('volume_10m','未知')}；量比 {row.get('volume_ratio_10m','未知')}")
    coverage=result.get('coverage',{})
    if coverage:
        lines.append(f"資料覆蓋：{coverage.get('usable_count',0)}/{coverage.get('requested_count',len(TICKERS))} 檔有足夠完整分鐘、實際成交及來源時效。")
    if result.get('gaps'):
        lines.extend(['','資料限制：']+['- '+str(g) for g in result['gaps']])
    lines.extend(['','來源：本機 Futu OpenD 24H 一分鐘歷史 K 線；價格和成交量使用上述精確窗口，未以全天快照代替。',
                  f"擷取時間：{result.get('scan_timestamp','未知')}；無確認異常，因此未搜尋新聞催化劑。"])
    return '\n'.join(lines)+'\n'


def tick(now=None):
    info=gate(now)
    if info=='IDLE':
        print(json.dumps({'wakeAgent':False},separators=(',',':'))); return 0
    result=scan(info)
    if result.get('candidates') or result.get('cross_signals'):
        print(json.dumps({'wakeAgent':True,'slot':info['slot'],'snapshot_path':result['snapshot_path'],
                          'status':result.get('status'),'candidate_count':len(result.get('candidates',[])),
                          'errors':result.get('errors',[])},ensure_ascii=False,separators=(',',':'))); return 0
    path=STATE/('report-'+_slot_key(info['slot'])+'.md')
    text=render_quiet_report(info,result)
    if result.get('status')!='ok' or result.get('errors'):
        text=text.replace('最近 10 分鐘沒有發現具有足夠可信度的市場熱點。','本輪資料不足，無法可靠判定最近10分鐘熱點。')
        text+='\n資料阻擋：\n'+'\n'.join('- '+json.dumps(e,ensure_ascii=False) for e in result.get('errors',[]))+'\n'
    _atomic_bytes(path,text.encode('utf-8'))
    try:
        verified=publish(info['slot'],path)
    except Exception as exc:
        print(json.dumps({'wakeAgent':True,'slot':info['slot'],'snapshot_path':result['snapshot_path'],
                          'publication_error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False)); return 1
    print(json.dumps({'wakeAgent':False,'publication':verified},separators=(',',':'))); return 0


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest='command',required=True)
    for name in ('gate','tick','scan'):
        p=sub.add_parser(name); p.add_argument('--now')
        if name=='scan':
            p.add_argument('--diagnostic',action='store_true')
    p=sub.add_parser('publish'); p.add_argument('--slot',required=True); p.add_argument('--report',required=True)
    args=parser.parse_args(); now=datetime.fromisoformat(args.now) if getattr(args,'now',None) else None
    if args.command=='gate':
        result=gate(now); print(result if result=='IDLE' else json.dumps(result,ensure_ascii=False)); return 0
    if args.command=='tick':
        return tick(now)
    if args.command=='scan':
        info=gate(now)
        if args.diagnostic:
            stamp=(now or datetime.now(TAIPEI)).astimezone(TAIPEI)
            slot=stamp.replace(minute=(stamp.minute//10)*10,second=0,microsecond=0)
            info={'slot':slot.isoformat(),'trading_date':slot.astimezone(ET).date().isoformat(),'market_state':'診斷窗口'}
        elif info=='IDLE':
            print(json.dumps({'wakeAgent':False})); return 0
        print(json.dumps(scan(info,diagnostic=args.diagnostic),ensure_ascii=False)); return 0
    print(json.dumps(publish(args.slot,Path(args.report)),separators=(',',':'))); return 0


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
