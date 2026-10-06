from datetime import datetime
from pathlib import Path
import json
import subprocess
import pytest
import radar


def run_git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, check=True).stdout


@pytest.fixture
def publication_repo(tmp_path, monkeypatch):
    root = tmp_path / 'work'
    remote = tmp_path / 'remote.git'
    root.mkdir()
    subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
    run_git(root,'init','-b','main')
    run_git(root,'config','user.name','Radar Test')
    run_git(root,'config','user.email','test@example.invalid')
    run_git(root,'config','core.autocrlf','false')
    (root/'README.md').write_text('test repository\n',encoding='utf-8')
    run_git(root,'add','README.md'); run_git(root,'commit','-m','init')
    run_git(root,'remote','add','origin',str(remote)); run_git(root,'push','-u','origin','main')
    monkeypatch.setattr(radar,'ROOT',root)
    monkeypatch.setattr(radar,'STATE',root/'.state')
    # Dependency-injected local bare remote, never production GitHub.
    monkeypatch.setattr(radar,'EXPECTED_REMOTE',str(remote),raising=False)
    slot='2026-10-05T21:20:00+08:00'
    state=root/'.state'; (state/'scans').mkdir(parents=True)
    scan=state/'scans'/f"{slot.replace(':','').replace('-','')}.json"
    scan.write_text(json.dumps({'production':True,'diagnostic':False,'slot':slot,'trading_date':'2026-10-05','window_end':slot}),encoding='utf-8')
    report=state/'one.md'; report.write_text('🚨 實際發布單元測試（本地裸庫）\n',encoding='utf-8')
    return root,remote,slot,report,scan


@pytest.mark.skipif(__import__('os').name!='nt', reason='Windows background handle regression')
def test_git_with_invalid_background_stdin_handle():
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetStdHandle.argtypes=[wintypes.DWORD]
    kernel.GetStdHandle.restype=wintypes.HANDLE
    kernel.SetStdHandle.argtypes=[wintypes.DWORD,wintypes.HANDLE]
    kernel.SetStdHandle.restype=wintypes.BOOL
    stdin_id=wintypes.DWORD(-10)
    original=kernel.GetStdHandle(stdin_id)
    assert kernel.SetStdHandle(stdin_id,wintypes.HANDLE(-1))
    try:
        assert radar._git('rev-parse','--is-inside-work-tree').strip()==b'true'
    finally:
        assert kernel.SetStdHandle(stdin_id,original)


def test_publish_accepts_markdown_and_verifies_remote(publication_repo):
    root,remote,slot,report,_=publication_repo
    result=radar.publish(slot,report)
    assert result['verified'] is True
    assert result['path']=='reports/2026-10-05.md'
    content=run_git(remote,'show','main:reports/2026-10-05.md').decode('utf-8')
    assert report.read_text(encoding='utf-8') in content
    assert content.count('<!-- radar-slot:')==1


def test_publish_preserves_old_slot_blocks_and_adds_stable_latest_navigation(publication_repo):
    root,remote,slot,report,_=publication_repo
    target=root/'reports'/'2026-10-05.md'
    old='''# 2026-10-05 美股10分鐘熱點雷達

<!-- radar-slot:2026-10-05T21:10:00+08:00 -->
## 21:10 台北／09:10 ET｜舊輪摘要
舊內容逐字保留。
'''
    target.parent.mkdir(); target.write_text(old,encoding='utf-8')
    radar.publish(slot,report)
    content=target.read_text(encoding='utf-8')
    assert old.split('\n\n',1)[1] in content
    assert '<!-- radar-latest:start -->' in content and '<!-- radar-latest:end -->' in content
    assert '[跳至最新一輪](#radar-2026-10-05t2120000800)' in content
    assert '<a id="radar-2026-10-05t2120000800"></a>' in content
    assert content.count('radar-methodology') == 1


def test_publish_retry_does_not_duplicate_and_preserves_other_staging(publication_repo):
    root,remote,slot,report,_=publication_repo
    (root/'unrelated.txt').write_text('never publish me',encoding='utf-8')
    run_git(root,'add','unrelated.txt')
    first=radar.publish(slot,report)
    second=radar.publish(slot,report)
    assert first['commit']==second['commit']
    assert run_git(root,'diff','--cached','--name-only').decode().strip()=='unrelated.txt'
    assert 'unrelated.txt' not in run_git(remote,'ls-tree','--name-only','main').decode()


def test_publish_resume_after_failed_push(publication_repo,monkeypatch):
    root,remote,slot,report,_=publication_repo
    real_run=radar._git
    def fail_push(*args,**kwargs):
        if args and args[0]=='push':
            raise RuntimeError('test simulated network failure')
        return real_run(*args,**kwargs)
    monkeypatch.setattr(radar,'_git',fail_push)
    with pytest.raises(RuntimeError,match='network failure'):
        radar.publish(slot,report)
    count=run_git(root,'rev-list','--count','HEAD').strip()
    monkeypatch.setattr(radar,'_git',real_run)
    result=radar.publish(slot,report)
    assert result['verified']
    assert run_git(root,'rev-list','--count','HEAD').strip()==count
    assert (root/'reports'/'2026-10-05.md').read_text(encoding='utf-8').count('<!-- radar-slot:')==1


def test_publish_rejects_diagnostic(publication_repo):
    root,remote,slot,report,scan=publication_repo
    data=json.loads(scan.read_text()); data['production']=False; data['diagnostic']=True
    scan.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='production'):
        radar.publish(slot,report)
    assert not (root/'reports').exists()


def test_publish_rejects_report_outside_private_state(publication_repo):
    root,remote,slot,report,scan=publication_repo
    other=root/'outside.md'; other.write_text('not authorized',encoding='utf-8')
    with pytest.raises(ValueError,match='state'):
        radar.publish(slot,other)


def test_close_slot_accepts_normal_scheduler_latency():
    result=radar.gate(datetime.fromisoformat('2026-10-06T04:00:45+08:00'))
    assert result['slot']=='2026-10-06T04:00:00+08:00'
    assert radar.gate(datetime.fromisoformat('2026-10-06T04:06:00+08:00'))=='IDLE'


def test_early_close_and_winter_schedule():
    result=radar.gate(datetime.fromisoformat('2026-11-28T02:00:15+08:00'))
    assert result['trading_date']=='2026-11-27'
    assert radar.gate(datetime.fromisoformat('2026-11-28T02:10:00+08:00'))=='IDLE'
    result=radar.gate(datetime.fromisoformat('2026-12-01T21:20:00+08:00'))
    assert datetime.fromisoformat(result['window_end']).astimezone(radar.ET).hour==8
    assert isinstance(radar.gate(datetime.fromisoformat('2026-12-02T05:00:15+08:00')),dict)


def test_tick_quiet_publishes_without_model(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(radar,'STATE',tmp_path)
    monkeypatch.setattr(radar,'scan',lambda *a,**k:{'status':'ok','errors':[],'candidates':[],'rows':[],'cross_signals':[],'gaps':['options unavailable']})
    calls=[]
    monkeypatch.setattr(radar,'publish',lambda slot,path:(calls.append((slot,path.read_text(encoding='utf-8'))) or {'verified':True,'commit':'abc','path':'reports/2026-10-05.md'}))
    assert radar.tick(datetime.fromisoformat('2026-10-05T21:20:00+08:00'))==0
    assert len(calls)==1
    assert len(calls)==1 and '市場一句話：' in calls[0][1]
    assert '觀察窗口：09:10～09:20 ET｜盤前' in calls[0][1]
    assert '<details><summary>本輪數據與查核明細</summary>' in calls[0][1]
    assert 'radar-methodology' not in calls[0][1]
    assert json.loads(capsys.readouterr().out)['wakeAgent'] is False


def test_tick_data_gaps_publish_blocked_report_without_claiming_calm(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(radar,'STATE',tmp_path)
    monkeypatch.setattr(radar,'scan',lambda *a,**k:{'status':'blocked','snapshot_path':'local.json','errors':[{'ticker':'SPY','error':'permission denied'}],'candidates':[],'rows':[],'cross_signals':[],'gaps':['quotes unavailable']})
    calls=[]
    monkeypatch.setattr(radar,'publish',lambda slot,path:(calls.append(path.read_text(encoding='utf-8')) or {'verified':True,'commit':'abc'}))
    assert radar.tick(datetime.fromisoformat('2026-10-05T21:20:00+08:00'))==0
    assert '本輪資料不足，無法可靠判定最近10分鐘熱點。' in calls[0]
    assert '最近 10 分鐘沒有發現具有足夠可信度的市場熱點。' not in calls[0]
    assert 'permission denied' not in calls[0].split('<details>',1)[0]
    assert 'permission denied' in calls[0]
    assert json.loads(capsys.readouterr().out)['wakeAgent'] is False


def test_tick_candidate_wakes_agent_with_exact_snapshot(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(radar,'STATE',tmp_path)
    monkeypatch.setattr(radar,'scan',lambda *a,**k:{'status':'partial','snapshot_path':'exact.json','errors':[],'candidates':[{'cluster':'semiconductors'}],'cross_signals':[]})
    monkeypatch.setattr(radar,'publish',lambda *a:(_ for _ in ()).throw(AssertionError('must not auto-publish candidate')))
    assert radar.tick(datetime.fromisoformat('2026-10-05T21:20:00+08:00'))==0
    out=json.loads(capsys.readouterr().out)
    assert out['wakeAgent'] is True and out['snapshot_path']=='exact.json'


def test_scan_cache_is_immutable_and_diagnostic_cannot_overwrite(tmp_path,monkeypatch):
    monkeypatch.setattr(radar,'STATE',tmp_path)
    info=radar.gate(datetime.fromisoformat('2026-10-05T21:20:00+08:00'))
    calls=[]
    def collector(end,meta):
        calls.append(end)
        return {'status':'ok','rows':[],'candidates':[],'errors':[],'gaps':[]}
    first=radar.scan(info,collector=collector)
    second=radar.scan(info,collector=collector)
    diagnostic=radar.scan(info,diagnostic=True,collector=collector)
    assert first==second
    assert len(calls)==2
    assert first['snapshot_path']!=diagnostic['snapshot_path']
    assert json.loads(Path(first['snapshot_path']).read_text())['production'] is True
